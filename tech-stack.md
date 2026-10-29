# The tech stack

What RainAlert is built with, what each piece does, and why it is that
piece. It is meant to be read twice: once as an orientation for someone
joining the project, and once as a record of the decisions, so that the
next person does not have to re-derive them.

The short version: **a Flask app, five Python dependencies, a browser half
written in plain JavaScript, no database, no build step, and no third party
asked for anything at runtime.** The whole site is served by a single
container image that runs one process.

---

## The table

| Layer | What | Version | Where |
|---|---|---|---|
| Language | Python | 3.14 | everywhere |
| Web framework | Flask | 3.1.3 | `requirements.txt` |
| WSGI server | gunicorn | 26.2.0 | `requirements.txt` |
| HTTP client | requests | 2.34.2 | `requirements.txt` |
| Geocoding client | geopy | 2.5.0 | `requirements.txt` |
| Config | python-dotenv | 1.2.4 | `requirements.txt` |
| Templates | Jinja2 | (via Flask) | `templates/` |
| Styles | plain CSS | — | `static/style.css` |
| Script | plain JavaScript (ES5) | — | `static/app.js` |
| Offline | Service Worker | — | `static/service-worker.js` |
| Install | Web App Manifest | — | `static/manifest.json` |
| Type | Archivo, self-hosted | variable, Latin subset | `static/fonts/` |
| Icons / card | hand-generated PNG + SVG | — | `static/icon-*.png`, `static/og-image.png` |
| Container | Docker, two-stage | `python:3.14-slim` | `Dockerfile` |
| Hosting | Render, free plan, prebuilt image | — | `render.yaml` |
| CI/CD | GitHub Actions | — | `.github/workflows/ci-cd.yml` |
| Dependency updates | Dependabot, weekly, grouped | — | `.github/dependabot.yml` |
| Tests | unittest (stdlib), Selenium | selenium 4.44.0 | `tests/` |

Every runtime dependency is pinned to an exact version. There is no
lockfile, because there is nothing to lock: five lines in
`requirements.txt` are the whole runtime, and the Dockerfile builds wheels
from them.

---

## The backend

### Flask

**Why Flask, not Django or FastAPI.** The app has no database, no
admin, no forms library and no ORM, so most of what Django ships would be
unused weight. FastAPI would be a good fit for the API half, but the API
half is two endpoints that return HTML and an `.ics` file; the type
annotations and the OpenAPI generator would be more machinery than the
thing they describe. Flask gives routing, a template engine and a request
context, and stops there.

**What the app is built from.** `create_app()` in `rainalert/web/__init__.py`
builds the Flask object and registers the routes. `app.py` is the entry
point and nothing else: it calls `create_app()` and, under `python app.py`,
runs the development server.

**The layering.** The code is in layers, and the layers only point down:

```
rainalert/web      Flask: routes, the app factory, template globals
rainalert/present  the forecast turned into words and page data
rainalert/domain   the rules - bands, day names, alerts, parsing
rainalert/upstream the two clients - Nominatim and Open-Meteo
rainalert/data     the curated cities, the release notes
```

`domain` imports neither Flask nor `requests`, so a rule can be tested
without an app and without a mock. A new rule goes in `domain`, a new
label in `present`, a new route in `web`.

**Routes are registered on the app, not on blueprints.** So the endpoint
names - the names the templates pass to `url_for` - stay the plain function
names: `index`, `city_page`, `manifest`.

### Jinja2

**Why Jinja and not string building.** Templates give the pages autoescaping
(a city's name with an apostrophe in it cannot break the markup) and
inheritance for free, and Jinja is already a Flask dependency, so it costs
nothing extra.

**One footer, one macro.** `templates/_footer.html` holds the footer and
every page calls `{{ site_footer() }}`, so the version, the credits and the
release-notes link cannot drift apart between pages. The footer is a Jinja
macro rather than a base template because the pages share a head but not a
body.

**One builder per page-level fact.** The title, the description, the
canonical link, the Open Graph tags and the JSON-LD are all decided in
`render_forecast_page()` and passed to the template as one set, so the
title a reader sees in the tab and the title a search engine shows in its
results cannot disagree.

### gunicorn

**Why gunicorn and not the Flask dev server in production.** The dev
server says on startup that it is not for production; gunicorn is a real
WSGI server, and it is what lets the image run one worker with four
threads instead of the dev server's own thread-per-request model.

**How it is run.** One worker, four threads:

```
gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 30 --access-logfile - app:app
```

One worker on purpose: the app is I/O-bound on two keyless APIs, and the
geocoding cache is per process, so a single worker keeps the cache warm and
avoids duplicate Nominatim lookups. Four threads is enough for the
traffic a free-tier service sees.

**The writable home.** gunicorn 26 opens a control socket at
`$HOME/.gunicorn/gunicorn.ctl` and fails with "Permission denied" on a user
created without `--create-home`. The image creates `/home/rainalert` and
sets `XDG_RUNTIME_DIR=/run/rainalert`, both owned by uid 1001.

### requests

**Why requests and not `urllib`.** Timeouts are the reason, and they are
not optional: `requests.get` has no default timeout, so every call passes
one explicitly (`WEATHER_TIMEOUT`, 10s by default). The alternative -
`urllib.request` - needs more code for the same thing.

### geopy

**Why geopy and not a raw HTTP call to Nominatim.** geopy is a thin,
well-behaved wrapper around the Nominatim API, and it is one dependency
rather than a URL, a query string and a parser to maintain.

**The timeout is configuration.** geopy defaults to a **one second** read
timeout, which is short enough to fail against a healthy-but-slow
Nominatim. `GEOCODER_TIMEOUT` (10s by default) is read from the
environment for the same reason.

**The user agent is configuration.** Nominatim's usage policy asks callers
to identify themselves, so `NOMINATIM_USER_AGENT` is a setting.

**Results are cached** with `lru_cache(maxsize=256)` on
`get_coordinates`, keyed by city name. A city name always maps to the same
place, and Nominatim is rate-limited. Failures are deliberately *not*
cached, so a retry re-attempts the lookup.

### python-dotenv

**Why.** `load_dotenv()` reads a `.env` file next to the project, so a
developer can set `SITE_URL` or `DONATION_URL` without exporting anything.
`.env` is git-ignored; the file is never in the image.

### The standard library, used more than it looks

`unittest` for the tests (no pytest), `datetime` for the dates and the
hours, `functools.lru_cache` for the geocoding cache, `re` and
`unicodedata` for the slugs, `dataclasses` for the forecast model,
`decimal.Decimal` for the half-up rounding, `logging` for the logs,
`urllib.parse` to check the donation URL before it is rendered. The
standard library is a dependency too, and it is the one that is always
there.

---

## The frontend

### Plain CSS, no framework, no preprocessor

**Why not Tailwind or Bootstrap.** The design is one page of night street
in a handful of colours, with a type scale and a layout that has to fit a
768-pixel-tall window without a scrollbar. That is a few hundred lines of
CSS, hand-written, and a utility framework would be a build step, a
`node_modules`, and a class name on every element that says less than the
CSS does.

**No build step at all.** The stylesheet is served as it is written. There
is no npm, no bundler, no transpiler and no minifier, so what you read in
`static/style.css` is what the browser gets, and the browser's devtools
show the same rules.

**How it is organised.** The width axis does the work: the city name is set
wide, the labels narrow, the figures wide again in tabular numerals. The
Archivo variable face carries a `wdth` axis, so one family covers the
whole scale.

**The `hidden` attribute loses to a class that sets `display`.** The UA
stylesheet's `[hidden] { display: none }` is weaker than
`.notify-toggle { display: inline-flex }`, so a button hidden in the markup
would still show up. There are explicit `.notify-toggle[hidden]` and
`.calendar-export[hidden] { display: none; }` rules for exactly that.

### Plain JavaScript, no framework

**Why not React, Vue or Svelte.** The browser half does four things:
remember a city, remember a threshold, mark the days that reach it, show a
notification, and switch the visible day panel. That is a few hundred
lines of DOM manipulation. A framework would add a build step, a bundle and
a runtime to do what `querySelector` and a `for` loop already do - and it
would put a compile step between the code and the page, which is a
liability when the page has to work without any of it.

**ES5 on purpose.** The script is written in ES5 (`var`, `function`), with
no arrow functions, no `let`/`const` and no template literals. The reason
is not nostalgia: the file is served to every browser, including old
ones on old phones, and the smallest JavaScript that runs everywhere is
still the safest thing to hand a reader who has not updated their phone in
four years.

**The page works without it.** Everything the script does is
progressive enhancement. The seven day panels and the seven hourly strips
are rendered by the server, for every day, and the script only decides
which of them is showing - so the page says something useful with no
script at all, which is today's panel, because the week starts on today.
The button that picks a day is built by the script, not by the markup, so
a reader without JavaScript is never handed a button that cannot work.

**The preferences live in `localStorage`.** The saved city and the
personal alert threshold are in the browser, and the server is stateless:
it never sees either value, and a first-time visitor sees exactly the page
a returning one does. Every `localStorage` access goes through a
try/except, because a browser in private mode throws on the first access.

### The service worker

**What it is for.** The app can be installed on a phone, and it opens
without a network.

**Two rules run through all of it.**

1. **The forecast is never cached.** A rain chance from yesterday is
   wrong. A navigation is network-first and bypasses the browser's own
   cache as well, `/api/` is never intercepted at all, `/calendar.ics` is
   skipped for the same reason, and `/` is deliberately absent from the
   shell list - there is a test that asserts it.
2. **The shell is cached.** The stylesheet, the script, the icons, the font
   and the background photo: the files that make the page *look* like Rain
   Alert, and nothing that carries data. So an installed app opens without
   a network and shows `static/offline.html` instead of the browser's
   error screen.

**Served from the root.** `/service-worker.js` and `/manifest.json` are
served by two thin routes in `rainalert/web/site.py`, so the worker's scope
and the manifest's scope are the whole site rather than `/static/`. A
worker's scope is the path it is served from.

**`CACHE_VERSION` has to be bumped** when the shell changes. The old
caches are dropped when the new worker takes over, and the shell is
refreshed in the background, so a reader gets the new files on the load
after the one that fetched them. Without the bump, a changed `style.css`
keeps being served from the cache.

### Self-hosted everything

**Archivo** (`static/fonts/archivo-latin.woff2`, the Latin subset of a
variable face) is self-hosted under the SIL Open Font License. The page
asks no third party for anything and still works with no network.

**The icons and the social card are generated, not sourced.** `tools/`
renders them from the same brand mark with headless Chrome; the PNGs are
committed, so nothing in the build, the image or the test suite has to run
the generators.

**No third-party JavaScript at all.** No analytics, no fonts from a CDN,
no embeddable widgets, no consent banner - because there is nothing to
consent to.

---

## The data sources

Two free, keyless APIs. Neither needs a signup, and neither needs an API
key, which is why the app has no accounts and no secrets to manage.

### Nominatim (OpenStreetMap)

A city name to coordinates. `https://nominatim.openstreetmap.org/`,
through geopy.

- **Rate-limited**, which is why the results are cached.
- **Needs a user agent**, which is why it is configuration.
- **Data under the ODbL**; the footer credits the OpenStreetMap
  contributors, and there is a test that says so.

### OpenWeather One Call 4.0 (the second source)

Used only when Open-Meteo refuses a request, and only with
`OPENWEATHER_API_KEY` set. The answer is translated into Open-Meteo's shape
in `rainalert/upstream/openweather.py`, so nothing above it knows which
service a forecast came from. 4.0 has an endpoint for each timeline
(`/timeline/1day` and `/timeline/1h`, at most 10 and 20 records a call), so a
forecast is two calls; the current hour comes from the clock and the offset
every answer carries. Free to 1,000 calls a day, billed beyond it, so the app
counts its calls and stops at `OPENWEATHER_DAILY_LIMIT`.

### Open-Meteo (CC BY 4.0)

The forecast for a pair of coordinates.
`https://api.open-meteo.com/v1/forecast`.

- **One request per page load.** The daily fields, the hourly rain chance
  and the current hour all come in the same call.
- **`timezone=auto`** is deliberate. The API returns each date in the
  queried city's local time, so a forecast for Tokyo is dated in Tokyo's
  days. The app never converts these to the viewer's timezone - that would
  be a bug.
- **The service converts the temperatures, not the app.** The request
  carries `temperature_unit` and the values come back in that scale. A
  hand-rolled conversion rounds differently from the service's, and the
  two would disagree on the same day.
- **The free tier is non-commercial.** Voluntary one-off donations are
  allowed; advertising, affiliate promotions, subscriptions and paid tiers
  are not, and would need a paid Open-Meteo plan. The licence also
  requires attribution, which the footer carries.

---

## The infrastructure

The whole chain below is written and committed, and the parts of it that
can be exercised without a release have been. **None of the release half
has ever run**: no `v*` tag has been pushed, so the image has never been
pushed to Docker Hub and Render has never been told to deploy one. The
domain is still on Namecheap's URL forwarding. `DEPLOY.md` is the runbook
and says exactly where that stands.

### Docker, two stages

The build stage compiles the dependency wheels; the runtime stage installs
from those wheels and never sees a compiler.

**The runtime image installs no system packages.** The weekday names are
hard-coded in the app rather than read from the C library's locale data,
so there is no locale to compile and nothing to install. That is also why
the app never reads the browser's `Accept-Language` header: the whole page
is English, and a half-translated date inside it would be worse than a
consistently English one.

**It runs as a non-root user**, `rainalert` (uid 1001). The application
needs no write access anywhere: no database, no uploads, no instance
folder.

**The container's clock is UTC**, on purpose. The forecast's dates and
hours come from the API in the city's own time, so the container's clock
is only ever the server's own clock - the log stamps and the `lastmod` the
sitemap reports. UTC is the honest answer for both.

**The test suites go into the image** (`tests/offline/` and
`tests/test_api.py`), so `docker compose run --rm tests` exercises
exactly the image that gets deployed. The browser suite is deliberately
left out (`.dockerignore` excludes it): it drives a real headless Chrome,
and the image installs no system packages on purpose.

### Render, on a prebuilt image

`render.yaml` uses `runtime: image` pointing at a tag on Docker Hub.
Render pulls that image; it never runs the Dockerfile. A release is
therefore a pushed image tag, not a merged commit.

**Auto-deploy is off** (`autoDeploy: false`). A new tag on Docker Hub is
not enough on its own; the deploy hook has to be called with an `imgURL`
parameter naming the tag. Left on, auto-deploy would redeploy the service
with the stored default image - the fallback tag - as soon as any image
was pushed, which is how an old version comes back.

**The health check is the home page.** The app has no separate health
endpoint: its home page is the app's own page, and a 200 from it means
the server is up and serving.

### GitHub Actions

One workflow, `.github/workflows/ci-cd.yml`:

- **Every pull request and every push to `main`** builds the image for
  `linux/amd64` and runs the offline suite **inside the image**, so that
  what is tested is exactly what will be shipped. The image that passes
  the tests is the image that is pushed - it is not rebuilt for the push.
- **The browser suite runs on the runner**, not in the image, because the
  image installs no system packages. It sits before the push, so a failing
  browser test means the image is never pushed at all. The runner's own
  Python is 3.12 (it is the runner's, not the image's 3.14), so the suite
  is also the check that the code runs on an older interpreter.
- **A `v*` tag** builds, tests, pushes to Docker Hub as the version without
  the `v`, and calls Render's deploy hook with that exact tag. Pull
  requests never push and never deploy, so the secrets are only touched on
  a tag run.
- **The smoke test greps the live page for `Version <tag>`.** The footer
  of every page carries the version of the build that answered it, so the
  test can tell "the site is up" from "the new build is up". It retries
  twelve times, because Render needs a moment to swap the container over.
  It will fail on the first tag run, while the domain is still on
  Namecheap's forwarding - so the first release ends red even when the
  deploy itself worked.

### Dependabot

Weekly, Monday 07:00 Berlin, in three groups: the GitHub Actions, the
pinned pip packages, and the `python:3.14-slim` base image. Every PR it
opens runs the pipeline, so a bump only merges if it passes.

---

## The tests

### unittest, from the standard library

**Why not pytest.** It would be a dependency, and the suite does not need
one: `unittest` has discovery, `subTest` for the table-driven cases, and
shared setup through `setUp` and a common base class - and it is what the
CI image and the Docker image already have. `pytest` is not installed and
the suite does not miss it.

**Three suites, three jobs.**

| Suite | Count | Needs | What it is for |
|---|---|---|---|
| `tests/offline/` | 369 | nothing | The gate. HTTP fully mocked. |
| `tests/test_browser.py` | 80 | Chrome, selenium | The real page in a real browser. |
| `tests/test_api.py` | 7 | the two live APIs | That the upstreams still answer. |

**The offline suite is the one that gates changes.** It mocks both
upstreams and runs in about three seconds, with no network and no browser.

**The browser suite skips itself** when selenium or Chrome is missing, so a
plain `python -m unittest` never fails because of it. But a skipped suite
is not a passing suite, so `RAINALERT_REQUIRE_BROWSER=1` turns a missing
browser into a failure in CI.

**The browser suite drives a real headless Chrome**, not a DOM emulator,
because the things it checks are layout: that the page fits a 768-pixel
window with no scrollbar, that the value row's twenty-four numbers do not
collide, that the current-hour label does not stick out of the card. It
sets the viewport with `Emulation.setDeviceMetricsOverride`, because a
`set_window_size` in headless Chrome measures the wrong page - it
includes the browser's own chrome.

**A test lives with the module it tests**, in `tests/offline/`, and imports
that module directly. It patches a name where it is defined:
`rainalert.config`, `geocoding.geolocator`, `requests.get`.

**The snapshot is the check for a refactor.** `tools/snapshot.py` saves
what every route answers, with both upstreams mocked, so a change that
must not change what the site serves can be checked with `diff -r` before
and after.

---

## The local toolchain

Six scripts in `tools/`. Five of them drive a real headless Chrome and so
need selenium; `snapshot.py` needs only the app's own dependencies.

| Tool | What it does |
|---|---|
| `tools/shoot.py` | Screenshots a page of the running app, for looking at the design. |
| `tools/crop.py` | Screenshots one element, for looking at a detail. |
| `tools/measure.py` | Measures the page in a real browser: the vertical budget and the boxes. |
| `tools/snapshot.py` | Saves what every route answers, for `diff -r` before and after a refactor. |
| `tools/make_icons.py` | Regenerates the install icons from the brand mark. |
| `tools/make_og_image.py` | Regenerates the social card. |

The last two need Chrome and selenium, and what they write is committed,
so nothing in the build, the image or the test suite has to run them.

**No linter and no formatter is configured.** There is no `ruff`,
`flake8` or `black` in the workflow. The code follows the surrounding
style, and the suite is the gate.

---

## What is deliberately not here

Listing these is the point of the file, because each one is a decision
rather than an omission.

- **No database.** The app has no user data to store. The saved city and
  the personal threshold live in the reader's browser, and the server
  stays stateless.
- **No user accounts and no authentication.** There is nothing to log in
  to, and no session to keep.
- **No ORM and no SQL.** There is no schema to migrate.
- **No secrets to manage.** Both upstream APIs are keyless. The only
  credentials in the whole project are the Docker Hub token and the Render
  deploy hook, and they are GitHub Actions secrets used at release time.
- **No JavaScript build step and no `package.json`.** No npm, no bundler,
  no transpiler, no `node_modules`.
- **No CSS framework and no preprocessor.**
- **No third-party requests at runtime.** No CDN, no analytics, no
  embedded widget, no consent banner. The page asks nobody for anything.
- **No locale data and no i18n framework.** The UI is English and the
  weekday names are hard-coded, so the container image installs no system
  packages at all.
- **No database service in `docker-compose.yml`.** The app is stateless,
  so there is nothing to run beside it.
- **No background scheduler or push server.** The notification works while
  the tab is open, and the calendar export hands the alerting to software
  the reader already has.
- **No paid services.** Everything in the stack is free, and the two that
  are rate-limited are cached and used politely.
