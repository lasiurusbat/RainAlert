# RainAlert

A small Flask web app that shows the 7-day rain chance for any city.

Enter a city name → geocoded to coordinates via **Nominatim** (OpenStreetMap) →
7-day forecast from **Open-Meteo** → rendered as a list of daily rain chances.

Both APIs are free, keyless, and need no signup. There is no database and no
user account system.

**The app is deployed and live at <https://rainalert.live/>.** It runs
from the `1.2.1` image on Docker Hub, on a Render service, and the domain
is attached to it: `http://` redirects to `https://`, and every route
answers. Release tags have been cut from `v1.0` on 2026-10-22 up to `v1.2.1` on 2026-10-30 — the images they built were pushed, and the
workflow's deploy hook has deployed them. It
also runs locally, from `python app.py` or `docker compose up`. `DEPLOY.md`
is the runbook, and the "Still to do" section below is the list of what is
actually ahead.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Serves on <http://127.0.0.1:5000>. `FLASK_DEBUG=1` enables the reloader and
debugger.

```bash
python -m unittest discover -s tests/offline -t .  # offline suite, 595 tests, no network
python -m unittest tests.test_browser               # browser suite, 128 tests, needs Chrome
python -m unittest tests.test_api                   # live integration tests, hits both APIs
```

The offline suite is the one that gates changes. `tests/test_api.py`
requires the upstream services to be reachable. `tests/test_browser.py`
needs Chrome and
selenium (`pip install -r requirements-dev.txt`) and skips itself when
either is missing.

## Running it in Docker

```bash
docker compose up --build       # http://localhost:8000
docker compose run --rm tests   # the two HTTP suites in the same image
```

`Dockerfile` is a two-stage build; the runtime image has no compiler, runs as
the non-root user `rainalert` (uid 1001), and serves with gunicorn on port
8000. The image installs no system packages: the weekday names are hard-coded
in the app, so there is no locale data to compile. It carries a health check
(the home page, which asks no upstream, so the check never depends on a third
party) and OCI labels with the version and the commit, so the image itself
says which build it is. `DEPLOY.md` is the deployment runbook, and
`.github/workflows/ci-cd.yml` runs the tests inside the built image before
any release is pushed.

**Compose builds the image from the source every time** (`pull_policy:
build` on the shared `x-image` block). Without it, Compose reuses the local
`rainalert:latest` whenever it exists and never rebuilds it, so
`docker compose run --rm tests` can quietly test an old image and report the
result of old code — it happened here, when a stale image ran 368 of the 520
offline tests and still said `OK`.

**The settings come from `.env`.** Copy `.env.example` to `.env` and edit
that; it holds the site's address, the donation link and the app's tunables.
Compose fills them into the app container. The test container deliberately
gets none of them, because the offline suite asserts the app's own defaults.

## Deployment status

**The app is live at <https://rainalert.live/>.** Checked on 2026-10-23:

- **The domain is attached to the service and answers.** `rainalert.live`
  is a CNAME to `rainalert-1-0.onrender.com` and on to
  `gcp-us-west1-1.origin.onrender.com`, resolving to `216.24.57.16` and
  `216.24.57.18`. `http://` answers `301` to `https://`; `https://` answers
  `200` with the real page, and a city's page with a live forecast from
  both upstreams. The footer reads "Version 1.2.1" and the commit the `v1.2.1` tag
  points at, so the build that is answering is
  the build that was released.
- **Every route answers on the live domain**: the start page, `/cities`,
  `/release-notes`, `/robots.txt`, `/sitemap.xml`, `/manifest.json`,
  `/service-worker.js`, `/api/alert`, `/calendar.ics`, a city's page, and
  a `404` for an address that is not on the site. Each page's canonical
  link is its own address under `https://rainalert.live/`, which is what
  `SITE_URL` says.
- **The image is on Docker Hub.** `lasiurusbat/rainalert` has a tag per release, from
  `1.0` (2026-10-22) to `1.2.1` (2026-10-30). The last one is what the live
  service is running; `1.1.2` added the Google and Bing ownership files and
  `1.1.1` the security headers. `1.2.2` (the footer) is prepared, not tagged.
- **The donation link is on the live page.** The service runs with
  `DONATION_URL` set, so "Buy me a coffee" appears under the search and
  in the footer of every page. The variable is read at start-up, so
  changing it needs a restart of the service and no new image.
- **The service is named `rainalert`, and its address is still
  `rainalert-1-0.onrender.com`.** It was created as `rainalert-1-0`
  because an older stub service held the name; the stub has been deleted
  and the service renamed. Render fixes the subdomain at creation, so the
  rename did not change the address and the domain's CNAME is untouched.

**The first release ran, and it took five attempts.** `v1.0` points at
`7265a18` on `main`, and the tag-gated half of the workflow has now run
green, so the machinery is not untested:

- **Attempt 1 failed at the Docker Hub login.** The `DOCKERHUB_USERNAME`
  and `DOCKERHUB_TOKEN` secrets were not set, so the login step had
  nothing to log in with.
- **Attempt 2 failed at the push**, with `unauthorized: access token has
  insufficient scopes`. The token existed but had the **Read** scope; a
  push needs **Read & Write**. The token was replaced on 2026-10-22.
- **Attempt 3 failed in the browser suite**, on
  `test_the_export_downloads_with_the_worker_in_charge`. It was a flake in
  the test's own wait, not a fault in the app: the worker installed and
  activated, and the page was not taken over by it, so the wait for
  `navigator.serviceWorker.controller` ran out. The wait now waits for
  the registration to be *active* and loads the page once more when it is
  not controlled yet, which is what the test actually means. A tag run is
  pinned to the commit the tag points at, so the fix had to be pushed
  into the tag itself — the tag was moved, and the run re-fired.
- **Attempt 4 got the image pushed, and failed at the deploy.** The build,
  the offline suite inside the image, the browser suite on the runner, the
  Docker Hub login and the push were all green. The deploy job then
  failed on `curl: (3) URL rejected: Bad hostname`, because the
  `RENDER_DEPLOY_HOOK_URL` secret is not set: the hook URL was empty. The
  service was deployed by hand instead.
- **Attempt 5 is green, end to end.** The hook secret was set — from the
  service that runs the image, since a hook is per-service — and the
  deploy job was re-run. It called the hook with the image URL, Render
  pulled and started the image, and the smoke test found "Version 1.0" on
  the live domain. The deploy job's smoke test greps the live page for
  `Version <tag>`, so it proves the new build is the one answering and not
  an old one.

**The second release ran green on the first attempt.** `v1.0.1` points at
`e045be4` on `main` and was cut on 2026-10-23. Every step was green the
first time: the build, the offline suite inside the image, the browser
suite on the runner, the Docker Hub login, the push, the deploy hook and
the smoke test, which found "Version 1.0.1" on the live domain. The five
attempts above were the cost of finding out which secrets were missing,
not a property of the pipeline.

**Changing the image in Render does not deploy anything.** An image-backed
service is never redeployed automatically, because auto-deploy only
applies to Git-connected services. Saving a new image URL in the service's
settings changes what the *next* deploy will pull and nothing else. The
deploy is a separate action: **Deploys → Manual Deploy → Deploy latest
reference**, or the deploy hook. The hook is what the workflow calls, and
it is what makes a release a release.

### Still to do

- **Verify the site with the search engines.** `v1.1.2` serves the Google and
  Bing ownership files (`/googlee75783b48c054b73.html` and `/BingSiteAuth.xml`).
  Click Verify in Google Search Console (a URL-prefix property for
  `https://rainalert.live/`) and in Bing Webmaster Tools, then submit
  `https://rainalert.live/sitemap.xml` in both.

## Layout

| Path | Purpose |
|---|---|
| `app.py` | The entry point for `python app.py` and `gunicorn app:app`; it only calls `create_app()` |
| `requirements.txt` | The runtime dependencies, installed by the Dockerfile and by `pip install -r` |
| `rainalert/config.py` | Every setting read from the environment |
| `rainalert/errors.py` | The three failures, and `FAILURES`: what each one says and which status it answers |
| `rainalert/domain/rain.py` | The bands, the umbrella and the alert threshold |
| `rainalert/domain/days.py` | The one rule that names a day ("today", "Tomorrow", "on Friday") |
| `rainalert/domain/model.py` | `Day`, `Hour` and `Forecast`: the forecast before any of it is worded |
| `rainalert/domain/parse.py` | The Open-Meteo answer, parsed once per request |
| `rainalert/domain/alerts.py` | The banner, the tab title, the hourly summary and the notification |
| `rainalert/present/labels.py` | Every visible label: dates, chances, amounts, temperatures |
| `rainalert/present/forecast_view.py` | `Day`s and `Hour`s turned into the dicts the template renders |
| `rainalert/present/seo.py` | Slugs, the title, the description, the canonical link, the structured data |
| `rainalert/upstream/geocoding.py` | Nominatim: a city name to coordinates, cached |
| `rainalert/upstream/open_meteo.py` | Open-Meteo: the one forecast request per page load, kept for `WEATHER_CACHE_SECONDS` |
| `rainalert/upstream/openweather.py` | OpenWeather One Call 4.0: the second source (two calls: the days and the hours), used only when Open-Meteo refuses; translated into Open-Meteo's shape |
| `rainalert/calendar_ics.py` | The iCalendar file, built with no HTTP in it |
| `rainalert/web/__init__.py` | `create_app()`: the Flask app, its template globals and its routes |
| `rainalert/web/pages.py` | `/`, `/city/<slug>`, `/cities`, `/release-notes` and `render_forecast_page()` |
| `rainalert/web/api.py` | `/api/alert` and `/calendar.ics` |
| `rainalert/web/site.py` | `robots.txt`, `sitemap.xml`, the search engines' ownership files, the manifest, the service worker, the 404 |
| `rainalert/web/security.py` | The security headers on every response: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy |
| `rainalert/web/common.py` | What the route modules share: reporting a failure. The forecast as views is a helper here, but only the tests call it |
| `rainalert/data/cities.py` | The curated list of cities that have a page of their own |
| `rainalert/data/releases.py` | What each release brought, for the release notes page |
| `templates/index.html` | Single page; inline styles are out, classes live in `style.css` |
| `templates/cities.html` | The index of the cities, with a link to each |
| `templates/release_notes.html` | What each release brought |
| `templates/_footer.html` | The shared footer, a Jinja macro the pages call |
| `templates/404.html` | The page for an address that is not on this site |
| `static/style.css` | All styling |
| `static/fonts/` | The self-hosted Archivo variable face: the Latin subset and the Latin Extended subset, for the accented letters of a city nobody looked up in advance |
| `static/app.js` | The browser half: saved city, personal alert threshold, notifications |
| `static/googlee75783b48c054b73.html`, `static/BingSiteAuth.xml` | Google's and Bing's site-ownership files, each served from the root by its own route; they must stay |
| `static/manifest.json` | The web app manifest: the app's name, icons and install metadata |
| `static/service-worker.js` | The service worker: caches the shell, never the forecast |
| `static/offline.html` | The page shown when the server cannot be reached |
| `static/og-image.png` | The social card: 1200x630, the picture a shared link shows |
| `static/icon-*.png` | The install icons: 180, 192, 512 and a maskable 512 |
| `static/favicon.svg` | Tab icon |
| `static/favicon-rain.svg` | Tab icon when rain is coming |
| `static/image/` | Background photo |
| `tools/make_icons.py` | Regenerates the install icons from the brand mark (not run by CI) |
| `tools/make_og_image.py` | Regenerates the social card (not run by CI) |
| `tools/shoot.py` | Screenshots a page of the running app, for looking at the design |
| `tools/measure.py` | Measures the page in a real browser: the vertical budget and the boxes |
| `tools/crop.py` | Screenshots one element, for looking at a detail |
| `tools/snapshot.py` | Saves what every route answers, both upstreams mocked, for `diff -r` before and after a refactor |
| `tests/offline/` | The offline suite, one file per module, HTTP fully mocked |
| `tests/fixtures.py` | The mocked upstream answers and `AppTestCase`, shared by the suites |
| `tests/test_browser.py` | Browser tests, real headless Chrome, no network |
| `tests/test_api.py` | Live integration tests |
| `refactor-plan.md` | How `app.py` was split into the package, step by step |
| `requirements-dev.txt` | Development-only dependencies (selenium) |
| `Dockerfile` | Two-stage container image |
| `docker-compose.yml` | Local container setup: the app and a test service |
| `.env.example` | The local settings `docker compose` fills into the container |
| `render.yaml` | Render Blueprint; runs a prebuilt image, not a build (the service that is live) |
| `API.md` | The HTTP API reference: every route, the parameters, the status codes, the upstream services |
| `openapi.yaml` | The same API as an OpenAPI 3.1 spec, for tools that read one |
| `README.md` | The front door: what the app is, how to run it, and the rest of the documents |
| `DEPLOY.md` | Deployment runbook: Render setup, domain, CI/CD, releases |
| `tech-stack.md` | What the app is built with, what each piece does, and why it is that piece |
| `implementation-plan.md` | What is built, what is next, and the go-live checklist |
| `RainAlert-Ideas-for-Alerting-Users.md` | The alerting tiers as proposed, each annotated with what was built |
| `design/` | The design mockups: what the page could look like. Not part of the app |
| `docs/` | The committed screenshot the README shows |
| `.github/workflows/ci-cd.yml` | CI on every PR and push; release on a git tag |
| `.github/dependabot.yml` | Weekly grouped PRs for actions, pip and the base image |

## Architecture notes

**The code is in layers, and the layers only point down.** `rainalert/web`
is Flask: the routes, the app factory, the template globals. It uses
everything below it, and nothing imports it. `rainalert/present` turns the
forecast into words and page data. `rainalert/domain` holds the rules - the
bands, the naming of a day, the alerts - and imports neither Flask nor
`requests`, so a rule can be tested without an app or a mock.
`rainalert/upstream` holds the two clients. A new rule goes in `domain`, a
new label in `present`, a new route in `web`; `app.py` stays the entry
point and nothing else.

- **Settings are read as `config.NAME`, at the moment they are needed**,
  never copied out with `from rainalert.config import NAME`. A test patches
  `rainalert.config`, and a copied name would never see the patch.
- **The package logs under the `rainalert` logger.** `app.logger` is that
  logger, and the modules below log to its children
  (`logging.getLogger(__name__)`), so every line goes through Flask's
  handler and names the module it came from: `WARNING in common:
  Geocoding service unavailable for 'London'`.

**Error handling is exception-based.** `rainalert/errors.py` defines three
exceptions that the routes translate into user-facing messages:

- `CityNotFound` — the geocoder answered normally but had no match.
- `GeocodingUnavailable` — the geocoder was unreachable, rate-limited, or
  errored.
- `WeatherUnavailable` — the forecast service was unreachable or returned junk.

**The distinction between the first two matters.** Do not collapse them into a
single "not found" path: a network blip must not tell a user their valid city
does not exist. Internal exception text is logged, never rendered.

**Every failure is described once.** `FAILURES` in `rainalert/errors.py`
gives each exception its page message, its shorter API message, its status
code and its log line, and the page, `/api/alert` and `/calendar.ics` all
read it. A page can offer to "try again in a moment"; the API cannot, so it
gets the shorter sentence.

**Geocoding results are cached** with `lru_cache` on `get_coordinates`
(`rainalert/upstream/geocoding.py`), keyed
by city name. Nominatim is rate-limited and a city name always maps to the same
place, so caching cuts load substantially. Failures are deliberately not
cached, so a retry re-attempts the lookup. Clear the cache in tests with
`geocoding.get_coordinates.cache_clear()`; `AppTestCase` does it for you.

**Timeouts are explicit and configurable.** geopy defaults to a **1 second**
read timeout, which is short enough to fail against a healthy-but-slow
Nominatim. `GEOCODER_TIMEOUT` and `WEATHER_TIMEOUT` (both default 10s) are
read from the environment. `requests.get` has no default timeout, so always
pass one.

**The server keeps a forecast for ten minutes.** Open-Meteo's free tier limits
requests per IP address and answers `HTTP 429` beyond it; on Render the egress
IP is shared with other apps, and on 2026-10-29 every forecast on the live site
failed that way. `fetch_payload()` in `rainalert/upstream/open_meteo.py` keeps
a good answer for `WEATHER_CACHE_SECONDS` (default 600, `0` turns it off), keyed
by coordinates and scale, so a crawler or a second visitor costs no upstream
call. This is the server's own copy only: the browser and the service worker
still never keep a forecast, and a failure or a broken answer is never stored,
so a retry asks again. `tests/__init__.py` sets the variable to `0` for the
suites, because they fake different forecasts for the same coordinates; the
cache's own tests turn it on. `robots.txt` also sets `Crawl-delay: 10` and shuts
out SemrushBot, since every crawled city page is an upstream call.

**A second source answers when Open-Meteo refuses.** The 429s of 2026-10-29 were
`Daily API request limit exceeded` for Render's shared IP: an allowance the app
cannot raise or protect, and a cache cannot help once the whole day is spent. So
`fetch_payload()` catches the `WeatherUnavailable` from Open-Meteo and, when
`OPENWEATHER_API_KEY` is set, asks `rainalert/upstream/openweather.py` instead.
That module **translates OpenWeather's answer into Open-Meteo's shape**, so the
validator, `parse_forecast()` and everything above never learn which service a
forecast came from; keep it that way, and never mix the two within one page
(the probabilities come from different models).

- **It never raises.** `fallback()` returns `None` for every reason there can be
  no second source (no key, the allowance spent, a refusal, a broken answer), and
  `fetch_payload()` then re-raises Open-Meteo's own failure, so the log and the
  503 are about the first source.
- **A forecast is two calls**, because One Call 4.0 has an endpoint per timeline:
  `/timeline/1day` (the week) and `/timeline/1h` (at most 20 hours from now). The
  hours are an addition: if only they fail, the week still makes a page. The
  current hour is not asked for; it is the clock plus the `timezone_offset` every
  answer carries. Written from the docs page alone, then run against the real
  API on 2026-10-30 (both calls, London): the days and the hours parse as expected.
  The daily `rain` came as a plain number, not the docs' `{"1h": mm/h}` rate, and the
  daily `snow` has not been seen; `/timeline/1day` hung for a while that morning and
  then recovered.
- **The calls are counted** and stop at `OPENWEATHER_DAILY_LIMIT` (default 900, per
  UTC day, in memory; the image runs one gunicorn worker). A forecast that does not
  fit in what is left is not half made. OpenWeather bills calls
  past its free thousand a day, so set the same cap in the OpenWeather account too.
- **The key is in the query string, so nothing logs a URL or an exception's text** -
  only the status, or the exception's class. A test holds this.
- **What it cannot give is left unknown, not invented**: the hours of rain in a day
  (`None`), a day's millimetres when the answer says nothing (`None`, not 0), the
  hours of the day that are not reported (`None`, so the strip keeps its 24
  columns), and the hourly strip for the days past the hours the call returned
  ("Hourly detail is not available for this day.").
- **The footer credits OpenWeather only while a key is set** (`openweather_enabled`
  in `inject_site_info()`), so it never credits a source the site is not using. The
  Open-Meteo and OpenStreetMap credits stay required.
- **The answer is kept like any other** for `WEATHER_CACHE_SECONDS`, which is what
  protects the small allowance.

**`timezone=auto` is deliberate.** Open-Meteo returns each date in the
queried city's local time. A forecast for Tokyo is dated in Tokyo's days.
Do not convert these dates to the viewer's timezone — that would be a bug.

**Weekday names are always English.** They are hard-coded in `WEEKDAY_NAMES`
in `rainalert/domain/days.py` (Monday first) and picked by `date.weekday()`, not taken from
`strftime("%A")` and not read from the C library's locale data. `strftime`
follows the process-wide `LC_TIME` locale, so on a German Windows machine, or
in a container with `LANG` set, it would render the weekday in that
language. The rest of the page is English, so a half-translated date inside
it would be worse than a consistently English one. The app therefore does
not read the browser's `Accept-Language` header at all, and the image needs
no locale data.

**Rain severity is a three-band scale** computed in `rainalert/domain/rain.py` from
`precipitation_probability_max`: under `SEVERITY_LOW_MAX` (30) is *low*,
up to `SEVERITY_MODERATE_MAX` (60) is *moderate*, above that is *high*. A
missing chance gets its own *unknown* band rather than being treated as
zero. The thresholds and `UMBRELLA_THRESHOLD` are environment variables.

The bands are named **Rain unlikely / Rain possible / Rain likely**, not
"Dry / Light rain / Heavy rain". A 25%-chance day is not dry, and a
probability does not predict an intensity — the scale has to stay honest
about what a percentage can tell you.

**The page is a night street.** The panel is a dark plate laid over the
photograph — the same night the picture shows, lit by the same sodium lamps
— and the colours are taken from the image: asphalt, haze, mist, paper and
the amber of a street lamp. **Amber is the only accent**, so a colour on the
page always means something about the rain and never just decoration. The
type is **Archivo, self-hosted** (`static/fonts/archivo-latin.woff2` and
`static/fonts/archivo-latin-ext.woff2`, the Latin and the Latin Extended
subsets of a variable face, the second one for the accented letters of a
city nobody looked up in advance — Gdańsk, Malmö, Zürich), so the page
asks no third party for anything and still works with no network. The
width axis does the work: the city name is set wide, the labels narrow,
the figures wide again in tabular numerals.

**The answer is at the top of the page.** The city is the `h1`, the sentence
about the week is the banner under it, and the strip and the week follow.
The search is a compact field in the top bar on a page that already has a
forecast, and a full-width field under the name on the start page — one
form, two sizes, and never both on the same page. The `h1` is the city
name on a city's page, so the strip's title is the `h2` and the headings
stay in order. Under the name is a **caption line** — "7-day rain chance"
on the left, the calendar export on the right, on one baseline — so the two
read as one line rather than as a label and a button.

**The hourly strip sits between the banner and the week.** It
comes from `hourly=precipitation_probability` in the same request as the
daily fields — one request per page load, not two. `parse_forecast()`
(`rainalert/domain/parse.py`) reads the response **once**: it groups the
hours by the day they fall on, gives each `Day` its hours, and picks out
the city's local day as `Forecast.today`. `summarise_hours()` turns a day's
hours into the one-line "Bring an umbrella" sentence.

**A day is named by one rule.** `day_name(iso_date, index, form)` in
`rainalert/domain/days.py` names the first day today and the second
tomorrow, and every later one by its weekday, in the form each place
needs: `panel` ("Today", "Friday"), `tab` ("today", "Friday"), `caption`
("today", "on Friday") and `summary` ("for the rest of today", "on
Friday"). A later day whose date cannot be read is "in 3 days", never "on ".

The strip's hours are the **city's local hours**, exactly like the daily
dates. The current hour comes from the `current` block the API returns, in
that same local time; `utc_offset_seconds` is only a fallback for a
response without it, and without that there is no now-marker at all.
"Today" follows the current time when it is known, because that is the day
the now-marker belongs to — the first daily entry is only the fallback.

The bar height is **bucketed into 5% steps** so it can live in the
stylesheet as a class rather than an inline style. The exact percentage is
in the tooltip and in the table view, so the rounding never hides a value.
A **known 0% still gets a 2px stub** — a hole in the strip reads as
missing data rather than as "no rain".

**Every hour's number is written over its own bar.** The strip is a row of
equal columns, and the row of values above it is the same row of cells, so
a value never needs a hover to be read — and a touch screen never shows
one. The value row carries the **bare number**, without the percent sign:
twenty-four columns of three digits do not fit across the panel with it,
and the sentence above, the tooltip and the table below all say what the
numbers are. The sign is left off in the row and nowhere else.

**The current hour is a rule, and it is labelled.** A 1px line in paper
white runs through the strip at the current hour, and the words "now 11:00"
are written in the gap above it, over the rule they point at. It is a rule
rather than a mark in a data colour, so the data mark itself is not
altered, and it is labelled rather than left to be inferred from the axis.
The label lives in the **value row**, not in the axis: the axis is for
the hours, and a label that sat in the axis collided with the hour marks
below it.

**The headline banner is one sentence under the city's name.**
`forecast_headline()` picks the first day worth mentioning: a day at or
above `UMBRELLA_THRESHOLD`, a day that is only *possible*, or the week as a
whole. The band name in the sentence is the day's own band — the same one
its column in the week carries — so the banner and the week never
disagree. The colour follows the band and the band name is in the text, so
the meaning never rests on colour alone.

**Today is judged on the hours that are left, not on the daily maximum.**
The daily maximum covers the whole day, so at 18:00 it still counts the
morning's downpour while the reader can only walk into the evening. When
the hourly data is available, the banner's figure for today comes from the
remaining hours and says so — "Rain likely for the rest of today (80%)" —
while the row in the list keeps the daily maximum. The two are different
quantities and each is labelled with which one it is. When the day is over
it drops out of the banner entirely. A missing chance is never counted as
dry: a quiet week with one unreported day is "most of", not "all of".

**The week can be picked, and the day panel answers.** Each of the seven
columns is a button, and picking one puts that day's rain in the panel above
the week: the day itself, the band it is in, the chance, how much rain falls
in it and how long it lasts. The panel is **rendered by the server for every
day**, and the script only decides which of the seven panels is showing — so
the page says something useful without any script at all, which is today's
panel, because the week starts on today. All seven panels sit in **one cell of
one grid**, so the strip keeps its height when the day changes and the week
never moves.

- **The button is built by the script**, not by the markup, so a reader
  without JavaScript is never handed a button that cannot work. The columns
  stay a list of figures, and the panel shows today.
- **The panel carries the same chance the column shows**, and the same
  threshold for the umbrella, so the panel, the column, the banner and the
  tab title can never disagree about how wet the day is.
- **The millimetres and the hours are only shown when there is rain in
  them.** A day the model expects no rain in says nothing more than that:
  "0 mm" beside a chance of rain would read as a contradiction, because the
  two come from different parts of the model.
- **A day the service did not report is named as such** — "Rain not
  reported" — and carries no figures at all. An unreported day is never
  counted as a dry one.
- **The picked day is marked with a rule in the paper's own colour**, not
  the band's: the band colour already means the rain, and the selection is a
  different thing.

**The graph follows the picked day too.** The strip is drawn for the day the
reader picked, so the graph and the panel are always about the same day.
There is **one strip per day**, rendered by the server for all seven of
them, and the script only decides which one is showing — the same split as
the panels, and for the same reason: the page says something useful without
any script, and the rule that decides what a bar means stays behind the
offline test suite.

- **The title of the strip names the day it draws** — "Today, hour by
  hour", "Friday, hour by hour" — and the script writes the day's own title
  into it, so the heading is never about another day than the bars.
- **The summary of a day names that day.** A dry day says "No rain likely
  tomorrow", not "No rain likely for the rest of today": only the day that
  is running has hours left to come.
- **The strips sit in one cell of one grid**, like the panels, so the graph
  does not move and the week below it never moves either. Two lines are
  reserved for the summary, so a day whose sentence is shorter than another
  day's does not push the graph down.
- **The banner and the tab title do not follow the picked day.** Picking a
  day is browsing; the banner is the app's own alert and names the first
  day worth mentioning, which is the same sentence whatever the reader is
  looking at.

**The tab title and the favicon are the alert.** `tab_alert()` decides whether
the browser tab should say anything, and the route passes `page_title` and
`favicon` to the template. It fires at the **same `UMBRELLA_THRESHOLD`** as
the ☔ icon and the banner's "Bring an umbrella", so the tab, the banner and
the row can never disagree about whether rain is worth noticing. The title
names the day — "Rain tomorrow - Rain Alert" — rather than the date, because
a tab title is read at a glance and "tomorrow" is the thing a reader is
asking about. The app name is kept as a suffix, in the usual
"page - site" order, so that a reader with a row of tabs open can still
tell which one is Rain Alert.

Today is judged on the hours that are left here too, exactly as the banner
judges it, so the title does not still say "Rain today" at 18:00 when the
morning's downpour has been and gone. A day that is over drops out and the
next wet day is named instead. A missing chance is never counted as dry: an
unreported week simply has no alert, and neither does a dry week.

The two favicons are **separate files** (`favicon.svg` and `favicon-rain.svg`),
not one file that is recoloured, because browsers cache a favicon by its URL
and a single file would keep showing the old icon until the cache was
cleared. The rain icon changes **shape** as well as colour — the same
umbrella mark, but on the sodium-lamp amber plate with two strokes of rain
falling from it, against the dark plate with the mark in paper white — so
the two are told apart at 16 pixels by the shape and not by the hue alone.

**Every city has one address, and it is `/city/<slug>`.** A forecast is
reachable by half a dozen routes — the search form, a query string, a
bookmark, a link somebody sent — and a search engine would index each of
them as a separate page. So `city_path()` decides the one address, the page
carries a canonical link to it, and everything else is sent there.

- **The address comes from the name the city was asked for**, never from the
  geocoder's `display_name`. The geocoder answers with a full address
  ("London, Greater London, England, United Kingdom"), and an address built
  from it would be `/city/paris-france` for `/city/paris`. The reader asked
  for a city, so the city is what the address carries.
- **A curated city keeps the slug the list gives it.** `rainalert/data/cities.py` is the
  list of the 92 cities that have a page; `CITY_NAMES` and `CITY_SLUGS` map
  between the names and the slugs, so the address in the city index, the
  address in the sitemap and the address the page claims for itself are the
  same one. Only "Washington, D.C." does not slug to its own name, and the
  map handles it.
- **`GET /?city=X` answers `301`.** The redirect is worked out before the
  forecast is fetched, so the extra hop asks the server for no more than a
  header. A `POST` renders the page where it is and points its canonical
  link at the address, so there is still one page per city. The unit travels
  with the redirect as `?unit=`, because the reader's chosen scale is part
  of the request.
- **A slug that is not the canonical one is also a `301`.** `/city/London`
  and `/city/london` are one page, not two.
- **`city_from_slug()` capitalises only the first letter** of a fallback
  name. A name is not a sentence, and capitalising every word would turn
  "St John's" into "St John'S" — the same rule that keeps `.title()` away
  from user input.

**A missing page answers `404`, and a broken upstream answers `503`.** A
page that says "not found" but answers `200` is a soft 404, and search
engines treat it as one. On a city's page a `CityNotFound` is a `404` and a
`GeocodingUnavailable` or `WeatherUnavailable` is a `503`; on the start
page both stay `200`, because a failed *search* is not a missing *page*.
`templates/404.html` is the real 404 page, with a search form on it, and
it says `noindex, follow`.

**A missing page says so in its head as well.** A city the geocoder does
not know has no page, and the page that answers `404` used to carry the
title and the description of a working one — "7-day rain chance for
Nowhereville" — which is a promise the site cannot keep, in the tab a
reader sees and in the social card a shared link carries. A missing page
now takes the same words as the site's own 404 page ("Page not found -
Rain Alert") and the site's own description, and it **claims no address of
its own**: its canonical link points at the site, like the other 404s. A
page that is only *broken* is not missing — a `503` keeps the city's own
title and address, because the city is there and the page will come back.
`NOT_FOUND_TITLE` and `NOT_FOUND_DESCRIPTION` in `rainalert/present/seo.py`
are the one place those words are written down.

**A broken answer is a `503`, and a missing feature is not.** The forecast
service is a third party, so its answer is checked before it is used.
`_is_a_forecast()` in `rainalert/upstream/open_meteo.py` decides whether
the answer is shaped like a forecast at all: a list, a string, an error page
served as JSON, or a `daily` block that is not an object, or a `daily` field
that is there but is not a list, is a **broken answer** and becomes a
`WeatherUnavailable` — the reader is told to come back in a moment, rather
than shown an empty week. A `daily` block that is simply **absent** is not
broken: the service answered and had no forecast to give, so the page says
so and stays up.

The **hourly block is not checked** by the validator. The hours are an
addition to the forecast, so a missing or unreadable strip is a missing
feature, not a broken forecast: the week survives it, the strip goes away,
and a warning is logged.

**An address of nothing in it is a `404`, not a redirect.** A slug made
only of punctuation (`/city/---`) stands for no city: there is no name
behind it, and a city with no address of its own has no page either. The
address has to exist before the page does, so `city_from_slug()` returns
`""` for such a slug and `city_page()` answers `404` rather than redirecting
to an empty address.

**The title, the description, the canonical link, the Open Graph tags and
the JSON-LD are decided in one place.** `render_forecast_page()` renders
every page of the site — the start page, a city's page, an error page — and
passes the whole set to the template, so the title a reader sees in the tab
and the title a search engine shows in its results cannot drift apart. The
title is still the alert: on a city's page it reads "Rain tomorrow in
London - Rain Alert", which is the same `UMBRELLA_THRESHOLD` as the ☔ icon
and the banner. `page_title()` is the only builder of a title.

The other pages - the city index, the release notes and the 404 - write
their own title and description, but every page, the forecast included,
hands its head to the template through `page_meta()` in
`rainalert/present/seo.py`. That is what puts the same social card, the same
structured data and an absolute canonical link on every page, so no page
can forget one of them.

**`SITE_URL` is the site's own address.** It is read from the environment
(with `https://rainalert.live` as the default) and used for the canonical
link, the Open Graph image, the sitemap and the structured data. It is
absolute, and it is the address the site is actually served from — a
canonical link pointing somewhere else is worse than none.

**The endpoints that are not pages say so in their headers.** `/api/alert`
and `/calendar.ics` carry `X-Robots-Tag: noindex, nofollow` and are
disallowed in `robots.txt`: they are an endpoint the page uses and a file
the page hands over, and crawling them costs two upstream requests each.

**The city index is the front door of the crawlable part of the site.**
`/cities` links to every curated city, and `/sitemap.xml` lists the start
page, the index, the release notes and every city. The list is short on
purpose — the geocoder is rate-limited, and every address in it is a
forecast the app has to fetch.

**The changelog is a page of the site, not a file in the repository.**
`/release-notes` says what each release brought, newest first, and the
footer of every page links to it after the version. The content lives in
`rainalert/data/releases.py`, so **cutting a release means adding an entry there** — the
version on the top entry should be the one the build stamps into the footer
(the footer reads `APP_VERSION`, not the release notes, so the two are kept in
step by hand), and the number of the release in preparation is the fallback
tag in `render.yaml`.

- **A release is a version, a date, a name and a list of features.** A
  feature is a `title` and a `text`: the title is the `h3` and the text is
  the paragraph under it, so the page reads as a set of things the app does
  rather than as a wall of prose. The version is the `h2` and the
  release's name is the line under it.
- **The date is `dd.mm.yyyy`, on the version's line.** An entry holds an ISO
  `date` ("2026-10-23"); `format_numeric_date()` in `rainalert/present/labels.py`
  writes it as `23.10.2026`, with no weekday and no locale, and the page
  renders it in a `<time class="release-date" datetime="...">` inside the
  `h2`, so a release costs no extra line. The date is the day the tag was
  pushed, **in UTC**: `v1.0.1` was tagged at 01:07 local on 2026-10-23, which
  is 2026-10-22 in UTC, and the notes say 22.10.2026. The forecast's own
  dates keep their format (`format_date()`, "Thursday 22.10.2026"); only the
  release notes use the numeric one.
- **The page is the same night street as the rest of the site.** Same
  background photograph, same panel over it, same frame. It is a page of
  the site, so it looks like one.
- **There is no amber on it.** The lamp means rain on the forecast page,
  and a colour that means one thing on one page must not mean nothing on
  the next. The release notes are set in paper and mist only.
- **The footer is three tiers on its own plate.** The notice with the
  donation link, the credits and the build line are centred on a measure of
  about 40em, on a translucent dark plate (`backdrop-filter` blur, hairline
  edge) that keeps the white type readable over the photograph; it replaced
  a radial shadow (`.copyright::before`) that looked bad, so do not put one
  back. "Buy me a coffee" (`.coffee-link`) is a filled paper chip - paper,
  never amber, because the lamp means rain. Each credit is a `.credit` that
  wraps whole, and the OpenWeather clause after the comma is
  `.credit-fallback`, always on its own row, so no word is left alone. Below
  560px each credit takes a line and the build line's links are about 44px
  touch targets. Keep `href` first in the donation anchor: a test finds it
  by that prefix.
- **The footer is one macro.** `templates/_footer.html` holds the footer,
  and every page calls `{{ site_footer() }}` — so the version, the credits
  and the release-notes link cannot drift apart between pages. The release
  notes page itself calls `site_footer(release_notes=False)`, so it does
  not link to itself.

**The headings are in order.** The forecast page is `h1` (the city's name)
→ `h2` (the hourly strip's title), and the day list is a real `<ol>` of
`<li>`s, so the page says what it is to a reader who never sees the
picture. The list is laid out as **seven columns of figures** — a CSS grid
over the `<ol>`, so the markup is still a list of days in the order of the
days. Each column carries the weekday, the chance, the temperature and the
umbrella, and today is lifted out of the row with a slightly lighter
plate behind it.

**The week says "chance of rain" once, in the column heading.** The phrase
used to be on all seven rows, where it carried nothing after the first one.
Now `format_rain_chance()` returns the number with its sign for the visible
column, `format_rain_chance_short()` returns the bare number for the
hourly strip's value row, and `describe_rain_chance()` returns the full
phrase for screen readers and tooltips, and the wording itself lives in
the `.severity-legend` row above
the week. That row is also the **heading row of the week**: "Rain chance"
names what the figures are, the three band names say what the colours
mean, and the temperature switch sits on the right of it.

The legend row is **one flex row that wraps**, with the three band names
wrapped in a `.legend-bands` group so that the group takes the slack, and
the unit switch pushed to the right with `margin-left: auto`. When the row
is too narrow for the bands and the switch, the switch wraps to a second
line and stays on the right of that line.

The visible number is wrapped in `aria-hidden="true"` and a `.sr-only` span
carries "100% chance of rain" beside it. The umbrella carries its own
words in a second `.sr-only` span — "Take an umbrella." — so the two
sentences are read one after the other and neither is lost. The heading is
a `<span>`, not a real table header, so the column itself has to say what
the number means. The hourly table below *does* have a real `<th scope="col">Rain
chance</th>`, so its cells can be bare numbers.

**The narrow layout is decided, not left to flexbox.** Below 560px the
seven columns get narrow enough for the numbers to touch, so the type in
them is cut down and the **date number goes**: the weekday stays, the full
date is still on the page for screen readers. The columns stay seven — a
week that turned into a stack of rows at phone width would be a different
design, not a narrower one.

**The donation link sits under the search, not under the forecast.** It is
on every page, including error pages, because it is a site-wide link rather
than part of the result. The band name in the headline is a sentence, not a
badge, and the ☔ icon in the week keeps its own meaning — one icon for one
meaning — so the banner carries no icon of its own.

**The temperature switch asks the service to convert, not the app.** The
Open-Meteo request carries `temperature_unit`, and the service returns the
values in that scale. The app never does the arithmetic: a hand-rolled
conversion rounds differently from the service's, and the two would disagree
on the same day. The unit arrives as a `unit` parameter — in the query string
on a GET, in the form on a POST — and anything unrecognised falls back to
`DEFAULT_TEMPERATURE_UNIT` rather than failing the page. The switch is a
pair of links, not a form with a submit button, so it works without
JavaScript; a GET with a city re-runs the forecast in the other scale. The
search form carries the unit in a hidden field, so a new search keeps the
scale the reader chose.

**Deployment runs a prebuilt image, not a build.** `render.yaml` uses
`runtime: image` pointing at `docker.io/lasiurusbat/rainalert:1.2.1` (the release that is
live; when the next release is in preparation, the file may name a tag that
is not pushed yet, and a manual deploy before then has no such image to
pull). Render
pulls that image; it never runs the `Dockerfile`. A release is therefore a
pushed image tag, not a merged commit. The old `runtime: python` shape,
where Render ran `pip install` and gunicorn itself, is gone — that is the
shape the old stub service ran. The image exists and the service
pulls it. See "Deployment status" above.

**CI runs the tests inside the built image.** `.github/workflows/ci-cd.yml`
builds for `linux/amd64` and runs the offline suite
(`python -m unittest discover -s tests/offline -t .`) in the
container, so that what is tested is exactly what will be shipped. The image
that passes the tests is the image that is pushed — it is not rebuilt for the
push. The suite needs no locale data any more, so it would also pass on a
stock runner; the reason for running it in the image is that it tests the
shipped artefact, not the developer's machine.

**The browser suite runs on the runner, not in the image.** `tests/test_browser.py`
drives a real headless Chrome, and the image installs no system packages on
purpose, so Chrome cannot be in it. The suite therefore runs as a step on
the GitHub runner, against the same source, **before** the push — so a
failing browser test means the image is never pushed at all. The offline
suite still runs in the image, because that one can be.

**Releases are git tags.** A tag matching `v0.9` or `v1.2.3`, pointing at a
commit already on `main`, builds and tests the image, pushes it to Docker
Hub as the version without the `v`, and calls Render's deploy hook with an
`imgURL` parameter naming that exact tag. Pull requests never push and never
deploy, so the secrets are only touched on a tag run. **`v1.0`, `v1.0.1`, `v1.1.0`
`v1.1.1` and `v1.1.2` have all been pushed and the whole path has run green**, so a release is a
tag and a push and nothing else: the build, the offline suite inside the
image, the browser suite on the runner, the Docker Hub login, the push, the
hook and the smoke test on the live domain.

**Every page says which build is answering.** `APP_VERSION` and `APP_COMMIT`
are read from the environment and passed to every template as `app_version`
and `app_commit`; the footer carries them under the data credits, on every
page — the forecast, the city index and the 404. A release build is stamped
by the Docker build args the CI workflow passes, so the live page names the
release and the commit it came from. A development run says "Version dev"
and names no commit, because a working tree is not a commit. The point is
that the version is *on the page*: the workflow's smoke test greps the live
page for `Version <tag>`, which is how it tells "the site is up" from "the
new build is up".

**The donation link is opt-in.** `DONATION_URL` is read once at import through
`clean_donation_url()`, which accepts only absolute `https://` URLs without
whitespace, quotes or angle brackets and returns `""` for anything else. A
context processor passes it to every template as `donation_url`, reading the
setting on each request so tests can patch `rainalert.config.DONATION_URL`.
When it is empty no donation markup renders at all. The link appears just
under the search button and in the footer. It is a plain link with
`rel="noopener noreferrer"`, never an embedded widget or script.

**The weather data licence limits what the site may do.** Open-Meteo's free API
is non-commercial. Voluntary donations are allowed; advertising, affiliate
promotions, subscriptions and paid tiers are not, and would need a paid
Open-Meteo plan. The donation page must stay one-off donations only. The footer
credits for Open-Meteo (CC BY 4.0) and OpenStreetMap are required and have
tests; do not remove them.

**The saved city and the personal threshold live in the browser, not on the
server.** `static/app.js` keeps both in `localStorage`, and the server
stays stateless: it never sees either value, and a first-time visitor sees
exactly the page a returning one does. The server's only job is to tell the
page what kind of page it is, through four attributes on `<body>`:
`data-autoload` (may this page load a remembered city by itself?),
`data-search` (`ok`, `error` or `none` — was the last search worth
remembering?), `data-city` and `data-unit` (the scale the temperatures in
the forecast are in — the browser cannot work it out on its own). Without
JavaScript neither control can do
anything, so the preferences row is hidden by the `.no-js` class and the
page is exactly what it was before.

**A city is only remembered once a search for it has actually worked.** The
submitted city waits in `sessionStorage` until the result page confirms the
search was good, so a typo is never remembered and a failed search does not
destroy the city that was already saved. Unticking the box forgets the city
straight away.

**The personal threshold is a second answer, not a second umbrella.** The
umbrella, the banner, the ☔ icon and the tab title are the app's advice and
all fire at `UMBRELLA_THRESHOLD`. The reader's own threshold is marked
differently — a ▲ with its own words — because it answers a different
question. The two never stand in for each other, and the marker is not
carried by colour alone.

**The preferences row is set in bold.** It is a feature, not a footnote:
at the quiet weight it started at, a reader walked straight past it and
did not know the app could remember anything. The row is also slightly
larger and lighter than the surrounding text (`0.75rem` at `#a3b3bb`) so it
reads as a control rather than as a caption. It sits at the foot of the
panel, below a hairline, and the panel still fits a 768px window with no
scrollbar.

**The threshold is compared against the number the page shows.** The row
carries `data-chance`, the same whole number `format_rain_chance()` renders,
so the threshold and the number on the page can never disagree. A day the
service did not report has no `data-chance` at all, so it is never counted
as a dry day and never marked as a wet one either.

**Every `localStorage` access goes through a try/except.** A browser in
private mode, or one where the reader has blocked site data, throws on the
first access. The helpers swallow that, so a browser that refuses to store
anything loses the feature instead of breaking the page.

**The notification is the same rule, delivered in the background.** Tier 2's
second half: the page polls `/api/alert` every `NOTIFICATION_POLL_MINUTES`
while it is open, and the server answers with at most one event — rain in the
current hour, or rain starting within `NOTIFICATION_LEAD_HOURS`.

- **The decision is on the server, not in the script.** `notification_event()`
  in `rainalert/domain/alerts.py` decides what is worth interrupting a reader for and writes the
  wording; the browser only asks, shows and remembers. That keeps the rule
  behind the offline test suite instead of inside a string in `app.js`.
- **The event's key is what stops a repeat.** The key is the day for the
  "right now" event and the hour for the one that is coming, and the browser
  keeps the keys it has already shown. A poll that lands twice in the same wet
  hour, or two open tabs, do not say it twice.
- **The notification uses the reader's own threshold when there is one**, and
  says so in the body ("Above your 40% threshold."). Without a threshold it
  uses `UMBRELLA_THRESHOLD` and it is the app's advice, umbrella and all —
  the same split as the ▲ marker, for the same reason.
- **The button lives in the hourly title row**, because the panel has no
  vertical room for another line: the panel is 597px and the page fits a
  768px window with no scrollbar. The `.hourly-head` row takes the button on
  the right of the title, so it costs the 2px the button is taller than the
  title, not a whole line.
- **The bell is drawn, not borrowed.** It is an inline SVG in the markup and
  the script never swaps it for an emoji: a colour emoji arrives as a
  little coloured picture in the middle of a night. The state is in the
  drawing as well as in the words — a strike across the bell when the
  browser has blocked notifications, the lamp's amber when they are on.
- **The button is `hidden` in the markup** and only revealed by the script,
  and only when `Notification` exists and the context is secure. A browser
  that cannot show notifications never gets a dead button; one that has
  blocked them gets a disabled "Notifications blocked".
- **This is the browser's edge, and the page does not pretend otherwise.** It
  only works while the tab is open. Real push is Tier 3 and needs a server, a
  database and a scheduler.

**The calendar export is the last browser-side piece.** Tier 2's third half: a
link on the forecast page that downloads an `.ics` file with one all-day event
for every day that reaches the threshold. The reader's own calendar app then
does the alerting, so RainAlert needs no server, no account and no scheduler
for that — which is the whole of Tier 3 handed to software the reader
already has.

- **The file is built on the server.** `build_calendar()` in
  `rainalert/calendar_ics.py` writes
  the whole iCalendar file, and `/calendar.ics` serves it. The browser only
  says which threshold the reader is using, so the rule that decides which
  days go in the file is behind the offline test suite and not inside a
  string in `app.js` — the same split as the notification.
- **The threshold is the reader's own when they have set one**, and the app's
  umbrella threshold when they have not. That is the same split as the ▲
  marker and the notification, for the same reason: the reader's limit and
  the app's advice are two different answers and never stand in for each
  other. `alert_threshold()` decides it, so the notification and the export
  always draw the line in the same place.
- **The days are the ones the page shows.** The file is built from the
  same parsed `Day`s as the page, and the comparison is against
  `chance_number()`, the whole number in the row, so the calendar and the
  list can never disagree about which days are wet. The page counts the days
  that would go in the file from those same `Day`s, to decide whether to
  offer the link. A day the service did not
  report is never in the file: an unknown chance is not a chance of
  anything.
- **The events are all-day events**, because the forecast is a daily maximum.
  The file says which days are wet; the reader's calendar app decides when
  to remind them about it. The event id is derived from the city and the
  date, so importing the file again updates the same events instead of
  adding a second copy of every one of them.
- **The link sits on the caption's line**, next to "7-day rain chance".
  The two are in one `.result-subline` row with `align-items: baseline`, so
  the link reads as part of the caption rather than as a button dropped
  beside the answer. The panel is at its vertical limit — 597px, and the
  page fits a 768px window with no scrollbar — so a new line would not
  fit, and the link costs 0px: the caption's line is a line the page was
  already taking. The heading above takes the slack and the subline does
  not, so a long city name wraps the heading rather than pushing the link
  off the panel.
- **The icon is 10px, so it belongs to the caption's line.** An icon that
  stands on the baseline is as tall as the icon is, and at 13px it
  climbed above the caption and read as part of the city's name instead.
  At 10px its top is level with the caption's own text, and the whole
  link sits in the band just above the headline.
- **The link is hidden when there is nothing to export.** A link that would
  download an empty calendar is not an offer, so the server leaves it
  `hidden` when no day reaches the app's threshold, and the script takes it
  away again when the reader's own higher threshold leaves nothing. The
  `hidden` attribute needs its own CSS rule, or `display: inline-flex` would
  win and the link would show anyway.
- **The export is never cached, and never intercepted.** The file holds a
  forecast, so a copy of one would be a lie: the response is `no-store`, and
  the service worker skips `/calendar.ics` so that an offline page can never
  be downloaded in its place.

**The app is installable, and the two caching rules are the whole design.**
`static/manifest.json` and `static/service-worker.js` are served from the
**root** — `/manifest.json` and `/service-worker.js` — by two thin routes in
`rainalert/web/site.py`, so the manifest's scope and the worker's scope are the whole site
rather than `/static/`. The worker is also sent with `Service-Worker-Allowed: /`
so the header cannot contradict the path. The manifest carries the three icons
a browser needs to offer the install (192, 512 and a maskable 512, whose
safe zone the generator keeps clear), and `templates/index.html` links it with
`{{ url_for('manifest') }}` next to a `theme-color` meta and an
`apple-touch-icon`.

- **The forecast is never cached.** A navigation is network-first and
  bypasses the browser's own cache as well (`fetch(request, {cache:
  'no-store'})`), `/api/` is never intercepted at all, `/calendar.ics` is
  skipped for the same reason, and `/` is deliberately absent from the shell
  list — there is a test that asserts it. A rain chance from yesterday is
  wrong, so it is never replayed.
- **The shell is cached**, so an installed app opens without a network and
  shows `static/offline.html` instead of the browser's error screen. The
  shell is the stylesheet, the script, the icons, the font and the
  background photo: the files that make the page *look* like Rain Alert,
  and nothing that carries data. The offline page says plainly that the
  forecast cannot be fetched, and shows no forecast.

**The app says it can be installed, in two quiet places.** Without a word
about it, nobody finds the Chrome menu entry. Both pieces live in
`templates/_footer.html` and `static/app.js`, so they are on every page
that loads the script (the forecast pages; the city index, the release
notes and the 404 load no script, so their link stays hidden).

- **A footer link, "Install app"**, on the build's line after "Release
  notes", so it costs no height. It is `hidden` in the markup and the
  script reveals it only when the browser can install: Chrome on Android
  hands over `beforeinstallprompt`, which the page keeps and the link
  opens; Safari on an iPhone has no such prompt, so the link shows the
  steps ("Share, then Add to Home Screen"). It stays hidden in an app that
  is already installed (`display-mode: standalone`, `navigator.standalone`,
  the `appinstalled` event) and in every other browser.
- **A one-time hint**, a fixed note over the page (so the panel gains no
  height), shown on a **later visit by a reader who has a city
  remembered**: `rainalert.visits` counts browser sessions and must be at
  least 2, and `rainalert.installHintSeen` is written the moment it shows,
  so it is shown once. It is not tied to the moment a city is saved,
  because that happens on the first visit. It is set in paper and mist, no
  amber: the lamp means rain.
- **Chrome's prompt can be used once.** The link clears it after
  `prompt()` and waits for the next `beforeinstallprompt`.
- **`beforeinstallprompt` is listened for at once, not in `start()`**,
  because Chrome can send it as soon as the page has loaded.
- **Headless Chrome sends a real install event on localhost**, which would
  replace a test's own fake one and leave its `prompt()` uncounted. The
  tests in `InstallBrowserTestCase` swallow trusted events before the page
  sees them.
- **Safari is told from other iOS browsers by its user agent.** Chrome,
  Firefox, Edge and Opera on an iPhone (`CriOS`, `FxiOS`, `EdgiOS`,
  `OPiOS`) are not offered the link, because the steps name Safari's
  Share menu. The tests set the user agent with
  `Emulation.setUserAgentOverride` and put it back in a cleanup, because
  the browser is shared by the whole class.
- **Chrome cannot emulate `display-mode: standalone`**, so the test for an
  installed app wraps `window.matchMedia` in a script added with
  `Page.addScriptToEvaluateOnNewDocument`. Remove such a script in a
  cleanup (`Page.removeScriptToEvaluateOnNewDocument`), or it is still
  there for the next test.
- **A browser that stores nothing never sees the hint.** The visits cannot
  be counted, so a returning reader cannot be told from a new one; the
  hint stays away rather than guess. The footer link still works.

**Bump `CACHE_VERSION` in `static/service-worker.js` when the shell
changes.** The old caches are dropped when the new worker takes over, and
the shell is refreshed in the background, so a reader gets the new files on
the load after the one that fetched them. Without the bump, a changed
`style.css` or `app.js` keeps being served from the cache.

**The worker registers itself only when it can work.** `static/app.js` checks
for `serviceWorker` in `navigator` and for `window.isSecureContext`, and
registers on `load`. `http://127.0.0.1` and `http://localhost` are secure
contexts, so it works in local development, and a failure is swallowed
because the app works without it.

- **The security headers are strict because the site loads nothing from
  elsewhere.** `rainalert/web/security.py` sets the CSP (`default-src 'none'`,
  everything else `'self'`, no `unsafe-inline`), `X-Frame-Options: DENY`,
  `nosniff`, `Referrer-Policy` and `Permissions-Policy`. HSTS is sent only
  when the request was HTTPS (`X-Forwarded-Proto` behind Render's proxy), with
  no `includeSubDomains` or `preload`. So: no inline `style=`, `<style>` or
  `<script>` (the JSON-LD block is data and is exempt), and no third-party
  asset. A test fails on either; widen the policy deliberately if one is needed.

## Gotchas

- **Do not remove `static/googlee75783b48c054b73.html` or `static/BingSiteAuth.xml`,
  or their routes.** Google Search Console and Bing Webmaster Tools verified the
  site by fetching them from the root, and both say the files must stay for the
  site to stay verified. `VERIFICATION_FILES` in `rainalert/web/site.py` lists
  them, `verification_file()` serves them, and tests hold them.

- **`strftime('%A')` follows the process locale**, which is why the weekday
  names are hard-coded in `WEEKDAY_NAMES` rather than read from
  `strftime`. On a German Windows machine, or in a container with `LANG`
  set, `strftime` would render the weekday in that language.
- **Banker's rounding.** Python's `round(8.5)` is `8`, not `9`. Use the
  `round_half_up()` helper for temperatures, where halves are common.
- **Do not use `.title()` on user input.** It turns `"st john's"` into
  `"St John'S"`. The app shows the first comma-separated segment of the
  geocoder's own `display_name` — "Gdansk", not "Gdansk, Pomeranian
  Voivodeship, Poland".
- **The CSS file once contained a literal `\n`** (backslash-n, not a
  newline) that silently swallowed the next declaration. If `background-size`
  ever stops applying, check for stray escape sequences in the raw bytes.
- **The `hidden` attribute loses to a class that sets `display`.** The UA
  stylesheet's `[hidden] { display: none }` is weaker than
  `.notify-toggle { display: inline-flex }`, so a button that is hidden in the
  markup would still show up. The rules `.notify-toggle[hidden]` and
  `.calendar-export[hidden] { display: none; }` are there for exactly that:
  the first keeps the notification button from being a dead button before
  the script has run, the second keeps the export link from appearing when
  there is nothing to export.
- **The browser suite needs Chrome and selenium, and skips without them.**
  `tests/test_browser.py` is not in the image (`.dockerignore` leaves it
  out): the image installs no system
  packages, so there is no Chrome in it. It runs on the CI runner instead,
  where Chrome is already installed. Install the driver locally with
  `pip install -r requirements-dev.txt`. The suite skips itself when
  selenium or Chrome is missing, so a plain `python -m unittest` never
  fails because of it — but a skipped suite is not a passing suite, so
  check that it actually ran before trusting it.
- **A page is not controlled by a service worker just because it is
  active.** `clients.claim()` takes charge of the pages that are open at
  the moment it runs, and a page navigated after that is not controlled
  until it is loaded again. So a test that wants "the worker is in
  charge" cannot wait for `navigator.serviceWorker.controller` alone: it
  has to wait for the registration to be **active** first, and then load
  the page once more when it is not controlled yet. Waiting only for the
  controller timed out on a CI runner that had just moved to a new
  image, with the worker installed and activated and the page still
  uncontrolled. `wait_for_the_worker()` in `tests/test_browser.py` does
  this now.
- **A "re-run failed jobs" re-runs the commit the tag points at.** The
  release run is pinned to the tag, so a fix to the test suite does not
  reach it: the button replays the old workflow against the old commit,
  and the same test fails again. A fix has to be pushed into the tag
  itself. The `v1.0` tag was moved to the fixed commit on 2026-10-22,
  which is what re-fired the run — and it is safe to do, because a tag
  that never produced a published image has nothing to move.
- **A local Docker image is never rebuilt on its own.** Compose reuses
  `rainalert:latest` whenever it exists, so `docker compose run --rm tests`
  can test yesterday's code and still say `OK`. The compose file now sets
  `pull_policy: build`, so the image is rebuilt from the source every time —
  if that ever goes missing, the symptom is a test count that does not
  match the suite.
- **Jinja caches templates when debug mode is off.** Restart the server after
  editing `index.html`, or run with `FLASK_DEBUG=1`.
- **A browser caches a favicon by its URL, not by its contents.** Rewriting
  `static/favicon.svg` in place changes nothing until the cache is cleared,
  so the rain icon is a **second file** with a second URL
  (`static/favicon-rain.svg`). If the icon ever stops swapping, look for a
  reused URL before suspecting the code.
- **The `<title>` and the icon are template variables, not static markup.**
  `render_forecast_page()` passes `page_title` and `favicon` to the template,
  so any route that renders `index.html` has to pass them too — otherwise the
  title renders empty and the icon URL breaks. Two routes render that
  template today, `/` and `/city/<slug>`, and both go through
  `render_forecast_page()`; six (`/api/alert`, `/calendar.ics`,
  `/robots.txt`, `/sitemap.xml`, `/manifest.json`, `/service-worker.js` and the two
  search-engine ownership files)
  render no template at all, and `/cities`, `/release-notes` and the 404
  handler render their own templates with their own titles. The
  forecast page keeps the default icon whenever there is no alert, which is
  the case for the empty page and
  for every error page. The title is never a bare "Rain Alert" either:
  without an alert it reads "7-day rain chance for London - Rain Alert" on
  a city's page and "Rain Alert - 7-day rain chance for any city" on the
  start page, so every page says what it is about. A page that is **not
  there** is the one exception, and it says exactly that: "Page not found
  - Rain Alert", the same words the site's own 404 page uses.
- **A city page is a `404` or a `503`, not a page with a message on it.**
  A `200` that says "not found" is a soft 404. The start page is different:
  a failed *search* there is not a missing *page*, so it stays `200`.
- **The page is a `.page` flex wrapper around `.container` plus the
  copyright footer.** `margin: auto` lives on `.page`, not on `.container`.
  The footer sits over the background photo, so it is white text on a
  plate of its own (translucent dark, blurred, hairline edge) rather than
  inside the panel. Adding vertical space to the panel
  or footer can push the document past `100vh` and reintroduce a scrollbar
  on a standard desktop view — measure `scrollHeight - clientHeight` after
  changing it.
- **A colour emoji is not a glyph.** `☔` (U+2614) takes the text
  presentation selector `&#xFE0E;` and comes out in the panel's own
  amber, but `📅` and `🔔` ignore it on Windows and arrive as little
  coloured pictures. The calendar and the bell are inline SVGs with
  `stroke="currentColor"`, and the script never swaps them for emoji
  either — it changes the words and a class, and the drawing follows.
- **The week must stay seven columns.** The columns are a CSS grid over
  the `<ol>`, and the band name lives in a **legend** above them, not on
  every column: seven repeated labels do not fit and would carry nothing
  after the first one. Each column carries the band name in a `.sr-only`
  span for screen readers. Severity must never be conveyed by colour
  alone. The same rule is why the "chance of rain" wording is a column
  heading rather than a per-column label.
- **The panel has to stay inside a 768px-tall window.** The panel is 597px
  tall and the page fits a 768px window with no scrollbar, with about 65px
  of slack above and below. Measure `scrollHeight - clientHeight` in a
  real browser after changing anything in it — a stock GitHub runner has
  a different viewport than the developer box, and the CI image is where
  the tests run. `tools/measure.py` prints the boxes, and there is a
  browser test that fails when the page scrolls.
- **The seven day panels share one cell of one grid.** They are laid out
  with `grid-area: 1 / 1` and the ones that are not showing are hidden
  with `visibility: hidden`, which keeps them in the cell without
  showing them. That is what stops the strip from changing height when
  the reader picks another day. Do not swap `visibility` for the
  `hidden` attribute: that takes the panel out of the grid, the cell
  shrinks to the shortest panel, and the week jumps.
- **The seven strips share one cell of one grid, the same way.** A strip
  is a day's graph, and the reader picks the day, so there is one strip
  per day and only the picked one shows. The same rule applies: `visibility:
  hidden`, never the `hidden` attribute.
- **The summary reserves two lines.** The days' summaries are different
  lengths, and a longer one would push the graph down, so
  `.hourly-summary` has a `min-height` of two lines. Drop it and the
  graph jumps when the reader picks a day whose sentence is longer.
- **The value row has to fit twenty-four numbers across the panel.** The
  sign is left off for that reason, and the type is set at the narrowest
  width of the family (62) at `0.77rem`. Set the percent sign back and
  the numbers collide; the sign lives in the sentence above, the tooltip
  and the table below. The size is bounded from above by the same row: a
  column of the widest panel is about 17px, and a hundred at `0.77rem`
  is about 15px wide, so the numbers keep a gap between them — but at
  `0.96rem` the row grows wider than the card and the numbers run
  together. A browser test holds that line, at three widths.
- **The label of the current hour is wider than its column.** It is
  written under its own value, and it hangs over the columns beside it.
  In the first and the last column it is pinned to the edge it cannot
  hang over, or it would stick out of the card.
- **A flex row of an icon and its words aligns on the icon, not on the
  words.** An inline SVG is a replaced element, so its baseline is its
  bottom margin edge, and the first flex item is what decides the
  baseline of the whole flex container. The export link therefore sets
  `align-items: baseline` on itself: the icon's bottom edge lands on the
  text's baseline, and the link then shares the caption's baseline
  through the subline. Put `align-items: center` back and the link's
  baseline becomes the icon's, so the words ride up above "7-day rain
  chance" instead of sitting on it.
- **An icon that stands on the baseline is as tall as it is.** The
  calendar icon is 10px for that reason: at 13px it reached above the
  caption's line and into the gap under the city's name, which is what
  made the whole link look as if it belonged to the name. The browser
  test that guards this measures the icon's top against the caption's
  own top.
- **The caption and the link are set at slightly different sizes**
  (0.72rem and 0.7rem), so their text boxes are not the same height
  even when the baselines match. A test that compares the boxes will
  fail for the right reason; the test measures the baseline, with a
  zero-height box standing on the text.
- **The label of the current hour lives in the value row.** It is
  absolutely positioned under its own value, in the gap the strip's
  `margin-top: 20px` leaves above the bars. Put it in the axis and it
  collides with the hour marks below it.
- **A `set_window_size` in headless Chrome measures the wrong page.**
  It includes the browser's own chrome, so the viewport comes out at
  616px instead of 768px and the page looks as if it scrolls. Set the
  viewport with `Emulation.setDeviceMetricsOverride`, the way
  `tests/test_browser.py` does.
- **The hourly axis labels sit on the hour boundary, not on the bar.** Each
  label is positioned at the left edge of its own cell, so "06" is under
  the gap before the 06:00 bar rather than under the middle of it. The
  first cell is nudged back inside, or its label would hang off the card.
- **The current hour is a rule, not a mark.** It is a `::after`
  pseudo-element on the hour's own cell, a 1px line in paper white running
  through the strip. It is drawn in ink rather than in a data colour, so
  the data mark itself is not altered, and it carries no animation: a
  pulse is decoration, and the night street has none. The words "now
  11:00" sit over the rule in the gap above the strip.
- **`.container` is `box-sizing: border-box`.** With the default
  content-box, `width: 92%` plus the padding pushed the panel past the
  viewport edge on narrow screens.
- **gunicorn 26 needs a writable home.** It opens a control socket at
  `$HOME/.gunicorn/gunicorn.ctl` (or `$XDG_RUNTIME_DIR/gunicorn.ctl`) and
  fails with "Permission denied" on a user created without `--create-home`.
  The image creates `/home/rainalert` and sets
  `XDG_RUNTIME_DIR=/run/rainalert`, both owned by uid 1001.
- **Render does not redeploy an image service when a new image appears.**
  A new tag on Docker Hub is not enough on its own; the deploy hook has to
  be called with the `imgURL` parameter naming the tag. See `DEPLOY.md`.
- **`rainalert.onrender.com` is not this app and no longer exists.** It was
  an older stub that answered with JSON; it has been deleted. The service's
  own onrender address is `rainalert-1-0.onrender.com`, and the app's public
  address is `https://rainalert.live/`.
- **A resolver that still holds the old forwarding record will say the
  site is down when it is not.** The domain used to be on Namecheap URL
  forwarding, and a local resolver can keep answering with the forwarder's
  address for a long time after the records have changed — the connection
  then times out, which looks exactly like the site being gone. Ask a
  public resolver what the domain is (`nslookup rainalert.live 1.1.1.1`)
  before believing that the site has gone down; a CNAME to
  `rainalert-1-0.onrender.com` and `216.24.57.16` are the right answers.
  `ipconfig /flushdns` clears the local cache.
- **Open-Meteo has gone down before** (TCP 443 unreachable while DNS still
  resolved). When the forecast endpoint fails, the app correctly shows "The
  weather service is unavailable right now" — that is the app behaving
  properly, not a regression.
- **A broken answer and a missing answer are different.** An answer that is
  not shaped like a forecast is a `503`; a `daily` block that is simply
  absent is a `200` with "No forecast data available". A daily *field* that
  is there but is not a list is a broken answer, so it is a `503` and not a
  `200` with an empty week. The hourly block is never checked this way: a
  broken strip takes the strip away and leaves the week.
- **`_is_a_forecast()` accepts a tuple as well as a list.** The daily arrays
  are lists in the service's answer, but the offline tests build them as
  tuples, and a validator that is stricter than the tests turns a working
  fixture into a `503`.
- **A service worker's scope is the path it is served from.** Served from
  `/static/service-worker.js` it would control `/static/` and nothing else,
  and the page at `/` would never be under its control. The
  `Service-Worker-Allowed: /` header widens the scope, but serving the
  worker from the root is simpler and needs no header to be right.
- **`unittest` builds a new test instance per test method.** Anything that
  has to survive from one test to the next — a server that was restarted, a
  shared browser, a list of recorded connections — has to live on the class,
  not on `self`, or the next test never sees it.
- **Closing a Werkzeug server can block for minutes.** `server_close()` joins
  the keep-alive handler threads, so the open connections have to be shut
  down first. The offline browser tests record every connection the server
  accepts and close them all before the server goes away.
- **CDP's `Network.emulateNetworkConditions` does not reach a service
  worker's own `fetch()`.** Emulating an offline network in the page does
  not make the worker's navigation fail, so the offline test takes the
  server away for real instead of pretending.

## Conventions

- Styling goes in `static/style.css` as classes, not inline `style`
  attributes in the template.
- User-facing error messages are plain English sentences ending in a period.
- Log with `app.logger` in a route and `logging.getLogger(__name__)` in
  the package, never `print()`. Both end up in Flask's handler.
- New user-visible strings belong in the template or in the `rainalert`
  package - a label in `present/labels.py`, a sentence about the rain in
  `domain/alerts.py`, an error in `errors.py` - and the UI text is English,
  and so are the weekday names.
- **A change that must not change what the site serves is checked by
  snapshot.** Run `python tools/snapshot.py snapshots/before` before the
  change and `python tools/snapshot.py snapshots/after` after it, then
  `diff -r` the two directories (`snapshots/` is git-ignored): every route's answer,
  with both upstreams mocked, has to be identical. The tests check what they
  were written to check; the snapshot checks everything else.
- **A test lives with the module it tests**, in `tests/offline/`, and
  imports that module directly. Patch a name where it is defined:
  `rainalert.config`, `geocoding.geolocator`, `requests.get`.
- **The tab title, the favicon, the ☔ icon and the banner are one alert.**
  They all read the same forecast and fire at the same `UMBRELLA_THRESHOLD`.
  Do not give any of them a threshold of its own — the moment two of them
  disagree, the page starts lying to the reader.
- **A city has one address.** `/city/<slug>` is the canonical one, and every
  other way of reaching the same forecast is sent there. Do not add a second
  way of rendering a forecast, and do not change the shape of the slug: the
  address is what people bookmark and what search engines index.
- **A missing page answers `404` and a broken upstream answers `503`.** A
  page that says "not found" but answers `200` is a soft 404, and search
  engines treat it as one.
- **One builder per page-level fact.** The title, the description, the
  canonical link, the robots meta and the structured data are all made in
  `render_forecast_page()`. Do not build a second one in a template.
- **Do not bump the image tag in `render.yaml` by hand as part of a normal
  change.** Releases are cut by pushing a `v*` tag; the workflow derives the
  image tag from it. The tag in `render.yaml` is only the fallback for a
  manual deploy, and `DEPLOY.md` explains when to update it.
- **The test count appears in four documents** — `README.md`, `CLAUDE.md`,
  `DEPLOY.md` and `implementation-plan.md`. They drift. Update all four when
  tests are added.
- **`API.md` and `openapi.yaml` describe the HTTP surface, and they are
  written by hand.** They are not generated from the app, so they drift the
  moment a route, a parameter or a status code changes. When you change one,
  change both of them in the same change. The spec is a description of the
  app, not a contract with a third party — the app is free to change, but the
  documentation must not lag behind it.
