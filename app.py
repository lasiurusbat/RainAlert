"""RainAlert: look up the 7-day rain chance for any city.

Two free, keyless APIs are used:
  * Nominatim (OpenStreetMap) turns a city name into coordinates.
  * Open-Meteo returns the daily forecast for those coordinates.
"""

import os
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request
from geopy.exc import GeocoderQueryError, GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- Configuration -----------------------------------------------------------
# Nominatim's usage policy asks callers to identify themselves, so the user
# agent is configurable. The timeouts matter too: geopy defaults to a 1 second
# read timeout, which is short enough to fail on a healthy but slow service.
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "RainAlert_App_v1_2026")
GEOCODER_TIMEOUT = int(os.getenv("GEOCODER_TIMEOUT", "10"))
WEATHER_TIMEOUT = int(os.getenv("WEATHER_TIMEOUT", "10"))

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = "precipitation_probability_max,temperature_2m_max,temperature_2m_min"

# The hourly rain chance for today, and the same field for the current hour.
# Both come in the same request, so the strip costs no extra request.
HOURLY_FIELDS = "precipitation_probability"

# Rain severity bands, used to colour-code each day of the forecast. A day
# under SEVERITY_LOW_MAX is unlikely to be wet, a day up to
# SEVERITY_MODERATE_MAX is a real possibility, and anything above is likely.
SEVERITY_LOW_MAX = int(os.getenv("SEVERITY_LOW_MAX", "30"))
SEVERITY_MODERATE_MAX = int(os.getenv("SEVERITY_MODERATE_MAX", "60"))

# The chance at which carrying an umbrella starts to be worth it. It sits
# below the top band on purpose: a 55% day is not a certainty, but it is
# enough to change what you wear.
UMBRELLA_THRESHOLD = int(os.getenv("UMBRELLA_THRESHOLD", "50"))

# The temperature scale. The forecast service converts the values itself
# when the unit is asked for, so the app never does the arithmetic and the
# numbers are the service's own. The default is the one the service uses.
TEMPERATURE_UNITS = ("celsius", "fahrenheit")
DEFAULT_TEMPERATURE_UNIT = os.getenv("TEMPERATURE_UNIT", "celsius")
if DEFAULT_TEMPERATURE_UNIT not in TEMPERATURE_UNITS:
    DEFAULT_TEMPERATURE_UNIT = "celsius"


def clean_donation_url(value):
    """Return ``value`` if it is a usable https link, otherwise ``""``.

    The donation link is rendered into every page, so it is checked rather
    than trusted: only absolute ``https://`` URLs are accepted. A value such
    as ``javascript:...``, a plain ``http://`` link, a relative path, or
    something containing whitespace, quotes, angle brackets or control
    characters is ignored, and the link is left out. (Jinja escapes the value
    on output as well; this keeps obviously broken input out entirely.)
    """
    url = (value or "").strip()
    if not url or any(
        character.isspace() or character in "\"'<>\\" or ord(character) < 32
        for character in url
    ):
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return url


# Optional link to a donation page (for example Buy Me a Coffee). It is empty
# by default, and while it is empty no donation text appears anywhere, so a
# fresh checkout looks exactly as it always did. Only voluntary, one-off
# donations are compatible with Open-Meteo's free, non-commercial terms, so
# the page behind this link must not sell memberships, extras or subscriptions.
DONATION_URL = clean_donation_url(os.getenv("DONATION_URL"))

geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=GEOCODER_TIMEOUT)


# --- Weekday names -----------------------------------------------------------
# The seven weekday names, Monday first, matching date.weekday().
#
# They are hard-coded rather than taken from strftime("%A"), because
# strftime reads the process-wide LC_TIME locale: on a German Windows
# machine, or in a container with LANG set, it would render the weekday in
# that language. The rest of the page is English, so a half-translated date
# would be worse than a consistently English one.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday")


# --- Errors ------------------------------------------------------------------
class CityNotFound(Exception):
    """The geocoder has no match for the requested city."""


class GeocodingUnavailable(Exception):
    """The geocoding service could not be reached or returned an error."""


class WeatherUnavailable(Exception):
    """The forecast service could not be reached or returned an error."""


# --- Helpers -----------------------------------------------------------------
def round_half_up(value):
    """Round to the nearest integer, with .5 going up.

    Python's built-in ``round`` uses banker's rounding, so ``round(8.5)`` is 8
    and ``round(9.5)`` is 10. For temperatures, where halves are common, that
    reads as an off-by-one error.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_date(value):
    """Format an ISO date as ``Wednesday 21.10.2026``.

    The forecast API returns plain ``YYYY-MM-DD`` dates already expressed in
    the queried location's local time, so there is no timezone to convert.

    The weekday name comes from :data:`WEEKDAY_NAMES`, so it is always
    English.
    """
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value)
    weekday = WEEKDAY_NAMES[parsed.weekday()]
    return f"{weekday} {parsed.strftime('%d.%m.%Y')}"


def format_rain_chance(value):
    """The rain chance as a short label for a row or a table cell.

    The rows say "chance of rain" once, in the column header, so this is
    just the number. The full phrase is what a screen reader needs, and
    that is :func:`describe_rain_chance`.

    A value the service did not report is "unknown" rather than "0%", so
    it can never be mistaken for a dry day.
    """
    if value is None:
        return "unknown"
    try:
        return f"{round_half_up(float(value))}%"
    except (TypeError, ValueError):
        return "unknown"


def describe_rain_chance(value):
    """The rain chance as a full phrase, for screen readers and tooltips.

    The visible rows carry only the number, so this is the wording that
    stands on its own.
    """
    if value is None:
        return "chance of rain unknown"
    try:
        return f"{round_half_up(float(value))}% chance of rain"
    except (TypeError, ValueError):
        return "chance of rain unknown"


def format_temperature(high, low, unit="celsius"):
    """Compact high/low temperature label, or an empty string when unknown.

    The unit letter is not appended: the row shows "12° / 9°" and the
    switch beside the legend says which scale those numbers are in. That
    keeps the row narrow, and the two would be redundant anyway.
    """
    parts = []
    for value in (high, low):
        if value is None:
            continue
        try:
            parts.append(f"{round_half_up(float(value))}°")
        except (TypeError, ValueError):
            continue
    return " / ".join(parts)


def rain_chance(value):
    """The rain probability as a number, or ``None`` when it is unknown.

    The API occasionally reports a missing value as ``null``; the bands below
    need a number, so unknown chances get their own neutral band rather than
    being silently treated as zero.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def severity_band(chance):
    """Classify a rain chance into a severity band.

    Returns one of ``"low"``, ``"moderate"``, ``"high"`` or ``"unknown"``,
    which the template turns into a CSS class. The bands are the ones set out
    in the ideas document: under 30% is unlikely to be wet, 30-60% is a real
    possibility, and above 60% is likely.
    """
    probability = rain_chance(chance)
    if probability is None:
        return "unknown"
    if probability < SEVERITY_LOW_MAX:
        return "low"
    if probability <= SEVERITY_MODERATE_MAX:
        return "moderate"
    return "high"


def needs_umbrella(chance):
    """Whether the day is wet enough to be worth carrying an umbrella."""
    probability = rain_chance(chance)
    return probability is not None and probability >= UMBRELLA_THRESHOLD


# --- Hourly rain for today ---------------------------------------------------
# The strip shows the city's local day, one column per hour. The hours run
# 00 to 23 in the city's own timezone - the same local time the daily
# forecast is dated in - so "today" means the same thing in both lists.
HOURS_PER_DAY = 24

# The bar height in the strip, in percent per step. The height is bucketed
# into steps so it can live in the stylesheet as a class rather than as an
# inline style; the exact percentage travels in the tooltip and in the
# screen-reader text.
HOUR_HEIGHT_STEP = 5


def parse_hour_timestamp(value):
    """Parse an Open-Meteo local timestamp such as ``2026-10-21T15:00``."""
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def hour_height_step(chance, step=HOUR_HEIGHT_STEP):
    """The bar height for an hourly rain chance, in percent.

    The height is bucketed into steps so that it lives in the stylesheet as a
    class. The exact percentage is still available in the tooltip and in the
    screen-reader text, so nothing is lost by rounding the bar.
    """
    probability = rain_chance(chance)
    if probability is None:
        return 0
    steps = round_half_up(probability / step)
    return max(0, min(100, steps * step))


def local_now(payload):
    """The local hour the forecast is current for.

    The API reports the current time in the queried location's own timezone,
    which is the same local time the hourly and daily data are dated in. The
    UTC offset is only a fallback, for a response without a current block.

    The result is always a naive local time, so it can be compared with the
    timestamps parsed out of the hourly array.
    """
    current = payload.get("current") or {}
    moment = parse_hour_timestamp(current.get("time"))
    if moment is not None:
        return moment.replace(minute=0, second=0, microsecond=0)

    try:
        offset = int(payload.get("utc_offset_seconds"))
    except (TypeError, ValueError):
        return None
    now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    # The offset is already applied, so the result is a local wall time and
    # carries no timezone of its own.
    return now.replace(tzinfo=None, minute=0, second=0, microsecond=0)


def parse_today_hours(payload):
    """Today's hourly rain chances, one entry per hour, in local time.

    An empty list means the response carried no hourly data; the daily list
    still renders on its own.
    """
    daily = payload.get("daily") or {}
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    chances = hourly.get("precipitation_probability") or []
    if not times:
        return []

    entries = []
    for index, stamp in enumerate(times):
        moment = parse_hour_timestamp(stamp)
        if moment is None:
            continue
        chance = chances[index] if index < len(chances) else None
        entries.append((moment, chance))

    # The hourly array starts at local midnight of the current day. Matching
    # on the date rather than slicing the first 24 keeps the strip aligned
    # with the daily list even if the two disagree by a day. A day with 23 or
    # 25 hours (a clock-change day) is kept whole rather than truncated.
    #
    # The current time decides which day is "today" when it is available,
    # because that is the day the now-marker belongs to. The first daily
    # entry is the fallback.
    now = local_now(payload)
    today = now.date().isoformat() if now is not None \
        else (daily.get("time") or [None])[0]
    if today:
        todays = [entry for entry in entries
                  if entry[0].date().isoformat() == today]
        if todays:
            return _build_hours(todays, now)
    return _build_hours(entries[:HOURS_PER_DAY], now)


def _build_hours(entries, now):
    """Turn (timestamp, chance) pairs into the entries the template renders."""
    hours = []
    for moment, chance in entries:
        band = severity_band(chance)
        probability = rain_chance(chance)
        hours.append({
            "day": moment.date().isoformat(),
            "hour": moment.hour,
            "hour_label": f"{moment.hour:02d}",
            "time_label": f"{moment.hour:02d}:00",
            "chance": chance,
            # The tooltip and the screen-reader text stand on their own, so
            # they carry the full phrase. The table cell sits under a real
            # "Rain chance" column heading, so it can be the bare number.
            "chance_label": describe_rain_chance(chance),
            "chance_cell": format_rain_chance(chance),
            "severity": band,
            "severity_label": severity_label(band),
            "height": hour_height_step(chance),
            # A value the app cannot read is unknown, whether it arrived as
            # null or as something that is not a number.
            "unknown": probability is None,
            "past": now is not None and moment < now,
            "now": now is not None and moment == now,
        })
    return hours


def summarise_hours(hours):
    """A one-line summary of when rain is likely in the given hours.

    The threshold is the umbrella threshold, so the sentence agrees with the
    umbrella icon on the daily list. Only hours that have not happened yet
    count: a window that has already passed is not an alert.

    Returns an empty string when there is nothing to say.
    """
    upcoming = [hour for hour in hours if not hour["past"]]
    if not upcoming:
        return ""

    # Group the wet hours into contiguous windows.
    windows = []
    window = []
    for hour in upcoming:
        probability = rain_chance(hour["chance"])
        if probability is not None and probability >= UMBRELLA_THRESHOLD:
            window.append(hour)
        elif window:
            windows.append(window)
            window = []
    if window:
        windows.append(window)

    if not windows:
        return "No rain likely for the rest of today."

    first = windows[0]
    band = "high" if any(hour["severity"] == "high" for hour in first) \
        else "moderate"
    if all(hour["severity"] == "unknown" for hour in first):
        # An unknown chance is not a wet hour, but it is also not a dry one,
        # so it is never called "possible" or "likely".
        band = "unknown"
    peak = max(rain_chance(hour["chance"]) or 0 for hour in first)
    if len(first) == 1:
        span = f"at about {first[0]['time_label']}"
    else:
        span = f"from about {first[0]['time_label']} to {first[-1]['time_label']}"

    sentence = f"{severity_label(band).lower()} {span}, up to {round_half_up(peak)}%"
    if len(windows) > 1:
        sentence += ", and at other times too"

    return f"{sentence[0].upper()}{sentence[1:]}. Bring an umbrella."


def severity_label(band):
    """A short human-readable name for a severity band.

    The three bands read as a scale - unlikely, possible, likely - rather
    than as absolute claims. A day with a 25% chance is not "dry", it is
    just unlikely to be wet, and saying otherwise would mislead.

    The labels are deliberately short: they appear on the same line as the
    date, and a long label would push the forecast row onto a second line
    and make the whole list taller than the viewport.
    """
    return {
        "low": "Rain unlikely",
        "moderate": "Rain possible",
        "high": "Rain likely",
        "unknown": "Unknown",
    }.get(band, "Unknown")


# --- The headline ------------------------------------------------------------
# One line above the daily list that says what the week looks like. It names
# the first day worth mentioning: a day that reaches the umbrella threshold,
# a day that is merely possible, or the week as a whole when no day is.
#
# The band name in the sentence is the same one the row in the list carries,
# so the banner and the list never disagree about how wet a day is.


def forecast_day_label(iso_date, index):
    """How the headline names a day of the forecast.

    The first two days are "today" and "tomorrow", in the city's local time -
    the same local time the daily list is dated in, so the banner and the
    list never call different days "today". Later days are named by their
    weekday, the same English name the date in the list carries.
    """
    if index == 0:
        return "today"
    if index == 1:
        return "tomorrow"
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return f"in {index} days"
    return f"on {WEEKDAY_NAMES[parsed.weekday()]}"


def remaining_hour_chance(hours):
    """The highest rain chance among the hours that are still to come.

    ``None`` means the service reported no usable value for any of them.
    """
    chances = [rain_chance(hour.get("chance")) for hour in hours or []]
    known = [chance for chance in chances if chance is not None]
    if not known:
        return None
    return max(known)


def forecast_headline(forecast, remaining_hours=None):
    """The one-line summary of the forecast, or ``None`` if there is none.

    The sentence names the first day worth mentioning:

    * a day at or above the umbrella threshold - "Rain likely tomorrow
      (80%). Bring an umbrella.";
    * a day that is merely possible - "Rain possible on Thursday (45%).";
    * otherwise the week as a whole - "No rain likely for the next 7 days."

    The band in the sentence is the day's own band, the same one its row in
    the list carries, so the banner and the list never disagree about how
    wet a day is. The umbrella follows the same threshold as the icon on the
    row, and the wording follows the hourly summary above the strip.

    Today is the one day that needs care. The daily maximum covers the whole
    day, so at 18:00 it still counts the morning's downpour, while the
    reader can only walk into the evening. Today is therefore judged on the
    hours that are left, and the sentence says which figure it is using:
    "Rain likely for the rest of today (80%)." The hourly figures and the
    daily figure are two different quantities, and each one is labelled with
    which it is. When today is over, it is left out of the banner entirely:
    the reader wants to know about the days ahead, not about a day that has
    been and gone.

    A day whose chance the service did not report is never counted as dry.
    When the week is quiet but some days are unreported, the sentence says
    "most of" rather than claiming the whole week is dry - and when more of
    the week is unreported than is known to be dry, it says the chance is
    unknown instead, because "no rain likely for most of" would be a claim
    about days nobody reported.
    """
    if not forecast:
        return None

    today_over = False
    days = []
    for index, day in enumerate(forecast):
        chance = rain_chance(day.get("chance"))
        when = forecast_day_label(day.get("iso_date"), index)
        if index == 0 and remaining_hours is not None:
            # Judge today on the hours that are left, not on the whole day.
            if not remaining_hours:
                today_over = True
                continue
            remaining = remaining_hour_chance(remaining_hours)
            if remaining is not None:
                days.append((day, remaining, "for the rest of today"))
                continue
        days.append((day, chance, when))

    known = [entry for entry in days if entry[1] is not None]
    wet = next((entry for entry in known
                 if entry[1] >= UMBRELLA_THRESHOLD), None)
    possible = next((entry for entry in known
                     if severity_band(entry[1]) == "moderate"), None)

    if wet is not None:
        day, chance, when = wet
        band = severity_band(chance)
        return {
            "text": f"{_headline_sentence(band, when, chance)} Bring an umbrella.",
            "severity": band,
            "umbrella": True,
        }

    if possible is not None:
        day, chance, when = possible
        band = severity_band(chance)
        return {
            "text": _headline_sentence(band, when, chance),
            "severity": band,
            "umbrella": False,
        }

    count = len(days)
    span = "the rest of the week" if today_over else f"the next {count} days"
    unknown = count - len(known)
    if not known:
        return {
            "text": f"Rain chance unknown for {span}.",
            "severity": "unknown",
            "umbrella": False,
        }

    if unknown > len(known):
        # More of the week is unreported than is known to be dry, so the
        # honest answer is that the chance is mostly unknown.
        return {
            "text": f"Rain chance unknown for most of {span}.",
            "severity": "unknown",
            "umbrella": False,
        }

    if unknown:
        return {
            "text": f"No rain likely for most of {span}.",
            "severity": "low",
            "umbrella": False,
        }

    return {
        "text": f"No rain likely for {span}.",
        "severity": "low",
        "umbrella": False,
    }


def _headline_sentence(band, when, chance):
    """The sentence naming one day: "Rain likely tomorrow (80%)."."""
    sentence = (f"{severity_label(band).lower()} {when} "
                f"({round_half_up(chance)}%).")
    return f"{sentence[0].upper()}{sentence[1:]}"


# --- Data sources ------------------------------------------------------------
@lru_cache(maxsize=256)
def get_coordinates(city_name):
    """Resolve a city name to ``(latitude, longitude, display_name)``.

    Results are cached per process because a city name always maps to the same
    place; this keeps repeated searches from hammering Nominatim, which is
    rate-limited. Failures are not cached, so a retry re-attempts the lookup.
    """
    try:
        location = geolocator.geocode(city_name, exactly_one=True)
    except GeocoderTimedOut as exc:
        raise GeocodingUnavailable("the geocoder timed out") from exc
    except GeocoderQueryError as exc:
        # The geocoder understood the request and rejected the query.
        raise CityNotFound(city_name) from exc
    except GeocoderServiceError as exc:
        # Rate limiting, 5xx responses, and connection failures land here.
        raise GeocodingUnavailable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - no unexpected error should 500
        app.logger.exception("Unexpected geocoder error for %r", city_name)
        raise GeocodingUnavailable("unexpected geocoder error") from exc

    if location is None:
        # The service answered normally and simply had no match.
        raise CityNotFound(city_name)

    raw = getattr(location, "raw", None) or {}
    display_name = raw.get("display_name")
    label = display_name.split(",")[0].strip() if display_name else city_name
    return location.latitude, location.longitude, label


def fetch_forecast(latitude, longitude, unit=None):
    """Return the daily forecast as a list of dicts.

    An empty list means the service responded but had no forecast for the
    location; transport and payload problems raise :class:`WeatherUnavailable`.
    """
    forecast, _ = fetch_weather(latitude, longitude, unit)
    return forecast


def fetch_weather(latitude, longitude, unit=None):
    """Return the daily forecast and today's hourly rain chances.

    Both come from a single request: Open-Meteo serves the daily and the
    hourly fields together, and asking for both in one call keeps the app
    to one request per page load.

    The daily list is the primary result. The hourly list is an addition to
    it, so it may be empty when the service omits the hourly block, but a
    transport or payload problem raises :class:`WeatherUnavailable` and the
    page shows the error rather than a half-rendered forecast.

    ``unit`` is the temperature scale to ask the service for. The service
    converts the values itself, so the app never does the arithmetic.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": DAILY_FIELDS,
        "hourly": HOURLY_FIELDS,
        "current": HOURLY_FIELDS,
        "timezone": "auto",
        "temperature_unit": unit or DEFAULT_TEMPERATURE_UNIT,
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=WEATHER_TIMEOUT)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise WeatherUnavailable("the forecast request timed out") from exc
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise WeatherUnavailable(f"the forecast service returned HTTP {status}") from exc
    except requests.RequestException as exc:
        raise WeatherUnavailable(f"the forecast request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise WeatherUnavailable("the forecast response was not valid JSON") from exc

    daily = payload.get("daily") or {}
    dates = daily.get("time") or daily.get("time_string") or []
    chances = daily.get("precipitation_probability_max") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []

    forecast = []
    for index, (day, chance) in enumerate(zip(dates, chances)):
        band = severity_band(chance)
        forecast.append({
            "date": format_date(day),
            # The raw date, kept so the headline can name the weekday without
            # having to take the formatted date apart again.
            "iso_date": day,
            # The visible number, and the full phrase for the screen reader.
            # The column heading above the list says "chance of rain" once.
            "rain_label": format_rain_chance(chance),
            "rain_sr_label": describe_rain_chance(chance),
            "temp_label": format_temperature(
                highs[index] if index < len(highs) else None,
                lows[index] if index < len(lows) else None,
            ),
            "chance": chance,
            "severity": band,
            "severity_label": severity_label(band),
            "umbrella": needs_umbrella(chance),
        })

    try:
        hours = parse_today_hours(payload)
    except (TypeError, ValueError) as exc:
        # A missing hourly strip is a missing feature, not a broken forecast.
        app.logger.warning("Hourly forecast could not be parsed: %s", exc)
        hours = []

    return forecast, hours


# --- Routes ------------------------------------------------------------------
@app.context_processor
def inject_donation_url():
    """Make the donation link available to every template.

    It is read from the module on each request, not copied at import time,
    so a test can switch it on and off.
    """
    return {"donation_url": DONATION_URL}


def temperature_unit_from_request():
    """The temperature scale this request asks for.

    The unit comes from the query string on a GET and from the form on a
    POST. Anything unrecognised falls back to the default rather than
    failing: a stray query parameter should not break the page.
    """
    source = request.form if request.method == "POST" else request.args
    unit = (source.get("unit") or "").strip().lower()
    if unit in TEMPERATURE_UNITS:
        return unit
    return DEFAULT_TEMPERATURE_UNIT


@app.route('/', methods=['GET', 'POST'])
def index():
    weather_data = None
    hourly_data = None
    hourly_summary = None
    headline = None
    error = None
    display_city = None
    unit = temperature_unit_from_request()

    # A POST carries the city in the form; a GET carries it in the query
    # string, which is how the temperature switch asks for the same city
    # in the other scale.
    source = request.form if request.method == 'POST' else request.args
    city = (source.get('city') or '').strip()

    if request.method == 'POST' and not city:
        error = "Please enter a city name."
    elif city:
        try:
            latitude, longitude, display_city = get_coordinates(city)
            weather_data, hourly_data = fetch_weather(
                latitude, longitude, unit)
            hourly_summary = summarise_hours(hourly_data or [])
            # The umbrella advice is about the hours ahead, so the
            # headline is told which of today's hours are still to come.
            remaining_hours = [hour for hour in (hourly_data or [])
                               if not hour.get("past")]
            headline = forecast_headline(
                weather_data or [], remaining_hours)
        except CityNotFound:
            error = "City not found. Please try a different name (e.g., 'Paris')."
        except GeocodingUnavailable:
            app.logger.warning("Geocoding service unavailable for %r", city)
            error = ("The geocoding service is unavailable right now. "
                     "Please try again in a moment.")
        except WeatherUnavailable:
            app.logger.warning("Forecast service unavailable for %r", city)
            error = ("The weather service is unavailable right now. "
                     "Please try again in a moment.")

    return render_template(
        'index.html',
        weather_data=weather_data,
        hourly_data=hourly_data,
        hourly_summary=hourly_summary,
        headline=headline,
        error=error,
        city=city,
        display_city=display_city or city,
        unit=unit,
        temperature_units=TEMPERATURE_UNITS,
    )


if __name__ == '__main__':
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
