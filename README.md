# Rain Alert 🌧️

A small Flask web app that shows the 7-day rain chance for any city, colour-coded
by how wet each day is expected to be.

Type a city name → the app geocodes it to coordinates via
**[Nominatim](https://nominatim.org/)** (OpenStreetMap) → fetches a 7-day
forecast from **[Open-Meteo](https://open-meteo.com/)** → renders a list of
daily rain chances with a visual severity scale.

Both APIs are free, keyless, and need no signup. There is no database, no
user accounts, and nothing to configure before running it.

![Rain Alert showing a 7-day forecast for London](docs/screenshot.png)

---

## Features

- **Seven-day forecast** for any city the geocoder recognises, with the daily
  maximum rain probability and the high/low temperature.
- **A one-line headline** above the list says what the week looks like: "Rain
  likely tomorrow (80%). Bring an umbrella." or "No rain likely for the next
  7 days." It names the first day worth mentioning, and today's figure comes
  from the hours that are left rather than from a day maximum that includes
  the morning.
- **Hour-by-hour strip for today.** One bar per hour of the city's local day,
  coloured on the same scale as the daily list, with a pulsing dot on the
  current hour. A one-line summary says when the rain is expected — "Rain
  likely from about 15:00 to 16:00, up to 83%. Bring an umbrella." — so you
  can tell whether to leave now or in an hour, which a daily maximum cannot.
- **Visual rain severity.** Each day is colour-coded on a three-band scale —
  grey for *rain unlikely*, blue for *rain possible*, amber for *rain likely* —
  with a matching dot, tinted row, and left border. A ☔ icon marks the days
  worth carrying an umbrella.
- **Celsius or Fahrenheit.** A small switch at the right end of the colour key
  switches the temperatures. The forecast service does the conversion, so the
  numbers are the service's own and the choice sticks when you search for
  another city.
- **English weekday names.** Dates render as `Wednesday 21.10.2026`. The page
  is English throughout, so a German date inside it would be a half-translated
  page; the seven names are hard-coded rather than taken from the C library's
  locale data, so they never depend on the host.
- **Honest error handling.** A city that does not exist and a geocoder that is
  temporarily down produce different messages — a network blip never tells a
  user their valid city is missing.
- **No build step, no bundler, no database.** Five Python dependencies, all
  pinned. A container image is included if you would rather not set up a
  Python environment.

---

## Quick start

```bash
git clone https://github.com/lasiurusbat/RainAlert.git
cd RainAlert
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>.

Python 3.10 or newer is required. The app was developed and tested on
Python 3.14.5.

---

## Running the tests

```bash
python -m unittest test_app    # 146 offline tests, no network required
python -m unittest test_api     # 6 live integration tests, hits both APIs
```

`test_app.py` is the suite that gates changes. It mocks both HTTP services
at the `requests` boundary, so it runs in under a second and never fails
because an upstream is down.

`test_api.py` checks the real response shapes against the live services and
needs them to be reachable.

The offline suite needs nothing from the host beyond Python itself: the
weekday names are hard-coded, so there is no locale to install.

---

## Running with Docker

If you would rather not manage a Python environment, the repository ships a
`Dockerfile` and a `docker-compose.yml`. The image contains the app and its
dependencies.

### With Compose (recommended)

```bash
docker compose up --build       # start the app on http://localhost:8000
docker compose down             # stop and remove the container
```

The Compose file builds the image once and shares it between two services:

- `rainalert` — the app, published on <http://localhost:8000>.
- `tests` — a one-shot service that runs both test suites in the same image.
  It is behind a profile, so it does not start with `up`:

  ```bash
  docker compose run --rm tests
  ```

  The `tests` service runs the live integration suite too, which needs
  Nominatim and Open-Meteo to be reachable from the container.

### With plain Docker

```bash
docker build -t rainalert .
docker run --rm -p 8000:8000 rainalert
```

### Configuration

The container reads the same environment variables as a local run. Pass them
with `-e`, or put them in a `.env` file next to the Compose file — Compose
picks that file up automatically.

```bash
docker run --rm -p 8000:8000 \
  -e NOMINATIM_USER_AGENT="RainAlert/1.0 (https://rainalert.live)" \
  -e DONATION_URL=https://buymeacoffee.com/rainalert \
  rainalert
```

With plain Docker, `--env-file .env` passes every variable in your `.env` file
to the container at once. The image never contains the file itself:
`.dockerignore` keeps it out of the build.

In Compose, only the variables listed under `environment:` in
`docker-compose.yml` reach the container. `DONATION_URL` is listed and is read
from your `.env` file or your shell, so putting it in `.env` is enough.

The port mapping is `host:container`. The container listens on `8000`; change
the host side if `8000` is already taken.

### What is in the image

- **Two stages.** The build stage compiles the dependency wheels; the runtime
  stage installs from those wheels and carries no compiler.
- **A non-root user.** The app runs as `rainalert` (uid 1001) and needs no
  write access anywhere.
- **No system packages.** The image installs nothing beyond the Python
  dependencies: the weekday names are hard-coded, so there is no locale data
  to compile.
- **gunicorn**, bound to `0.0.0.0:8000` with one worker and four threads.
  One worker keeps the geocoding cache warm and avoids duplicate Nominatim
  lookups, since the app is I/O-bound on two keyless APIs.

The image carries the test suites as well, so
`docker run --rm rainalert python -m unittest test_app` runs the same tests
against the same image that gets deployed.

---

## Configuration

Everything is optional — the defaults work. Set values in the environment or
in a `.env` file (the app loads one via `python-dotenv`).

| Variable | Default | What it does |
|---|---|---|
| `FLASK_DEBUG` | unset | `1`, `true` or `yes` enables the reloader and debugger |
| `NOMINATIM_USER_AGENT` | `RainAlert_App_v1_2026` | Identifies the app to Nominatim, whose usage policy asks callers to do so |
| `GEOCODER_TIMEOUT` | `10` | Seconds to wait for a geocoding response |
| `WEATHER_TIMEOUT` | `10` | Seconds to wait for a forecast response |
| `SEVERITY_LOW_MAX` | `30` | Rain chance below which a day is banded *low* |
| `SEVERITY_MODERATE_MAX` | `60` | Rain chance below which a day is banded *moderate* |
| `UMBRELLA_THRESHOLD` | `50` | Rain chance at or above which the ☔ icon appears |
| `TEMPERATURE_UNIT` | `celsius` | The scale the temperatures are shown in: `celsius` or `fahrenheit`. The reader can switch on the page, and their choice wins over this default |
| `DONATION_URL` | empty | An `https://` link to a donation page. When set, a short "Buy me a coffee" line appears under the search button and in the footer. When empty, nothing renders. Anything that is not an absolute `https://` URL is ignored. See [Donations and data credits](#donations-and-data-credits) |

Example `.env`:

```dotenv
SEVERITY_LOW_MAX=25
UMBRELLA_THRESHOLD=40
```

> `.env` is already in `.gitignore`, so a local one stays out of version
> control. `.env.example` is not ignored, if you want to ship a template.

---

## The headline banner

One line above the list says what the week looks like: the first day worth
mentioning, and what to do about it.

| Situation | The banner says |
|---|---|
| A day at or above the umbrella threshold | "Rain likely tomorrow (80%). Bring an umbrella." |
| A day that is only possible | "Rain possible on Thursday (45%)." |
| A quiet week | "No rain likely for the next 7 days." |
| A quiet week with a day the API did not report | "No rain likely for most of the next 7 days." |
| Nothing reported at all | "Rain chance unknown for the next 7 days." |

Three details are deliberate:

- **The band in the sentence is the day's own band**, the same one its row
  in the list carries, so the banner and the list never disagree about how
  wet a day is. The colour follows the band, and the band name is in the
  text, so the meaning never rests on the colour alone.
- **Today is judged on the hours that are left.** The daily maximum covers
  the whole day, so at 18:00 it still counts the morning's downpour while
  the reader can only walk into the evening. Today's figure in the banner
  comes from the hours ahead and says so — "Rain likely for the rest of
  today (80%)" — while its row in the list keeps the daily maximum. The two
  are different quantities, and each is labelled with which one it is. When
  the day is over it drops out of the banner entirely.
- **A missing value is never counted as dry.** A week where one day was not
  reported is "most of", not "all of".

---

## The severity scale

The bands are computed from the daily maximum precipitation probability.

| Band | Chance | Colour | Label |
|---|---|---|---|
| Low | below 30% | grey | Rain unlikely |
| Moderate | 30–60% | blue | Rain possible |
| High | above 60% | amber | Rain likely |
| Unknown | no value reported | grey | Unknown |

Two details are deliberate:

- **The labels are a scale, not absolute claims.** A 25% day is not "dry" —
  it is just unlikely to be wet. A probability also says nothing about
  *intensity*, so the app never tells you a day will be "light" or "heavy".
- **A missing value is not zero.** When the API reports no probability, the
  day is banded *unknown* rather than being silently treated as dry.

The colour key is rendered once above the list, and every row also carries its
band name in a screen-reader-only span, so severity is never communicated by
colour alone.

---

## The daily list

```
● Rain unlikely  ● Rain possible  ● Rain likely    Rain chance    [°C][°F]

● Wednesday 21.10.2026                       ☔ 100%    12° / 9°
● Thursday 22.10.2026                            86%    14° / 8°
● Friday 23.10.2026                             37%    11° / 7°
```

The row says each thing once:

- **"Chance of rain" appears once, in the column heading.** Repeating the
  phrase on all seven rows said nothing after the first one and made the
  list hard to scan, so the rows carry the number alone. The heading sits in
  the colour-key row above the list, which costs no extra height — the card
  is already at its vertical limit.
- **The temperature is its own column**, without the parentheses it used to
  wear, and the °C/°F switch doubles as that column's heading.
- **The ☔ icon sits inside the chance column**, so the digits' right edge is
  the same on every row and the column reads as a column.

The two columns are fixed-width and the date takes the slack, so the numbers
line up down the list. Screen readers still get the full wording — the
visible number is hidden from them, and a screen-reader-only span beside it
says "100% chance of rain. Take an umbrella."

Below 560px the three of them no longer fit on one line, so the date takes
a line of its own and the two columns share the line below it, both
right-aligned. The headings do the same, so they still sit over their
columns.

The hourly table underneath has a real column heading, so its cells are bare
numbers too. Its tooltips keep the full phrase, because a tooltip stands on
its own.

---

## The hourly strip

The strip above the daily list shows one bar per hour of the city's local
day, with the bar height giving the rain chance and the bar colour giving
the same severity band the daily list uses.

Four things about it are deliberate:

- **The hours are the city's local hours.** The forecast is requested with
  `timezone=auto`, so the API dates the hours in the queried location's local
  time — a forecast for Tokyo is timed in Tokyo's hours. They are never
  converted to the viewer's timezone, exactly like the daily dates.
- **The current hour is marked with a pulsing dot**, taken from the `current`
  block the API returns in the same local time. Without that block the app
  falls back to the UTC offset, and without that too it simply omits the
  marker. The pulse is dropped for anyone who has asked for less motion;
  the dot stays.
- **The bar height is bucketed into 5% steps** so that it can live in the
  stylesheet as a class. The exact percentage is in the tooltip and in the
  table view underneath, so the rounding never hides a value.
- **Every value is reachable without hovering.** The "Hourly values" table
  lists the rain chance for every hour; the tooltip only makes it easier to
  read.

The summary sentence above the strip uses the umbrella threshold, so it
agrees with the ☔ icon on the daily list, and it only looks at hours that
have not happened yet — a window that has already passed is not an alert.

---

## Donations and data credits

**Donation link.** Set `DONATION_URL` to your donation page (the live site uses
<https://buymeacoffee.com/rainalert>) and the page shows one quiet line just
under the "Check Rain Chance" button, plus a link in the footer. It is a plain
text link, not an embedded widget, so no third-party script is loaded and no
consent notice is needed. It opens in a new tab. It is a site-wide link, so it
appears on every page, including the error pages. With the variable empty, the
page is exactly as it was without the feature.

**Keep donations voluntary and one-off.** Open-Meteo's free API is for
non-commercial use. Its terms allow voluntary donations but treat advertising
and subscriptions as commercial. So the page behind the link should not sell
memberships, extras or recurring subscriptions. If you ever want ads, paid
features or promotions, you need one of Open-Meteo's paid plans first.

**Credits are required and always shown.** The footer credits Open-Meteo
(data under CC BY 4.0) and OpenStreetMap (place names come from Nominatim).
Do not remove them: the Open-Meteo licence requires attribution.

---

## Project layout

```
RainAlert/
├── app.py                       # the whole app: routes, geocoding, forecast, formatting
├── templates/
│   └── index.html               # the single page
├── static/
│   ├── style.css                # all styling
│   ├── favicon.svg              # tab icon
│   └── image/
│       └── rain-alert-bg.jpg    # background photo (privately owned, see License)
├── docs/
│   └── screenshot.png           # the image above
├── test_app.py                  # offline unit tests, HTTP fully mocked
├── test_api.py                  # live integration tests
├── requirements.txt             # pinned dependencies
├── Dockerfile                   # multi-stage container image
├── docker-compose.yml           # local container setup, app + test services
├── .dockerignore                # keeps the build context small
├── .gitignore                   # keeps local artefacts out of version control
├── render.yaml                  # Render deployment blueprint
├── .github/                     # CI workflow and Dependabot config
├── DEPLOY.md                    # the deployment runbook
├── CLAUDE.md                    # notes for AI assistants working in this repo
├── implementation-plan.md       # what is built, what is next, what is deferred
└── RainAlert-Ideas-for-Alerting-Users.md
```

`app.py` holds the entire application — routes, geocoding, forecast fetching
and formatting — in about 670 lines. There is no package structure to
navigate; a single module is the right size for an app this small.

---

## How it works

### Geocoding

`get_coordinates(city_name)` calls Nominatim with `exactly_one=True` and
returns `(latitude, longitude, display_name)`. Results are cached with
`functools.lru_cache`, because a city name always maps to the same place and
Nominatim is rate-limited. Failures are deliberately *not* cached, so a retry
after a timeout re-attempts the lookup instead of replaying the error.

The displayed city name comes from the geocoder's own `display_name`, not from
the user's input. Running the input through `.title()` would turn
`"st john's"` into `"St John'S"`.

### Forecast

`fetch_forecast()` requests `precipitation_probability_max`, `temperature_2m_max`
and `temperature_2m_min` with `timezone=auto`. The API then returns each date
already expressed in the queried city's local time — a forecast for Tokyo is
dated in Tokyo's days. Those dates are never converted to the viewer's
timezone, because that would be a bug, not a feature.

### Weekday names

The seven weekday names are hard-coded in `app.py`, Monday first, and
`format_date()` picks one by `date.weekday()`.

They are not taken from `strftime('%A')`, because that reads the process-wide
`LC_TIME` locale: on a German Windows machine, or in a container with `LANG`
set, it would render the weekday in that language. The rest of the page is
English — the interface text, the headline banner, the hourly summary and
every error message — so a half-translated date inside an English page would
be worse than a consistently English one.

The consequence is that the app no longer reads the browser's
`Accept-Language` header at all, and the image no longer needs any locale
data.

### Error handling

Three distinct exceptions separate the failure modes that matter:

| Exception | Meaning | Message shown |
|---|---|---|
| `CityNotFound` | The geocoder answered and had no match | "City not found. Please try a different name (e.g., 'Paris')." |
| `GeocodingUnavailable` | The geocoder was unreachable, rate-limited, or errored | "The geocoding service is unavailable right now. Please try again in a moment." |
| `WeatherUnavailable` | The forecast service was unreachable or returned junk | "The weather service is unavailable right now. Please try again in a moment." |

The first two must stay separate. Collapsing them into one "not found" path
means a network blip tells the user their city does not exist. Internal
exception text is always logged, never rendered on the page.

---

## Deployment

`render.yaml` describes a free-tier [Render](https://render.com) web service
that runs a prebuilt image from Docker Hub:

```yaml
runtime: image
image:
  url: docker.io/lasiurusbat/rainalert:0.8
```

Render pulls the image; it does not build the Dockerfile. Releases are cut by
building an image, pushing it with a new tag, and telling Render to deploy
that tag. The GitHub Actions workflow in `.github/workflows/ci-cd.yml` does
exactly that, and `DEPLOY.md` is the runbook for the one-time setup — Docker
Hub credentials, the Render deploy hook, and the release steps.

For any other host, the app is a standard WSGI application:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

gunicorn is a Unix server and will not run on Windows. It is in
`requirements.txt` because the deployment targets are Linux; for local
development on Windows, use `python app.py`. The container image uses the
same command.

### Before deploying anywhere

- **Set a real `NOMINATIM_USER_AGENT`** identifying your deployment. The
  default identifies the development copy.
- The built-in Flask server is for development only. Use gunicorn or
  equivalent in production.

---

## Notes for contributors

- **Styling lives in `static/style.css` as classes.** No inline `style`
  attributes in the template.
- **User-facing error messages are plain English sentences ending in a
  period.** The UI text is English, and so are the weekday names.
- **Log with `app.logger`, never `print()`.**
- **Restart the server after editing `index.html`.** Jinja caches templates
  when debug mode is off.
- **`round()` is not what you want for temperatures.** Python uses banker's
  rounding, so `round(8.5)` is `8`. Use the `round_half_up()` helper.
- **Never call `.title()` on user input.**
- **The background photograph is not yours to redistribute.** It is privately
  owned and covered by the restriction in the License section below. Replace
  it with an image you have the right to use, or get written approval
  first.

`CLAUDE.md` in this repository documents the architecture, the design
decisions behind each of these, and the gotchas that have bitten this
codebase before.

---

## License

Copyright © 2026 Vedad Dizdarevic. All rights reserved.

The favicon (`static/favicon.svg`) is original to this project.

**The background photograph is privately owned.** The image in
`static/image/rain-alert-bg.jpg` is a privately held work, not a
third-party or openly licensed asset. It may not be used, copied, modified,
redistributed or sublicensed by anyone other than the copyright holder
without prior written approval. This applies to forks, mirrors, Docker
images, redistributed copies of the app, and any derivative work that
includes the file.

If you want to publish, redistribute or build on this project, you need
permission for the photograph first. The practical options are to replace
`static/image/rain-alert-bg.jpg` with an image you have the right to use, or
to obtain written approval from the copyright holder. Everything else in the
repository — the code, the styles, the favicon and the documentation — is
covered by the copyright above.
