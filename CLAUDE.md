# RainAlert

A small Flask web app that shows the 7-day rain chance for any city.

Enter a city name → geocoded to coordinates via **Nominatim** (OpenStreetMap) →
7-day forecast from **Open-Meteo** → rendered as a list of daily rain chances.

Both APIs are free, keyless, and need no signup. There is no database and no
user account system.

**The app runs locally only.** Nothing is deployed: `rainalert.live` does not
serve this app, no release tag has ever been cut, and no image has been
pushed to Docker Hub. The deployment machinery is written and committed, but
it has never been run end to end. `DEPLOY.md` is the runbook, and the
"Still to do" section below is the list of what is actually ahead.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Serves on <http://127.0.0.1:5000>. `FLASK_DEBUG=1` enables the reloader and
debugger.

```bash
python -m unittest test_app    # offline suite, 183 tests, no network
python -m unittest test_browser  # browser suite, 17 tests, needs Chrome
python -m unittest test_api     # live integration tests, hits both APIs
```

The offline suite is the one that gates changes. `test_api.py` requires the
upstream services to be reachable. `test_browser.py` needs Chrome and
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
in the app, so there is no locale data to compile. `DEPLOY.md` is the
deployment runbook, and `.github/workflows/ci-cd.yml` runs the tests inside
the built image before any release is pushed.

## Deployment status

**The app is not live.** Checked on 2026-10-21, and every one of these is
still true:

- **No release tag exists.** `git tag -l` is empty. The workflow only pushes
  and deploys on a `v*` tag, so nothing has ever been released.
- **The Docker Hub image does not exist.** The repository
  `lasiurusbat/rainalert` is there, with **zero tags** — so the
  `docker.io/lasiurusbat/rainalert:0.8` that `render.yaml` points at cannot
  be pulled.
- **The Render service is not serving this app.** A service named
  `rainalert` answers at <https://rainalert.onrender.com>, but its `/`
  returns the JSON `{"message": "Rain Alert API is running", "status":
  "ok"}` behind gunicorn. This app's `/` renders the HTML page. It is a
  different, minimal service that happens to share the name.
- **`rainalert.live` points nowhere useful.** The domain is at Namecheap
  with URL forwarding: `rainalert.live` is an A record to a Namecheap
  forwarder that 302s to `www.rainalert.live`, whose own A record is
  `0.0.0.0`. No Render address appears in the DNS at all.
- **CI itself has run, and is green.** The workflow builds the image, runs
  the offline suite inside it and the browser suite on the runner. Only the
  tag-gated half — the push and the deploy — has never fired.

So the app is served by `python app.py` or `docker compose up`, and by
nothing else.

### Still to do

- [ ] Cut the first release tag (`git tag v0.8 && git push origin v0.8`),
      which builds, tests, pushes and deploys in one workflow run.
- [ ] Confirm the Docker Hub credentials and the Render deploy hook are set
      as GitHub secrets, and that the free Render plan includes a hook.
- [ ] Point the domain at Render: add `rainalert.live` to the service,
      then replace the Namecheap forwarding records with the DNS records
      Render gives, and verify HTTPS.
- [ ] Replace the `0.8` fallback in `render.yaml` if the first release is
      not `0.8`.
- [ ] Re-check the smoke test in the workflow: it only proves
      `https://rainalert.live/` answers, not that it answers with the new
      version. **It will fail on the first tag run** as long as the domain
      is still on Namecheap forwarding, so the first release ends red even
      when the deploy itself worked.

## Layout

| Path | Purpose |
|---|---|
| `app.py` | The whole app: routes, geocoding, forecast fetching, formatting |
| `templates/index.html` | Single page; inline styles are out, classes live in `style.css` |
| `static/style.css` | All styling |
| `static/app.js` | The browser half: saved city and personal alert threshold |
| `static/image/` | Background photo |
| `static/favicon.svg` | Tab icon |
| `static/favicon-rain.svg` | Tab icon when rain is coming |
| `test_app.py` | Offline unit tests, HTTP fully mocked |
| `test_browser.py` | Browser tests, real headless Chrome, no network |
| `test_api.py` | Live integration tests |
| `requirements-dev.txt` | Development-only dependencies (selenium) |
| `Dockerfile` | Two-stage container image |
| `docker-compose.yml` | Local container setup: the app and a test service |
| `render.yaml` | Render Blueprint; runs a prebuilt image, not a build (not deployed yet) |
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

**Weekday names are always English.** They are hard-coded in `WEEKDAY_NAMES`
(Monday first) and picked by `date.weekday()`, not taken from
`strftime("%A")` and not read from the C library's locale data. `strftime`
follows the process-wide `LC_TIME` locale, so on a German Windows machine, or
in a container with `LANG` set, it would render the weekday in that
language. The rest of the page is English, so a half-translated date inside
it would be worse than a consistently English one. The app therefore does
not read the browser's `Accept-Language` header at all, and the image needs
no locale data.

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

**The headline banner is one sentence above the list.** `forecast_headline()`
picks the first day worth mentioning: a day at or above `UMBRELLA_THRESHOLD`,
a day that is only *possible*, or the week as a whole. The band name in the
sentence is the day's own band — the same one its row in the list carries —
so the banner and the list never disagree. The colour follows the band and
the band name is in the text, so the meaning never rests on colour alone.

**Today is judged on the hours that are left, not on the daily maximum.**
The daily maximum covers the whole day, so at 18:00 it still counts the
morning's downpour while the reader can only walk into the evening. When
the hourly data is available, the banner's figure for today comes from the
remaining hours and says so — "Rain likely for the rest of today (80%)" —
while the row in the list keeps the daily maximum. The two are different
quantities and each is labelled with which one it is. When the day is over
it drops out of the banner entirely. A missing chance is never counted as
dry: a quiet week with one unreported day is "most of", not "all of".

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
cleared. The rain icon changes **shape** as well as colour — an amber square
with white streaks against a blue cloud — so the two are told apart at 16
pixels by the shape and not by the hue alone.

**The daily row says "chance of rain" once, in the column heading.** The
phrase used to be on all seven rows, where it carried nothing after the first
one. Now `format_rain_chance()` returns the bare number for the visible row
and `describe_rain_chance()` returns the full phrase for screen readers and
tooltips, and the wording itself lives in the `.severity-legend` row above
the list. That row already sat directly above the list and had free space on
it, so the heading costs **zero** vertical height — which matters, because
the card is at its vertical limit.

The two right-hand cells are **fixed-width columns** and the date takes the
slack (`flex: 1 1 auto`), with `justify-content: space-between` removed from
`.weather-item`. Without that, `space-between` distributed the free space
between the date and the number instead of pinning the number to a column,
and the percentages floated: their right edge came out at 358, 351, 342,
350, 345, 348 on six consecutive rows.

The legend row has to be **one flex row with the same two fixed-width
columns**, not a row of five loose items, or the headings drift away from
the columns they head. The three band names are wrapped in a
`.legend-bands` group so that the group takes the slack, exactly as the date
takes the slack in a data row.

The visible number is wrapped in `aria-hidden="true"` and a `.sr-only` span
carries "100% chance of rain. Take an umbrella." The heading is a `<span>`,
not a real table header, so the row itself has to say what the number means.
The hourly table below *does* have a real `<th scope="col">Rain chance</th>`,
so its cells can be bare numbers.

**The narrow layout is decided, not left to flexbox.** Below 560px the date,
the chance and the temperature do not fit on one line, and letting them
wrap where they liked gave a different layout on every row — a longer
weekday name pushed its own row over the line, and the columns drifted out
of alignment with the headings above them. The media query gives the date a
line of its own and puts both columns on the line below it, right-aligned,
and the legend row does the same, so the headings still line up.

**The donation link sits under the button, not under the forecast.** It is
on every page, including error pages, because it is a site-wide link rather
than part of the result. The band name in the headline is a sentence, not a
badge, and the ☔ icon in the list keeps its own meaning — one icon for one
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
`runtime: image` pointing at `docker.io/lasiurusbat/rainalert:0.8`. Render
pulls that image; it never runs the `Dockerfile`. A release is therefore a
pushed image tag, not a merged commit. The old `runtime: python` shape,
where Render ran `pip install` and gunicorn itself, is gone. None of this
has happened yet — the image does not exist and no tag has been cut. See
"Deployment status" above.

**CI runs the tests inside the built image.** `.github/workflows/ci-cd.yml`
builds for `linux/amd64` and runs `python -m unittest test_app` in the
container, so that what is tested is exactly what will be shipped. The image
that passes the tests is the image that is pushed — it is not rebuilt for the
push. The suite needs no locale data any more, so it would also pass on a
stock runner; the reason for running it in the image is that it tests the
shipped artefact, not the developer's machine.

**The browser suite runs on the runner, not in the image.** `test_browser.py`
drives a real headless Chrome, and the image installs no system packages on
purpose, so Chrome cannot be in it. The suite therefore runs as a step on
the GitHub runner, against the same source, **before** the push — so a
failing browser test means the image is never pushed at all. The offline
suite still runs in the image, because that one can be.

**Releases are git tags.** A tag matching `v0.9` or `v1.2.3`, pointing at a
commit already on `main`, builds and tests the image, pushes it to Docker
Hub as the version without the `v`, and calls Render's deploy hook with an
`imgURL` parameter naming that exact tag. Pull requests never push and never
deploy, so the secrets are only touched on a tag run. **No tag has been
pushed yet**, so the push-and-deploy half of the workflow has never run.

**The donation link is opt-in.** `DONATION_URL` is read once at import through
`clean_donation_url()`, which accepts only absolute `https://` URLs without
whitespace, quotes or angle brackets and returns `""` for anything else. A
context processor passes it to every template as `donation_url`, reading the
module global on each request so tests can patch `rainalert.DONATION_URL`.
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
page what kind of page it is, through three attributes on `<body>`:
`data-autoload` (may this page load a remembered city by itself?),
`data-search` (`ok`, `error` or `none` — was the last search worth
remembering?) and `data-city`. Without JavaScript neither control can do
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
larger and darker than the surrounding text (`0.78rem` at `#4a5a6a`, a
7:1 contrast ratio) so it reads as a control rather than as a caption.
The row costs 2px of the card's vertical budget, and the card still fits
a 768px window with no scrollbar.

**The threshold is compared against the number the page shows.** The row
carries `data-chance`, the same whole number `format_rain_chance()` renders,
so the threshold and the number on the page can never disagree. A day the
service did not report has no `data-chance` at all, so it is never counted
as a dry day and never marked as a wet one either.

**Every `localStorage` access goes through a try/except.** A browser in
private mode, or one where the reader has blocked site data, throws on the
first access. The helpers swallow that, so a browser that refuses to store
anything loses the feature instead of breaking the page.

## Gotchas

- **`strftime('%A')` follows the process locale**, which is why the weekday
  names are hard-coded in `WEEKDAY_NAMES` rather than read from
  `strftime`. On a German Windows machine, or in a container with `LANG`
  set, `strftime` would render the weekday in that language.
- **Banker's rounding.** Python's `round(8.5)` is `8`, not `9`. Use the
  `round_half_up()` helper for temperatures, where halves are common.
- **Do not use `.title()` on user input.** It turns `"st john's"` into
  `"St John'S"`. The app displays the geocoder's own `display_name` instead.
- **The CSS file once contained a literal `\n`** (backslash-n, not a
  newline) that silently swallowed the next declaration. If `background-size`
  ever stops applying, check for stray escape sequences in the raw bytes.
- **The browser suite needs Chrome and selenium, and skips without them.**
  `test_browser.py` is not in the image: the image installs no system
  packages, so there is no Chrome in it. It runs on the CI runner instead,
  where Chrome is already installed. Install the driver locally with
  `pip install -r requirements-dev.txt`. The suite skips itself when
  selenium or Chrome is missing, so a plain `python -m unittest` never
  fails because of it — but a skipped suite is not a passing suite, so
  check that it actually ran before trusting it.
- **Jinja caches templates when debug mode is off.** Restart the server after
  editing `index.html`, or run with `FLASK_DEBUG=1`.
- **A browser caches a favicon by its URL, not by its contents.** Rewriting
  `static/favicon.svg` in place changes nothing until the cache is cleared,
  so the rain icon is a **second file** with a second URL
  (`static/favicon-rain.svg`). If the icon ever stops swapping, look for a
  reused URL before suspecting the code.
- **The `<title>` and the icon are template variables, not static markup.**
  `index()` passes `page_title` and `favicon` to the template, so any route
  that renders `index.html` has to pass them too — otherwise the title
  renders empty and the icon URL breaks. There is one route today, and it
  keeps the plain "Rain Alert" title and the default icon whenever there is
  no forecast, which is the case for the empty page and for every error
  page.
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
  Severity must never be conveyed by colour alone. The same rule is why the
  "chance of rain" wording is a column heading rather than a per-row
  label, and why the two right-hand cells are fixed-width columns: the
  numbers have to line up, or the list reads as noise. Below 560px the rows
  wrap on purpose, and the wrap is the same on every row — a row that
  wrapped because its own weekday name was one letter longer would look
  broken.
- **The card has to stay inside a 748px-tall window.** The hourly strip
  added ~150px above the list, which pushed the document 25px past the
  viewport. The strip is 38px tall, the `.weather-item` padding was cut
  from `0.45rem` to `0.32rem`, and the h3 margin from `0.5rem` to
  `0.35rem` to claw the space back. Measure
  `scrollHeight - clientHeight` in a real browser after changing any of
  them — a stock GitHub runner has a different viewport than the
  developer box, and the CI image is where the tests run.
- **The headline banner is paid for out of the card's own padding.** It is
  21px tall, and the h1 margin, the `.container` padding, the `.result`
  margin and the `.hourly` padding were all trimmed to pay for it: the
  card was 718px and is now 696px, so the page fits a 768px window with
  no scrollbar. The levers, in the order they were used: `h1` margin
  (0.5rem/0.6rem), `.container` padding (`1.4rem 1.75rem`), `.result`
  margin-top (0.7rem) and padding-top (0.5rem), `.hourly` padding. The
  list rows themselves are already at their thinnest.
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
- **gunicorn 26 needs a writable home.** It opens a control socket at
  `$HOME/.gunicorn/gunicorn.ctl` (or `$XDG_RUNTIME_DIR/gunicorn.ctl`) and
  fails with "Permission denied" on a user created without `--create-home`.
  The image creates `/home/rainalert` and sets
  `XDG_RUNTIME_DIR=/run/rainalert`, both owned by uid 1001.
- **Render does not redeploy an image service when a new image appears.**
  A new tag on Docker Hub is not enough on its own; the deploy hook has to
  be called with the `imgURL` parameter naming the tag. See `DEPLOY.md`.
- **`rainalert.onrender.com` is not this app.** It answers with a JSON
  `{"message": "Rain Alert API is running", "status": "ok"}`; this app's `/`
  renders HTML. Do not read a 200 from that URL as "the site is up" — check
  for the HTML page, or a `Forecast for …` heading.
- **The domain is on Namecheap URL forwarding, not on Render.** The
  forwarding 302s to a `www` host whose A record is `0.0.0.0`, so the site
  does not answer at all. DNS has to be changed before the domain works,
  and the workflow's smoke test fails until it is.
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
  UI text is English, and so are the weekday names.
- **The tab title, the favicon, the ☔ icon and the banner are one alert.**
  They all read the same forecast and fire at the same `UMBRELLA_THRESHOLD`.
  Do not give any of them a threshold of its own — the moment two of them
  disagree, the page starts lying to the reader.
- **Do not bump the image tag in `render.yaml` by hand as part of a normal
  change.** Releases are cut by pushing a `v*` tag; the workflow derives the
  image tag from it. The tag in `render.yaml` is only the fallback for a
  manual deploy, and `DEPLOY.md` explains when to update it.
- **The test count appears in four documents** — `README.md`, `CLAUDE.md`,
  `DEPLOY.md` and `implementation-plan.md`. They drift. Update all four when
  tests are added.
