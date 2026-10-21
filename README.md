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
- **Visual rain severity.** Each day is colour-coded on a three-band scale —
  grey for *rain unlikely*, blue for *rain possible*, amber for *rain likely* —
  with a matching dot, tinted row, and left border. A ☔ icon marks the days
  worth carrying an umbrella.
- **Localised weekday names.** Dates render as `Wednesday 21.10.2026`, with the
  weekday in the visitor's language. 44 languages and 23 regional variants are
  supported, and the day names come from the C library's locale data rather
  than a heavyweight dependency. Which languages are actually available
  depends on the locales installed on the host — an unavailable one falls
  back to English.
- **Honest error handling.** A city that does not exist and a geocoder that is
  temporarily down produce different messages — a network blip never tells a
  user their valid city is missing.
- **No build step, no bundler, no database.** Five Python dependencies, all
  pinned.

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
python -m unittest test_app    # 51 offline tests, no network required
python -m unittest test_api     # 4 live integration tests, hits both APIs
```

`test_app.py` is the suite that gates changes. It mocks both HTTP services
at the `requests` boundary, so it runs in under a second and never fails
because an upstream is down.

`test_api.py` checks the real response shapes against the live services and
needs them to be reachable.

---

## Configuration

Everything is optional — the defaults work. Set values in the environment or
in a `.env` file (the app loads one via `python-dotenv`).

| Variable | Default | What it does |
|---|---|---|
| `FLASK_DEBUG` | unset | `1`, `true` or `yes` enables the reloader and debugger |
| `DATE_LOCALE` | `de_DE` | Locale for weekday names. A fixed code (`de_DE`, `fr_FR`, `pt_BR`) or `auto` to follow the browser's `Accept-Language` header |
| `NOMINATIM_USER_AGENT` | `RainAlert_App_v1_2026` | Identifies the app to Nominatim, whose usage policy asks callers to do so |
| `GEOCODER_TIMEOUT` | `10` | Seconds to wait for a geocoding response |
| `WEATHER_TIMEOUT` | `10` | Seconds to wait for a forecast response |
| `SEVERITY_LOW_MAX` | `30` | Rain chance below which a day is banded *low* |
| `SEVERITY_MODERATE_MAX` | `60` | Rain chance below which a day is banded *moderate* |
| `UMBRELLA_THRESHOLD` | `50` | Rain chance at or above which the ☔ icon appears |

Example `.env`:

```dotenv
DATE_LOCALE=auto
SEVERITY_LOW_MAX=25
UMBRELLA_THRESHOLD=40
```

> This repository has no `.gitignore`. If you create a `.env`, keep it out of
> version control — add `.env` to a `.gitignore` before your first commit.

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
│       └── rain-alert-bg.jpg    # background photo
├── docs/
│   └── screenshot.png           # the image above
├── test_app.py                  # offline unit tests, HTTP fully mocked
├── test_api.py                  # live integration tests
├── requirements.txt             # pinned dependencies
├── render.yaml                  # Render deployment blueprint
├── CLAUDE.md                    # notes for AI assistants working in this repo
└── RainAlert-Ideas-for-Alerting-Users.md
```

`app.py` holds the entire application — routes, geocoding, forecast fetching,
formatting and localisation — in about 390 lines. There is no package
structure to navigate; a single module is the right size for an app this
small.

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

### Localisation

`weekday_names(locale)` returns all seven weekday names, Monday first, using
the C library's locale data. `strftime('%A')` reads the process-wide `LC_TIME`
locale, so the locale is switched only while the names are read and the
previous value is always restored in a `finally` block. The result is cached,
so the switch happens once per locale rather than once per rendered row.

An unavailable locale falls back to English with a logged warning rather than
raising.

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

`render.yaml` describes a free-tier [Render](https://render.com) web service:

```yaml
startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
```

Nothing deploys until the repository is connected to Render and the Blueprint
is created there; `autoDeployTrigger` is off, so pushes do not deploy on their
own.

For any other host, the app is a standard WSGI application:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

gunicorn is a Unix server and will not run on Windows. It is in
`requirements.txt` because the deployment targets are Linux; for local
development on Windows, use `python app.py`.

### Before deploying anywhere

- **Set `DATE_LOCALE=auto`** so each visitor gets weekday names in their own
  language.
- **Set a real `NOMINATIM_USER_AGENT`** identifying your deployment. The
  default identifies the development copy.
- The built-in Flask server is for development only. Use gunicorn or
  equivalent in production.

---

## Notes for contributors

- **Styling lives in `static/style.css` as classes.** No inline `style`
  attributes in the template.
- **User-facing error messages are plain English sentences ending in a
  period.** The UI text is English even when weekday names are localised.
- **Log with `app.logger`, never `print()`.**
- **Restart the server after editing `index.html`.** Jinja caches templates
  when debug mode is off.
- **`round()` is not what you want for temperatures.** Python uses banker's
  rounding, so `round(8.5)` is `8`. Use the `round_half_up()` helper.
- **Never call `.title()` on user input.**

`CLAUDE.md` in this repository documents the architecture, the design
decisions behind each of these, and the gotchas that have bitten this
codebase before.

---

## License

Copyright © 2026 Vedad Dizdarevic. All rights reserved.

The favicon is original to this project. The background photograph in
`static/image/rain-alert-bg.jpg` is a third-party asset — it carries no
embedded attribution, and its origin is not recorded anywhere in this
repository. If you plan to publish or redistribute this app, confirm where
that image came from and its licence, and either record it here or replace
it with one you have the right to use.
