# RainAlert API reference

The HTTP surface of RainAlert: what the app serves, what it answers, and what
it sends upstream. There is one JSON endpoint, one calendar download, a handful
of HTML pages and two install-related files. Everything is keyless, there is no
authentication, no account and no database.

- **Base URL (local):** `http://127.0.0.1:5000`
- **Base URL (production):** `https://rainalert.live`
- **Machine-readable spec:** [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1)
- **Implementation:** the routes are in [`rainalert/web/`](rainalert/web/); [`app.py`](app.py) is the entry point

---

## Endpoints at a glance

| Method | Path | Content type | Purpose |
|---|---|---|---|
| `GET` | `/` | `text/html` | The start page. With a `city` it sends the reader on to that city's own page. |
| `POST` | `/` | `text/html` | The page, with the city taken from the form. |
| `GET` | `/city/{city_slug}` | `text/html` | One city's forecast, at that city's own address. |
| `GET` | `/cities` | `text/html` | The index of the cities that have a page of their own. |
| `GET` | `/release-notes` | `text/html` | What each release of the app brought. |
| `GET` | `/robots.txt` | `text/plain` | Where the crawlers may go, and where the sitemap is. |
| `GET` | `/sitemap.xml` | `application/xml` | The pages of the site, for the crawlers. |
| `GET` | `/BingSiteAuth.xml` | `application/xml` | Bing Webmaster Tools' site-ownership verification file. |
| `GET` | `/googlee75783b48c054b73.html` | `text/html` | Google Search Console's site-ownership verification file. |
| `GET` | `/api/alert` | `application/json` | The one thing worth interrupting the reader for. |
| `GET` | `/calendar.ics` | `text/calendar` | The rainy days as an importable calendar file. |
| `GET` | `/manifest.json` | `application/manifest+json` | The web app manifest, for installing the app. |
| `GET` | `/service-worker.js` | `application/javascript` | The service worker, served from the root so it covers the whole site. |
| `GET` | `/static/<path>` | varies | Stylesheet, script, icons, background photo, offline page. |

---

## Query parameters

Two parameters are shared by the three routes that take a city, so the page can
pass what it already knows.

### `city`

The name of the place to look up. Free text, sent to Nominatim as-is.

- **Required** on `/api/alert` and `/calendar.ics`; **optional** on `/` (a start
  page has no city).
- Leading and trailing whitespace is stripped. An empty value is treated as
  "no city given", not as a search for the empty string.
- The city is resolved to coordinates by **Nominatim**, and the page shows the
  geocoder's own label for the place, not the string that was typed. A city
  name always maps to the same place, so lookups are cached per process.

### `threshold`

The rain chance, in percent, at which the reader wants to be told.

- **Optional** everywhere it appears. When it is absent, empty or not a
  number, the app's own umbrella threshold (`UMBRELLA_THRESHOLD`, default
  **50**) is used and the answer says so.
- Valid range is `0`–`100`. A number outside the range is clamped into it
  (`999` → `100`).
- It is a *second* answer, not a second umbrella: the ☔ icon, the headline
  banner and the tab title always use the app's threshold. This one is the
  reader's own limit, and the responses name which of the two they are.

### `unit`

The temperature scale for the HTML page: `celsius` (default) or `fahrenheit`.
Anything unrecognised falls back to the default rather than failing the page.
The conversion is done by the forecast service, not by the app.

---

## `GET /` and `POST /` — the start page

The start page is the site itself: the search form, the saved city, and the
reader's own threshold. It has no city of its own, so it has no forecast on it.

**GET** takes `city` and `unit` from the query string. **POST** takes them
from the form body (`application/x-www-form-urlencoded`).

```bash
curl "http://127.0.0.1:5000/"
curl -X POST "http://127.0.0.1:5000/" -d "city=London" -d "unit=celsius"
```

### `GET /?city=<city>` is a `301`

A city has one address, and it is `/city/{city_slug}`. A `GET` that carries a city
is sent there for good:

```
$ curl -i "http://127.0.0.1:5000/?city=London"
HTTP/1.1 301 MOVED PERMANENTLY
Location: /city/london
```

The unit travels with it (`?unit=fahrenheit` becomes
`/city/london?unit=fahrenheit`), and the redirect is worked out **before** the
forecast is fetched, so the extra hop asks the server for no more than a
header.

A `POST` answers `200 OK` with the page itself. The page still names the
city's own address as its canonical one, so there is only ever one page for a
city whichever way it was asked for.

### What the page tells the browser

The server stays stateless, so the page carries what the browser half needs in
four attributes on `<body>`:

| Attribute | Values | Meaning |
|---|---|---|
| `data-autoload` | `1` / `0` | May this page load a remembered city by itself? Only the start page may. |
| `data-search` | `ok` / `error` / `none` | Was the last search worth remembering? |
| `data-city` | the city as typed | The city the forecast is for. |
| `data-unit` | `celsius` / `fahrenheit` | The temperature scale in use. |

The saved city and the personal threshold live in the browser's `localStorage`.
The server never sees either of them, so a first-time visitor and a returning
one get exactly the same page from the server.

---

## `GET /city/{city_slug}` — a city's page

The forecast for one city, at that city's own address. This is the page a
search engine indexes, and the one a reader can bookmark and share.

```bash
curl "http://127.0.0.1:5000/city/london"
curl "http://127.0.0.1:5000/city/london?unit=fahrenheit"
```

- The slug is the city's name with the accents folded away and everything that
  is not a letter or a digit turned into a dash: `Sao Paulo` → `sao-paulo`,
  `Zürich` → `zurich`. A curated list of cities maps its own slugs to their
  names, so `/city/new-york` looks up "New York".
- An address that is not the canonical one is a `301` to the canonical one:
  `/city/London` and `/city/london/` both end up at `/city/london`.
- A city the geocoder does not know is a **`404`**, and a page that says "not
  found" but answers `200` is a soft 404 that search engines treat as one.
- An upstream that is down is a **`503`**: the page is fine, the moment is not.

| Status | When |
|---|---|
| `200` | The forecast. |
| `301` | The address is not the canonical one. |
| `404` | The geocoder answered normally and had no match. |
| `503` | The geocoder or the forecast service is unreachable. |

### The page's own parts

The forecast rows are readable in the markup, if a consumer needs them:

- each day carries `data-chance="<whole number>"` — the same number the row
  displays, and the number a personal threshold is compared against. A day the
  service did not report has **no** `data-chance`, so it is never counted as
  dry and never marked as wet.
- each hour of today's strip carries `data-tip="<time> · <chance> · <band>"`.
- the calendar link carries `data-app-days="<count>"` — how many days the app's
  own threshold would put into a calendar. The browser uses it to decide
  whether the link is worth offering.

### The title, the description and the canonical link

Every page says three things about itself, and they are decided in one place,
`rainalert/present/seo.py`, so they cannot disagree:

- `<title>` — the alert, and the city it is about.
- `<meta name="description">` — the sentence a search result shows under the
  title, which is the headline the page itself shows.
- `<link rel="canonical">` — the page's own address, so that a search engine
  indexes the city's page and not the many ways of asking for the same
  forecast.

The `<title>` and the favicon are part of the forecast, not decoration. They
fire at the same threshold as the ☔ icon and the headline, so the tab, the
banner and the row can never disagree:

| Situation | `<title>` | Favicon |
|---|---|---|
| Rain expected | `Rain today in London - Rain Alert` / `Rain tomorrow in London - Rain Alert` / `Rain Thursday in London - Rain Alert` | `/static/favicon-rain.svg` |
| Dry or unreported week, on a city's page | `7-day rain chance for London - Rain Alert` | `/static/favicon.svg` |
| The start page | `Rain Alert - 7-day rain chance for any city` | `/static/favicon.svg` |

A page with an error on it carries `<meta name="robots" content="noindex,
follow">` — there is no forecast on it, and indexing it would fill the results
with pages that say nothing.

---

## `GET /cities` — the city index

The list of the cities that have a page of their own. It is the front door of
the crawlable part of the site: every city on it is one link away.

```bash
curl "http://127.0.0.1:5000/cities"
```

The list is short on purpose. Nominatim is rate-limited and every address on
this list is a forecast the app has to fetch, so the index names the cities
that are worth having a permanent page for and the start page's search form
covers the rest.

---

## `GET /release-notes` — what each release brought

The app's own history, newest first. The footer of every page links here,
after the version of the build that is answering.

```bash
curl "http://127.0.0.1:5000/release-notes"
```

The notes are written by hand, in `rainalert/data/releases.py`, the same way this document
is: they describe the app rather than being generated from it. Cutting a
release means adding an entry there, and the version on the top entry is the
one the build stamps into the footer, so the page and the footer never
disagree about which release is running.

Each release is a version, a name for it, and the features it brought. A
feature is a title and a paragraph, and both are rendered on the page.

The page is a page like any other: it has a title, a description, a
canonical link and a social card, and it is in the sitemap.

---

## `GET /robots.txt` and `GET /sitemap.xml`

The two files a crawler asks for.

`robots.txt` says where the crawlers may go:

```
User-agent: SemrushBot
Disallow: /

User-agent: *
Crawl-delay: 10
Allow: /
Disallow: /api/
Disallow: /calendar.ics

Sitemap: https://rainalert.live/sitemap.xml
```

`/api/` and `/calendar.ics` are kept out of the crawl: they are not pages,
and fetching either one costs two upstream requests. Every city page is an
upstream request too, and the free forecast service rate-limits by IP address,
so the crawl is slowed with `Crawl-delay` and SemrushBot, an SEO crawler that
brings no readers, is shut out.

`sitemap.xml` names the start page, the city index, the release notes and
every city's page, with today's date as the last modification — the forecast
on every one of those pages changes every day, so the date is today's every
time.

---

## `GET /api/alert` — the notification endpoint

The one JSON route. The page polls it every `NOTIFICATION_POLL_MINUTES`
(default **30**) while it is open, and it answers with **at most one event** —
the single thing worth interrupting the reader for.

The city comes from the page, so the reader never has to type it again.

```bash
curl "http://127.0.0.1:5000/api/alert?city=London"
curl "http://127.0.0.1:5000/api/alert?city=London&threshold=40"
```

### `200 OK`

```json
{
  "city": "Greater London",
  "now": "08:00",
  "threshold": 50,
  "personal_threshold": false,
  "lead_hours": 2,
  "poll_minutes": 30,
  "event": {
    "key": "hour:2026-10-21T10:00",
    "title": "Rain likely from 10:00",
    "body": "80% chance of rain in London at 10:00. Bring an umbrella."
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| `city` | string | The geocoder's label for the place, not the string that was sent. |
| `now` | string \| null | The city's local current hour, `HH:00`. `null` when the day has no hours left. |
| `threshold` | integer | The chance, in percent, that was used to decide the event. |
| `personal_threshold` | boolean | `true` when `threshold` is the reader's own, `false` when it is the app's advice. |
| `lead_hours` | integer | How far ahead a rain warning is worth sending (default **2**). |
| `poll_minutes` | integer | How often the browser should poll (default **30**). |
| `event` | object \| null | The one event worth showing, or `null` when there is nothing to say. |

### The event

| Field | Type | Meaning |
|---|---|---|
| `key` | string | The event's identity. The browser remembers the keys it has shown, so the same news is never announced twice, and two open tabs do not say it twice. `now:<YYYY-MM-DD>` for rain in the current hour, `hour:<YYYY-MM-DD>T<HH>:00` for rain that is coming. |
| `title` | string | The band and the time: `"Rain likely right now"`, `"Rain likely from 10:00"`. |
| `body` | string | The sentence under the title, naming the chance, the city and the threshold. |

The **band** in the title is the same three-band scale the daily list uses:
*Rain unlikely* / *Rain possible* / *Rain likely* (and *Unknown* for a chance
the service did not report).

The body says which threshold answered it. With the reader's own threshold:
`"80% chance of rain in London at 10:00. Above your 40% threshold."` With the
app's advice: `"80% chance of rain in London at 10:00. Bring an umbrella."`

### Errors

| Status | Body | When |
|---|---|---|
| `400` | `{"error": "Please enter a city name."}` | `city` is missing or empty. |
| `404` | `{"error": "City not found. Please try a different name (e.g., 'Paris')."}` | The geocoder answered normally and had no match. |
| `503` | `{"error": "The geocoding service is unavailable right now."}` | The geocoder was unreachable, rate-limited or errored. |
| `503` | `{"error": "The weather service is unavailable right now."}` | The forecast service was unreachable or returned junk. |

The `400` and `404` are different things on purpose: a network blip must not
tell a reader that their valid city does not exist.

> **Note.** This endpoint always fetches a fresh forecast — it is never
> cached, and the service worker never intercepts it. A rain chance from
> yesterday is wrong.

---

## `GET /calendar.ics` — the calendar export

The rainy days as a standard iCalendar file, for the reader's own calendar
app to import and to do the alerting with. It takes the same two parameters as
the alert endpoint: the city, and the reader's own threshold if they have set
one.

```bash
curl -OJ "http://127.0.0.1:5000/calendar.ics?city=London&threshold=40"
```

### `200 OK`

```
Content-Type: text/calendar; charset=utf-8
Content-Disposition: attachment; filename="rain-alert-london.ics"
Cache-Control: no-store
```

The body is an RFC 5545 calendar:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//RainAlert//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:Rain forecast - London
BEGIN:VEVENT
UID:rainalert-london-20261022@rainalert.live
DTSTAMP:20261022T074926Z
DTSTART;VALUE=DATE:20261022
DTEND;VALUE=DATE:20261023
SUMMARY:Rain likely - 100% chance of rain
DESCRIPTION:100% chance of rain in London on Thursday 22.10.2026.\nBring an
 umbrella.\nWeather data by Open-Meteo.com (CC BY 4.0).
END:VEVENT
END:VCALENDAR
```

- **One `VEVENT` per day that reaches the threshold**, and no event at all for
  a day the service did not report — an unknown chance is not a chance of
  anything.
- **All-day events.** The forecast is a daily maximum, so the file says which
  days are wet and the calendar app decides when to remind the reader.
  `DTEND` is the start of the next day, which is not part of the event.
- **The `UID` is derived from the city and the date**, so importing the file
  again updates the same events instead of adding a second copy of every one
  of them.
- **Text values are escaped** — a city name with a comma in it would otherwise
  split the value in two — and long lines are **folded at 75 octets** with a
  leading space, which is what the specification asks for. Lines end in CRLF.
- **The file is never cached.** It holds a forecast, so a copy of an old one
  would be a lie. The service worker skips this path as well, so an offline
  page can never be downloaded in its place.

### Errors

The export is a download, so there is no page to render: a failed request gets
a plain-text sentence and a status code.

| Status | Body | When |
|---|---|---|
| `400` | `Please enter a city name.` | `city` is missing or empty. |
| `404` | `City not found. Please try a different name (e.g., 'Paris').` | The geocoder had no match. |
| `503` | `The geocoding service is unavailable right now.` | The geocoder was unreachable. |
| `503` | `The weather service is unavailable right now.` | The forecast service was unreachable. |

---

## `GET /BingSiteAuth.xml`

The file Bing Webmaster Tools fetches to confirm who owns the site: a `<users>`
document holding the site's verification id. It answers at the root.

## `GET /googlee75783b48c054b73.html`

The file Google Search Console fetches to confirm who owns the site: one line,
`google-site-verification: googlee75783b48c054b73.html`. It has to answer at the
root under its own name, so it has a route of its own.

## `GET /manifest.json`

The web app manifest, served from the **root** so its scope is the whole site
rather than `/static/`.

```
Content-Type: application/manifest+json
Cache-Control: no-cache
```

It names the app, points `start_url` and `scope` at `/`, asks for
`display: standalone`, and carries the three icons a browser needs to offer
the install: 192 and 512 pixels, plus a maskable 512 for Android, which crops
its own icon to a shape and needs its safe zone kept clear.

`Cache-Control: no-cache` because the manifest names the icons and the colours
of the installed app, so a changed one has to reach the phone straight away.

## `GET /service-worker.js`

The service worker, also served from the **root** so that it covers the whole
site — a worker served from `/static/` would only control `/static/`.

```
Content-Type: application/javascript
Service-Worker-Allowed: /
Cache-Control: no-cache
```

`Service-Worker-Allowed: /` is belt and braces: the scope of a worker is its
own path unless the server widens it. `Cache-Control: no-cache` because a
worker that is cached is a worker that never updates.

The worker's two rules are the whole design:

- **The forecast is never cached.** A navigation goes to the network first and
  bypasses the browser's own cache as well, `/api/` is never intercepted at
  all, `/calendar.ics` is skipped for the same reason, and `/` is deliberately
  absent from the cached shell.
- **The shell is cached**, so an installed app opens without a network and
  shows `static/offline.html` instead of the browser's error screen. The shell
  is the stylesheet, the script, the icons and the background photo — the files
  that make the page *look* like Rain Alert, and nothing that carries data.

## `GET /static/<path>`

The stylesheet, the script, the install icons, the favicons, the background
photo and the offline page. Served by Flask's static handler with the usual
conditional-request headers (`ETag`, `Last-Modified`, `Range`).

---

## Status codes used by the app

| Code | Meaning |
|---|---|
| `200` | Success. A `POST` with a city that could not be found still answers `200` — the message is in the page, because a form that was submitted is not an HTTP error. |
| `301` | The address is not the canonical one: `/?city=London` and `/city/London` both go to `/city/london`. |
| `400` | The request is missing something it needs (no city). |
| `404` | The city is not one the geocoder knows — on a city's own page — or the address is not one of the site's. |
| `503` | An upstream service — the geocoder or the forecast service — is unreachable or is broken. |

---

## Configuration

The behaviour above is the default. These environment variables change it —
read at import, so they need a restart.

| Variable | Default | What it changes |
|---|---|---|
| `UMBRELLA_THRESHOLD` | `50` | The chance at which the ☔, the headline, the tab title and the favicon all fire. |
| `SEVERITY_LOW_MAX` | `30` | The upper bound of the *Rain unlikely* band. |
| `SEVERITY_MODERATE_MAX` | `60` | The upper bound of the *Rain possible* band. |
| `NOTIFICATION_POLL_MINUTES` | `30` | How often the page polls `/api/alert`; reported back as `poll_minutes`. |
| `NOTIFICATION_LEAD_HOURS` | `2` | How far ahead a rain warning is worth sending; reported back as `lead_hours`. |
| `TEMPERATURE_UNIT` | `celsius` | The default temperature scale. |
| `GEOCODER_TIMEOUT` | `10` | Seconds before the geocoder request is given up on. |
| `WEATHER_TIMEOUT` | `10` | Seconds before the forecast request is given up on. |
| `NOMINATIM_USER_AGENT` | `RainAlert_App_v1_2026` | The user agent sent to Nominatim, which its usage policy asks for. |
| `SITE_URL` | `https://rainalert.live` | The site's own address. The canonical link, the social card and the sitemap are built from it, so it has to be the address the site is really at. |
| `DONATION_URL` | *(empty)* | An absolute `https://` link to a donation page. Anything else is ignored and no link is rendered. |

---

## The upstream services

RainAlert is a client of two free, keyless APIs. It is worth writing down
exactly what it asks them for, because that is the part of the system that
can actually fail.

### Nominatim (OpenStreetMap)

The city name → coordinates lookup.

- **Endpoint:** `https://nominatim.org/search`
- **Library:** geopy's `Nominatim` geocoder, with `exactly_one=True` and a
  configurable user agent and timeout.
- **Returns:** the latitude, the longitude and the place's `display_name`. The
  page shows the first comma-separated part of that name.
- **Usage policy:** Nominatim asks callers to identify themselves and to keep
  the request rate down. The app identifies itself through
  `NOMINATIM_USER_AGENT` and caches every successful lookup per process, so a
  repeated search costs no request at all.
- **Licence:** place names © OpenStreetMap contributors. The footer credits
  them, and the credit is required.

### Open-Meteo

The forecast.

- **Endpoint:** `https://api.open-meteo.com/v1/forecast`
- **Parameters sent:**

  | Parameter | Value | Why |
  |---|---|---|
  | `latitude`, `longitude` | the geocoded coordinates | where to forecast for |
  | `daily` | `precipitation_probability_max,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_hours` | the seven-day list, and the rain that falls in each day |
  | `hourly` | `precipitation_probability` | today's hour-by-hour strip |
  | `current` | `precipitation_probability` | the current hour, in the city's local time |
  | `timezone` | `auto` | the dates come back in the **queried city's** local time |
  | `temperature_unit` | `celsius` or `fahrenheit` | the service does the conversion, not the app |

- **One request per page load** — the daily and the hourly fields come in the
  same call.
- **`timezone=auto` is deliberate.** A forecast for Tokyo is dated in Tokyo's
  days. Converting those dates to the reader's timezone would be a bug.
- **Licence:** the free plan is non-commercial. Voluntary one-off donations
  are allowed; advertising, affiliate promotions, subscriptions and paid tiers
  are not, and would need a paid Open-Meteo plan. The footer credits
  Open-Meteo (CC BY 4.0) and the credit is required.

---

## Deployment status

**The API is live** at `https://rainalert.live`. Every URL above can be
asked of that address — the API endpoints, the calendar export, and the
pages. `https://rainalert.live/api/alert?city=Berlin` answers with the
alert JSON, and the same paths on a local run answer the same way.

The app's own address is `https://rainalert.live/`, and `DEPLOY.md` is the
runbook.
