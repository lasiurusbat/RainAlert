# RainAlert refactor plan

Status as of 2026-10-22: **steps 0–12 done** on the `refactor/modules`
branch. One item is open: `/calendar.ics` on `Day`s (step 7). Checked items (`[x]`)
are finished and can be seen in the repository; unchecked items (`[ ]`) are
open.

The goal is to split `app.py` into modules that each own one layer, without
changing a single byte of what the site serves. Every step below is one
commit, leaves the offline suite at 359/359, and changes no behaviour except
in step 6, where two copies of one rule become one.

## 1. Where we are

| Area | Files | Lines | Shape |
|---|---|---|---|
| Server | `app.py` | 2,074 | One module: config, domain rules, upstream clients, presentation, SEO, iCalendar, routes |
| Data | `cities.py`, `releases.py` | 122 / 85 | Already separate |
| Templates | 5 files | ~550 | Fine; `index.html` holds two inline macros |
| Browser | `static/app.js` | 750 | One IIFE, in clearly marked sections |
| Styles | `static/style.css` | 1,400 | One file, in clearly marked sections |
| Tests | `test_app.py`, `test_browser.py`, `test_api.py` | 3,032 / 1,622 / 131 | 33 classes in one offline file; fixtures duplicated between suites |

The server is the problem; everything else is either already split or does
not need to be. `app.py` has thirteen sections that fall into five layers,
and the layers call each other in a tangle:

```
config (env)  ──►  domain rules  ──►  presentation (labels, sentences)  ──►  routes
                      ▲                       ▲
upstream clients ─────┘ (fetch_weather builds the view model itself)
```

## 2. What is wrong with `app.py`

1. **`fetch_weather()` does three jobs.** It makes the HTTP call, parses the
   payload and builds the template's view model (`rain_label`,
   `hourly_title`, `day_when`, …) in one 135-line function. The client
   cannot be tested without the presentation, and `/calendar.ics` and
   `/api/alert` build every label only to throw them away.
2. **Four functions name a day.** `forecast_day_label`, `tab_day_label`,
   `day_panel_name` and `day_phrases` all encode "0 is today, 1 is
   tomorrow, otherwise the weekday", with small variations ("on Friday",
   "Friday", "Today"). Four copies of one rule can drift apart, which is
   exactly the disagreement the project's conventions forbid.
3. **"Judge today on the hours that are left" is written twice**, once in
   `forecast_headline` and once in `tab_alert`. These are the banner and
   the tab title, which must never disagree, and they are two
   implementations.
4. **The hourly data is parsed twice per request.** `fetch_weather` calls
   `parse_hourly_days`, then `parse_today_hours`, which calls
   `parse_hourly_days` and `local_now` again.
5. **The hour entries are template dicts used as domain data.**
   `hour_moment()` rebuilds a `datetime` from `hour["day"]` and
   `hour["hour"]` because the dict has lost it. `notification_event` and
   `summarise_hours` reason over presentation dicts.
6. **The error-to-message mapping is written three times.**
   `render_forecast_page`, `api_alert` and `calendar_export` each catch the
   three exceptions, write their own English (already slightly different
   from each other), log and pick a status.
7. **The Open Graph and structured-data arguments are repeated** in four
   `render_template` calls: the cities index, the release notes, the 404
   and the forecast page.
8. **`calendar_failure()` returns a Flask `Response`** from inside the
   iCalendar section, so the HTTP layer leaks into otherwise pure code.
9. **Configuration is read into module globals at import**, and there is no
   app factory. That works, but it is why the tests patch module attributes.
10. **There are two slug functions.** `city_slug` folds accents and keeps 60
    characters; `calendar_slug` does neither and keeps 40. **This difference
    must stay**: the calendar's event ids are built from `calendar_slug`, and
    a changed id makes a re-import add a second copy of every event instead
    of updating it.

## 3. Constraints the refactor has to respect

- **The tests' patch targets.** The suites do `import app as rainalert` and
  patch:
  - `rainalert.requests.get` and `rainalert.geolocator.geocode`. These keep
    working as long as the client calls `requests.get` (never
    `from requests import get`) and the shim re-exports the same
    `geolocator` instance.
  - `rainalert.DONATION_URL`, `APP_VERSION`, `APP_COMMIT`,
    `SEVERITY_LOW_MAX` and `SEVERITY_MODERATE_MAX`. **Patching a re-exported
    name does nothing to the module that reads it.** Every one of these
    patches has to move to the owning module in the same commit as the code.
    `test_bands_are_configurable` fails loudly if it is missed; the
    donation and build-info tests may not all be as loud.
- **The context processor** reads `DONATION_URL` and the build info on each
  request, from whichever module the tests patch.
- **Endpoint names.** The templates call `url_for` with `index`,
  `city_page`, `cities_index`, `release_notes`, `calendar_export` and
  `manifest`. Blueprints would rename them (`pages.index`), so the routes
  are registered on the one app object with `register(app)` functions, and
  the names stay. `TestApiDocumentation` walks `app.url_map`; the rules do
  not change, so `API.md` and `openapi.yaml` stay correct.
- **Entry points.** gunicorn runs `app:app`, the documents say
  `python app.py`, and the `Dockerfile` copies `app.py cities.py
  releases.py` by name. The new package must be added to that `COPY`, or
  the image builds and then fails on import.
- **Calendar event ids** stay byte-for-byte the same (see 2.10).
- **The project's conventions.** `render_forecast_page()` stays the one
  builder of the forecast page's title, description, canonical link,
  robots and structured data. `UMBRELLA_THRESHOLD` stays the one threshold
  for the banner, the ☔, the tab and the favicon. The test count appears in
  four documents, and all four are updated together.

## 4. Where we are going

```
app.py                      # thin shim: from rainalert.web import create_app; app = create_app()
                            #   keeps `app:app` and `python app.py`; re-exports for the tests until step 11
rainalert/
  __init__.py
  config.py                 # every os.getenv, clean_donation_url, SITE_URL, APP_VERSION/COMMIT,
                            #   thresholds, timeouts, notification timings
  errors.py                 # CityNotFound, GeocodingUnavailable, WeatherUnavailable
                            #   + one table: exception -> message, page status, API status
  data/
    cities.py               # moved from the root
    releases.py             # moved from the root
  upstream/
    geocoding.py            # geolocator, get_coordinates (the lru_cache stays on it)
    open_meteo.py           # FORECAST_URL, the field lists, fetch_payload() -> raw JSON
  domain/
    model.py                # dataclasses: Hour(moment, chance), Day(iso_date, chance, high, low,
                            #   amount, rain_hours, hours)
    parse.py                # payload -> list[Day], parsed once: parse_hour_timestamp, local_now,
                            #   parse_hourly_days
    rain.py                 # rain_chance, chance_number, severity_band, needs_umbrella,
                            #   round_half_up, alert_threshold
    days.py                 # one day-naming rule with its variants: caption, tab, panel, summary
    alerts.py               # first_alert_day(), shared by the headline and the tab;
                            #   forecast_headline, tab_alert, summarise_hours, notification_event
  present/
    labels.py               # format_date*, format_rain_chance*, describe_rain_chance,
                            #   format_precipitation, format_rain_hours, format_temperature,
                            #   severity_label, hour_height_step
    forecast_view.py        # Day -> the dict the template renders; Hour -> the strip's dicts
    seo.py                  # city_slug, city_from_slug, city_path, short_city_name, page_title,
                            #   page_description, canonical_url, structured_data, page_meta()
  calendar_ics.py           # pure: escape, fold, day, next_day, calendar_slug (unchanged), build_calendar
  web/
    __init__.py             # create_app(): the Flask app, the context processor, the 404 handler,
                            #   route registration
    pages.py                # /, /city/<slug>, /cities, /release-notes, render_forecast_page
    api.py                  # /api/alert, /calendar.ics, and the plain-text failure response
    site.py                 # robots.txt, sitemap.xml, manifest.json, service-worker.js
tests/
  fixtures.py               # FORECAST_PAYLOAD, hourly_payload, FakeLocation, FakeResponse,
                            #   shared by the offline and the browser suite
  test_*.py                 # one file per module, plus test_routes_*.py for the HTTP classes
```

**The dependency rule:** `domain` imports neither Flask nor `requests`.
`present` imports `domain`. `upstream` imports `config` and `errors`. `web`
imports everything else, and nothing imports `web`. A test of the domain
needs no app, no client and no mock.

`templates/`, `static/` and `tools/` stay where they are. Flask finds the
templates and the static files relative to the app's root path, so
`create_app()` passes the repository root explicitly.

## 5. The steps

Every step: run `python -m unittest test_app` before and after, and run
`test_browser` after any step that touches routes or templates. Check that
the browser suite actually ran rather than skipped.

### Step 0 — Baseline

- [x] Run the offline and browser suites and record the counts.
- [x] Save the rendered HTML of `/`, `/city/london`, `/cities`,
      `/release-notes`, a 404, `/api/alert?city=London` and
      `/calendar.ics?city=London` with both upstreams mocked, from a small
      script in `tools/` (not in CI). Steps 5–10 are diffed against these
      byte for byte, with the `DTSTAMP` line masked.

### Step 1 — The package and the data

Risk: low.

- [x] Create `rainalert/__init__.py` and `rainalert/data/`.
- [x] Move `cities.py` and `releases.py` into `rainalert/data/` with
      `git mv`, so history follows them.
- [x] `app.py` imports from the new place and re-exports `RELEASES` and
      `CURATED_CITIES`.
- [x] Add `rainalert/` to the `COPY` in the `Dockerfile`, and check
      `.dockerignore` does not exclude it.
- [x] `docker compose up --build` still serves the page.

### Step 2 — Configuration and errors

Risk: **medium**. This is the step where a patch can silently stop applying.

- [x] `rainalert/config.py` takes every `os.getenv`, `load_dotenv()`,
      `clean_donation_url` and the constants derived from them.
- [x] `rainalert/errors.py` takes the three exceptions.
- [x] Every function that reads a setting reads it as `config.NAME` at call
      time, never `from config import NAME`, so a patch of the module is
      seen.
- [x] In the same commit, move every `mock.patch.object(rainalert,
      "DONATION_URL" | "APP_VERSION" | "APP_COMMIT" | "SEVERITY_*")` to
      `rainalert.config`.
- [x] Prove the patches still bite: temporarily break one patched value and
      watch its test fail. (Done: the donation link read as `""` failed six
      tests.)

### Step 3 — The calendar file

Risk: low. Done after step 4, because the calendar uses the rain rules and
the labels. The calendar tests now import `rainalert.calendar_ics` directly,
since `app.py` no longer needs the low-level helpers itself.

- [x] Move `calendar_escape`, `calendar_fold`, `calendar_day`,
      `calendar_next_day`, `calendar_slug`, `calendar_days`,
      `calendar_summary`, `calendar_description` and `build_calendar` into
      `rainalert/calendar_ics.py`.
- [x] `calendar_failure` stays with the routes; it is HTTP, not iCalendar.
- [x] **First**, add a test that pins the event id for "São Paulo" and for
      "Washington, D.C.", so no later step can change an id unnoticed.

### Step 4 — Labels and rain rules

Risk: low; pure functions, a mechanical move.

- [x] `rainalert/domain/rain.py`: `round_half_up`, `rain_chance`,
      `chance_number`, `severity_band`, `needs_umbrella`, `alert_threshold`.
- [x] `rainalert/present/labels.py`: `WEEKDAY_NAMES`,
      `WEEKDAY_SHORT_NAMES`, `format_date`, `format_date_parts`, the three
      rain-chance formatters, `format_precipitation`, `format_rain_hours`,
      `format_temperature`, `severity_label`, `hour_height_step`.
- [x] `app.py` imports all of them for its own use, so the tests reach
      them unchanged.

After steps 1–4, `app.py` is about 700 lines shorter and nothing has
changed shape.

### Step 5 — A domain model, and one parse per request

Risk: **medium**.

- [x] `rainalert/domain/model.py`: frozen dataclasses `Hour(moment,
      chance)` and `Day(iso_date, chance, high, low, amount, rain_hours,
      hours)`. The `past` and `now` flags are computed from `now`, not
      stored.
- [x] `rainalert/domain/parse.py`: `parse_forecast(payload) -> (days, now)`.
      It calls `local_now` once and groups the hours once.
      `parse_today_hours` becomes a lookup in the result, not a second
      parse.
- [x] `fetch_weather` keeps its signature and its return value: it parses,
      then builds the dicts. The template does not change.
- [x] `hour_moment()` is deleted; `notification_event` and
      `summarise_hours` take `Hour` objects. Their tests build `Hour`s
      instead of dicts.
- [x] A test holds the claim: one page load groups the hours once (it was
      twice before this step).

Done differently from the outline above: `Hour` stores `past` and `now`,
because the parser is the one place that knows the current time and both
the strip and the alerts need the same answer. `severity_label` moved to
`domain/rain.py`, because the band names are part of the scale and the
summary and the notification need them. `summarise_hours` and the
notification rule went into `domain/alerts.py` in this step rather than in
step 6. The view builders (`day_view`, `hour_view`) stay in `app.py` until
step 7.
- [x] Diff against the step 0 snapshots: identical.

### Step 6 — One rule for naming a day, one rule for today's alert

Risk: **medium**. The only step that touches logic.

- [x] `rainalert/domain/days.py`: one `day_name(iso_date, index, form)`,
      where `form` is `caption` ("on Friday"), `tab` ("Friday"), `panel`
      ("Friday", "Today") or `summary` ("for the rest of today"). The four
      old functions become one-line wrappers, and are then removed when
      their callers move.
- [x] `rainalert/domain/alerts.py`: `first_alert_day(days,
      remaining_hours, threshold)` holds the "today is judged on the hours
      that are left, a finished today drops out, an unreported day is never
      dry" rule. `forecast_headline` and `tab_alert` both call it.
- [x] `TestForecastHeadline` and `TestTabAlert` pass unchanged; add one test
      that feeds both functions the same week and asserts they name the
      same day.
- [x] Diff against the step 0 snapshots: identical.

Done as: `day_name(iso_date, index, form)` with the forms `panel`, `tab`,
`caption` and `summary`; the old four functions are gone rather than kept
as wrappers. The shared rule is `judge_days()` (today on the hours that are
left, a finished today drops out) plus `first_wet_day()`; both
`forecast_headline` and `tab_alert` take `Day`s and `Hour`s, and their
tests build those through two small helpers, so the test bodies are
unchanged. `WEEKDAY_NAMES` moved to `domain/days.py`.

One behaviour changed, on purpose: a later day whose date cannot be read
was captioned "on " (an empty weekday) in the hourly table and summary; it
is now "in 3 days", as the banner and the tab already said. A test holds
it.

### Step 7 — The client returns data, the view builds the page

Risk: medium.

- [x] `rainalert/upstream/open_meteo.py`: `fetch_payload(lat, lon, unit)`
      makes the request and returns JSON, raising `WeatherUnavailable`. It
      calls `requests.get` through the module, so the tests' patch of
      `rainalert.requests.get` still applies.
- [x] `rainalert/upstream/geocoding.py`: `geolocator` and `get_coordinates`,
      with the `lru_cache`. `app.py` re-exports the same `geolocator`
      object.
- [x] `rainalert/present/forecast_view.py`: `Day` → the template dict (the
      45-line dict now in `fetch_weather`).
- [x] `/api/alert` works on `Hour`s directly and no longer builds labels
      it does not use.
- [ ] `/calendar.ics` still uses the template's day dicts: the event text
      needs the long date and the band, which the dicts already carry.
      Moving `calendar_ics` onto `Day`s is left for later; it changes the
      signature its tests call.
- [x] Keep `fetch_weather` and `fetch_forecast` as thin compositions until
      step 11, because the tests call them.

Done with two additions. The upstream modules log to their own loggers
(`logging.getLogger(__name__)`), and `app.py` gives the `rainalert` logger
Flask's own handler, so the lines keep their format and now name the
module: `ERROR in geocoding: Unexpected geocoder error for 'London'`. The
tests patch `geocoding.geolocator` and `requests.get` directly instead of
reaching them through `app`.


### Step 8 — The page metadata

Risk: low.

- [x] `rainalert/present/seo.py` takes the slug functions, `page_title`,
      `page_description`, `canonical_url` and `structured_data`.
- [x] `page_meta(title, description, path)` returns the shared bundle: the
      canonical link, the Open Graph image and its size, the structured
      data. The four `render_template` calls spread it in.
- [x] `render_forecast_page` stays the only builder for the forecast page.

`DEFAULT_TAB_TITLE`, which nothing read, was removed. The favicon names
stay with the pages, in `web/pages.py`.

### Step 9 — One table for errors

Risk: low.

- [x] **First**, pin the current strings: the page messages and the
      shorter API messages ("…unavailable right now." without "Please try
      again") are different on purpose, and tests must hold both.
- [x] `errors.py` gets one table: exception → page message, page status on
      a city page, API message, API status, log line.
- [x] The three handlers use it. The start page still answers `200` for a
      failed search; a city page still answers `404` or `503`.

The table is `FAILURES` in `rainalert/errors.py`, with `MISSING_CITY` for a
request that names no city. The strings were pinned by adding the geocoder
being down to `tools/snapshot.py` (35 responses now) before the handlers
changed, and four tests hold the table's own rules.

### Step 10 — The routes and the app factory

Risk: medium.

- [x] `rainalert/web/__init__.py`: `create_app()` builds the app with the
      repository root as its root path, registers the context processor,
      the 404 handler and the routes.
- [x] `web/pages.py`, `web/api.py` and `web/site.py` each expose
      `register(app)`; the endpoint names stay exactly as they are.
- [x] `app.py` becomes `app = create_app()`, the `__main__` block and the
      re-exports.
- [x] `docker compose up --build` serves the page and `docker compose run
      --rm tests` passes; `gunicorn app:app` still starts.
- [x] Browser suite passes, actually run, not skipped.

`create_app()` names the app `rainalert`, so `app.logger` is the package's
own logger and the modules' loggers are its children. The helpers the route
modules share (`report_failure`, `fetch_weather`, `fetch_forecast`) are in
`web/common.py`. The re-exports were dropped here rather than in step 11:
the tests were pointed at the owning modules in the same commit.

### Step 11 — The tests

Risk: medium.

- [x] `tests/fixtures.py` holds `FORECAST_PAYLOAD`, `hourly_payload`,
      `FakeLocation` and `FakeResponse`; `test_browser.py` uses them too.
- [x] `test_app.py` is split into one file per module plus
      `test_routes_pages.py`, `test_routes_api.py`, `test_routes_site.py`
      and `test_docs.py` (the API-documentation and night-street design
      checks).
- [x] Each test imports from the module it tests; patches target the
      owning module.
- [x] Drop the re-exports from `app.py`; it keeps only `app`.
- [x] The count is still 359 offline and 80 browser tests (plus the new
      ones from steps 3, 6 and 9). Compare the test names before and after,
      not only the count.
- [x] Update the commands: `.github/workflows/ci-cd.yml`, the `Dockerfile`
      test `COPY`, `docker-compose.yml`'s `tests` service.

The offline suite is `tests/offline/`, twelve files: `test_rain`,
`test_labels`, `test_parse`, `test_alerts`, `test_calendar`, `test_errors`,
`test_upstream`, `test_config`, `test_pages`, `test_api_alert`, `test_site`,
`test_docs`. The 368 test names were compared before and after the split:
identical. The commands are:

    python -m unittest discover -s tests/offline -t .
    python -m unittest tests.test_browser
    python -m unittest tests.test_api

`.dockerignore` leaves `tests/test_browser.py` out of the image, and now
ignores bytecode caches at every depth: the old top-level pattern let
`__pycache__` folders inside packages into the image.

### Step 12 — The documents

Risk: low.

- [x] `CLAUDE.md`: the Layout table, the test commands, the gotchas that
      name `app.py` functions (the module they now live in), and a short
      section on the dependency rule.
- [x] `README.md`, `DEPLOY.md`, `implementation-plan.md`: the test
      commands and the test count, all four in one change.
- [x] `API.md` and `openapi.yaml` need no change, because no route,
      parameter or status code changes. `TestApiDocumentation` confirms it.

`RainAlert-Ideas-for-Alerting-Users.md` named `app.py` as the home of the
notification and the calendar too, and was updated with the others.

## 6. Later, and only if it earns it

- [ ] **`templates/_macros.html`** for `search_form` and `donate_line`,
      next to `_footer.html`. Small and safe.
- [ ] **`static/app.js` as ES modules** (storage, preferences,
      notifications, day picker, worker registration). It works without a
      bundler through `type="module"`, but every new file joins the service
      worker's shell list and needs a `CACHE_VERSION` bump. The sectioned
      IIFE reads well today; split it only if it keeps growing.
- [ ] **`static/style.css` stays one file.** `@import` costs requests and
      shell entries, and the sections are already clear.
- [ ] **Blueprints**, as a separate mechanical change that renames the
      endpoints and every `url_for` in the templates at once.

## 7. Order of work

Steps 1–4 go together: mechanical, low risk, about 700 lines out of
`app.py`. Steps 5–7 are where the real gain is — one parse per request, one
rule for naming a day, one rule for today's alert — and each goes in as its
own reviewed change, checked against the step 0 snapshots. Steps 8–12
follow in order.
