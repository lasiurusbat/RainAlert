# RainAlert

A small Flask web app that shows the 7-day rain chance for any city.

Enter a city name → geocoded to coordinates via **Nominatim** (OpenStreetMap) →
7-day forecast from **Open-Meteo** → rendered as a list of daily rain chances.

Both APIs are free, keyless, and need no signup. There is no database and no
user account system.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Serves on <http://127.0.0.1:5000>. `FLASK_DEBUG=1` enables the reloader and
debugger.

```bash
python -m unittest test_app    # offline suite, 110 tests, no network
python -m unittest test_api     # live integration tests, hits both APIs
```

The offline suite is the one that gates changes. `test_api.py` requires the
upstream services to be reachable.

## Running it in Docker

```bash
docker compose up --build       # http://localhost:8000
docker compose run --rm tests   # both suites in the same image
```

`Dockerfile` is a two-stage build; the runtime image has no compiler, runs as
the non-root user `rainalert` (uid 1001), and serves with gunicorn on port
8000. The locales are compiled in from the app's own language tables, so the
image cannot drift from the supported set. `DEPLOY.md` is the deployment
runbook, and `.github/workflows/ci-cd.yml` runs the tests inside the built
image before any release is pushed.

## Layout

| Path | Purpose |
|---|---|
| `app.py` | The whole app: routes, geocoding, forecast fetching, formatting |
| `templates/index.html` | Single page; inline styles are out, classes live in `style.css` |
| `static/style.css` | All styling |
| `static/image/` | Background photo |
| `static/favicon.svg` | Tab icon |
| `test_app.py` | Offline unit tests, HTTP fully mocked |
| `test_api.py` | Live integration tests |
| `Dockerfile` | Two-stage container image |
| `docker-compose.yml` | Local container setup: the app and a test service |
| `render.yaml` | Render Blueprint; runs a prebuilt image, not a build |
| `DEPLOY.md` | Deployment runbook: Render setup, domain, CI/CD, releases |
| `.github/workflows/ci-cd.yml` | CI on every PR and push; release on a git tag |
| `.github/dependabot.yml` | Weekly grouped PRs for actions, pip and the base image |

## Architecture notes

**Error handling is exception-based.** `app.py` defines three exceptions that
the route translates into user-facing messages:

- `CityNotFound` — the geocoder answered normally but had no match.
- `GeocodingUnavailable` — the geocoder was unreachable, rate-limited, or
  errored.
- `WeatherUnavailable` — the forecast service was unreachable or returned junk.

**The distinction between the first two matters.** Do not collapse them into a
single "not found" path: a network blip must not tell a user their valid city
does not exist. Internal exception text is logged, never rendered.

**Geocoding results are cached** with `lru_cache` on `get_coordinates`, keyed
by city name. Nominatim is rate-limited and a city name always maps to the same
place, so caching cuts load substantially. Failures are deliberately not
cached, so a retry re-attempts the lookup. Clear the cache in tests with
`get_coordinates.cache_clear()`.

**Timeouts are explicit and configurable.** geopy defaults to a **1 second**
read timeout, which is short enough to fail against a healthy-but-slow
Nominatim. `GEOCODER_TIMEOUT` and `WEATHER_TIMEOUT` (both default 10s) are
read from the environment. `requests.get` has no default timeout, so always
pass one.

**`timezone=auto` is deliberate.** Open-Meteo returns each date in the
queried city's local time. A forecast for Tokyo is dated in Tokyo's days.
Do not convert these dates to the viewer's timezone — that would be a bug.

**Weekday names are localised** via the C library's locale data, not
`babel`. `weekday_names(locale)` returns all seven names Monday-first and is
cached, so the process-wide `LC_TIME` locale is switched once per locale
rather than once per row, and the previous value is always restored.
`DATE_LOCALE` selects the locale: a fixed code (`de_DE`), or `auto` to follow
the browser's `Accept-Language` header.

**Rain severity is a three-band scale** computed in `app.py` from
`precipitation_probability_max`: under `SEVERITY_LOW_MAX` (30) is *low*,
up to `SEVERITY_MODERATE_MAX` (60) is *moderate*, above that is *high*. A
missing chance gets its own *unknown* band rather than being treated as
zero. The thresholds and `UMBRELLA_THRESHOLD` are environment variables.

The bands are named **Rain unlikely / Rain possible / Rain likely**, not
"Dry / Light rain / Heavy rain". A 25%-chance day is not dry, and a
probability does not predict an intensity — the scale has to stay honest
about what a percentage can tell you.

**The hourly strip for today sits above the daily list.** It comes from
`hourly=precipitation_probability` in the same request as the daily fields —
one request per page load, not two. `parse_today_hours()` picks out the
city's local day, and `summarise_hours()` turns it into the one-line
"Bring an umbrella" sentence.

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

**Deployment runs a prebuilt image, not a build.** `render.yaml` uses
`runtime: image` pointing at `docker.io/lasiurusbat/rainalert:0.8`. Render
pulls that image; it never runs the `Dockerfile`. A release is therefore a
pushed image tag, not a merged commit. The old `runtime: python` shape,
where Render ran `pip install` and gunicorn itself, is gone.

**CI runs the tests inside the built image.** `.github/workflows/ci-cd.yml`
builds for `linux/amd64` and runs `python -m unittest test_app` in the
container. That is deliberate: the suite asserts German weekday names, which
need the `de_DE` locale that the image installs and a stock GitHub runner
does not have. The image that passes the tests is the image that is pushed —
it is not rebuilt for the push.

**Releases are git tags.** A tag matching `v0.9` or `v1.2.3`, pointing at a
commit already on `main`, builds and tests the image, pushes it to Docker
Hub as the version without the `v`, and calls Render's deploy hook with an
`imgURL` parameter naming that exact tag. Pull requests never push and never
deploy, so the secrets are only touched on a tag run.

**The donation link is opt-in.** `DONATION_URL` is read once at import through
`clean_donation_url()`, which accepts only absolute `https://` URLs without
whitespace, quotes or angle brackets and returns `""` for anything else. A
context processor passes it to every template as `donation_url`, reading the
module global on each request so tests can patch `rainalert.DONATION_URL`.
When it is empty no donation markup renders at all. The link appears under the
forecast (only when there is a forecast) and in the footer. It is a plain link
with `rel="noopener noreferrer"`, never an embedded widget or script.

**The weather data licence limits what the site may do.** Open-Meteo's free API
is non-commercial. Voluntary donations are allowed; advertising, affiliate
promotions, subscriptions and paid tiers are not, and would need a paid
Open-Meteo plan. The donation page must stay one-off donations only. The footer
credits for Open-Meteo (CC BY 4.0) and OpenStreetMap are required and have
tests; do not remove them.

## Gotchas

- **`strftime('%A')` follows the process locale**, which is why the weekday
  lookup goes through `weekday_names()` rather than calling `strftime`
  directly.
- **Banker's rounding.** Python's `round(8.5)` is `8`, not `9`. Use the
  `round_half_up()` helper for temperatures, where halves are common.
- **Do not use `.title()` on user input.** It turns `"st john's"` into
  `"St John'S"`. The app displays the geocoder's own `display_name` instead.
- **The CSS file once contained a literal `\n`** (backslash-n, not a
  newline) that silently swallowed the next declaration. If `background-size`
  ever stops applying, check for stray escape sequences in the raw bytes.
- **Jinja caches templates when debug mode is off.** Restart the server after
  editing `index.html`, or run with `FLASK_DEBUG=1`.
- **The page is a `.page` flex wrapper around `.container` plus the
  copyright footer.** `margin: auto` lives on `.page`, not on `.container`.
  The footer sits over the background photo, so it is white text with a
  shadow rather than inside the card. Adding vertical space to the card or
  footer can push the document past `100vh` and reintroduce a scrollbar on a
  standard desktop view — measure `scrollHeight - clientHeight` after
  changing it.
- **The forecast list must stay one line per day on desktop.** The card's
  content is 500px, and a date plus a rain chance plus a text badge needs
  ~525px in English, so a per-row badge forces a wrap and doubles the list
  height. The band name therefore lives in a **legend** above the list, and
  each row carries the same word in a `.sr-only` span for screen readers.
  Severity must never be conveyed by colour alone.
- **The card has to stay inside a 748px-tall window.** The hourly strip
  added ~150px above the list, which pushed the document 25px past the
  viewport. The strip is 38px tall, the `.weather-item` padding was cut
  from `0.45rem` to `0.32rem`, and the h3 margin from `0.5rem` to
  `0.35rem` to claw the space back. Measure
  `scrollHeight - clientHeight` in a real browser after changing any of
  them — a stock GitHub runner has a different viewport than the
  developer box, and the CI image is where the tests run.
- **The hourly axis labels sit on the hour boundary, not on the bar.** Each
  label is positioned at the left edge of its own cell, so "06" is under
  the gap before the 06:00 bar rather than under the middle of it. The
  first cell is nudged back inside, or its label would hang off the card.
- **The current hour is a pulsing dot, not a tick.** It is a `::after`
  pseudo-element under the baseline, animated with a growing-and-fading
  `box-shadow` halo. The pulse is decoration, so it is dropped under
  `prefers-reduced-motion: reduce` — the dot stays, so the hour is still
  marked. The dot must not collide with the axis labels below it, which is
  what the `margin-top` on `.hourly-axis` is for. The dot is 8px with a
  10px halo and sits at `bottom: -9px`; the axis margin is 11px, which
  leaves the dot clear of the labels. If you resize the dot, resize the
  halo with it (twice the radius) and re-measure the axis margin.
- **`.container` is `box-sizing: border-box`.** With the default
  content-box, `width: 90%` plus the padding pushed the card past the
  viewport edge on narrow screens.
- **`locale.with_locale` is unavailable** in this Python build, and
  `locale.format_string` raises on a `date` argument. Use
  `locale.setlocale` with a save/restore, as `weekday_names()` does.
- **The C library spells locales differently per platform.** Windows accepts
  the bare name `de_DE`; glibc wants a codeset suffix and rejects the bare
  form even when the locale is installed, so the container rendered English
  weekday names until this was fixed. `_locale_candidates()` yields the bare
  name, then `.UTF-8`, then `.utf8` — use it rather than calling
  `setlocale` with a hardcoded name, in the app and in the tests alike.
- **The offline suite needs the `de_DE` locale.** It asserts German weekday
  names. The Docker image installs it; a bare Linux box does not have it.
- **Do not `apt-get purge locales` in the Dockerfile.** The compiled locale
  data lives in `/usr/lib/locale`, which the `locales` package owns, so
  purging it deletes the data that was just generated. Only the apt lists and
  `/usr/share/locale/locale.alias` are safe to remove.
- **`localedef -i` needs the full locale name.** `-i de` fails with "cannot
  open locale definition file 'de'"; the definitions in
  `/usr/share/i18n/locales` are named with the whole code, so use `-i de_DE`.
- **gunicorn 26 needs a writable home.** It opens a control socket at
  `$HOME/.gunicorn/gunicorn.ctl` (or `$XDG_RUNTIME_DIR/gunicorn.ctl`) and
  fails with "Permission denied" on a user created without `--create-home`.
  The image creates `/home/rainalert` and sets
  `XDG_RUNTIME_DIR=/run/rainalert`, both owned by uid 1001.
- **Render does not redeploy an image service when a new image appears.**
  A new tag on Docker Hub is not enough on its own; the deploy hook has to
  be called with the `imgURL` parameter naming the tag. See `DEPLOY.md`.
- **Open-Meteo has gone down before** (TCP 443 unreachable while DNS still
  resolved). When the forecast endpoint fails, the app correctly shows "The
  weather service is unavailable right now" — that is the app behaving
  properly, not a regression.

## Conventions

- Styling goes in `static/style.css` as classes, not inline `style`
  attributes in the template.
- User-facing error messages are plain English sentences ending in a period.
- Log with `app.logger`, never `print()`.
- New user-visible strings belong in the template or in `app.py`, and the
  UI text is English even when weekday names are localised.
- **Do not bump the image tag in `render.yaml` by hand as part of a normal
  change.** Releases are cut by pushing a `v*` tag; the workflow derives the
  image tag from it. The tag in `render.yaml` is only the fallback for a
  manual deploy, and `DEPLOY.md` explains when to update it.
- **The test count appears in four documents** — `README.md`, `CLAUDE.md`,
  `DEPLOY.md` and `implementation-plan.md`. They drift. Update all four when
  tests are added.
