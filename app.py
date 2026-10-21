"""RainAlert: look up the 7-day rain chance for any city.

Two free, keyless APIs are used:
  * Nominatim (OpenStreetMap) turns a city name into coordinates.
  * Open-Meteo returns the daily forecast for those coordinates.
"""

import locale
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

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

# Weekday names are localised. A fixed locale is simplest; set it to "auto" to
# follow the browser's Accept-Language header instead, or leave it unset for
# English. Examples: de_DE, fr_FR, es_ES, nl_NL, pt_BR.
DATE_LOCALE = os.getenv("DATE_LOCALE", "de_DE")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = "precipitation_probability_max,temperature_2m_max,temperature_2m_min"

# Rain severity bands, used to colour-code each day of the forecast. A day
# under SEVERITY_LOW_MAX is unlikely to be wet, a day up to
# SEVERITY_MODERATE_MAX is a real possibility, and anything above is likely.
SEVERITY_LOW_MAX = int(os.getenv("SEVERITY_LOW_MAX", "30"))
SEVERITY_MODERATE_MAX = int(os.getenv("SEVERITY_MODERATE_MAX", "60"))

# The chance at which carrying an umbrella starts to be worth it. It sits
# below the top band on purpose: a 55% day is not a certainty, but it is
# enough to change what you wear.
UMBRELLA_THRESHOLD = int(os.getenv("UMBRELLA_THRESHOLD", "50"))

geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=GEOCODER_TIMEOUT)


# --- Localisation ------------------------------------------------------------
# Language tags as sent in an Accept-Language header, mapped to the locale
# names the C library understands.
_LANGUAGE_TO_LOCALE = {
    "de": "de_DE", "fr": "fr_FR", "es": "es_ES", "it": "it_IT",
    "nl": "nl_NL", "pt": "pt_PT", "pl": "pl_PL", "cs": "cs_CZ",
    "sk": "sk_SK", "sl": "sl_SI", "hr": "hr_HR", "hu": "hu_HU",
    "ro": "ro_RO", "bg": "bg_BG", "sv": "sv_SE", "da": "da_DK",
    "nb": "nb_NO", "no": "nb_NO", "fi": "fi_FI", "is": "is_IS",
    "et": "et_EE", "lv": "lv_LV", "lt": "lt_LT", "tr": "tr_TR",
    "ru": "ru_RU", "uk": "uk_UA", "el": "el_GR", "ja": "ja_JP",
    "ko": "ko_KR", "zh": "zh_CN", "th": "th_TH", "vi": "vi_VN",
    "id": "id_ID", "ms": "ms_MY", "he": "he_IL", "ar": "ar_EG",
    "hi": "hi_IN", "fa": "fa_IR", "ca": "ca_ES", "gl": "gl_ES",
    "eu": "eu_ES", "sw": "sw_KE", "af": "af_ZA", "en": "en_US",
}

# Regional variants, used when the request names a specific region.
_LOCALE_ALIASES = {
    "pt_BR": "pt_BR", "pt_PT": "pt_PT",
    "en_GB": "en_GB", "en_AU": "en_AU", "en_CA": "en_CA", "en_IE": "en_IE",
    "en_NZ": "en_NZ", "en_US": "en_US",
    "fr_CA": "fr_CA", "fr_CH": "fr_CH", "fr_BE": "fr_BE", "fr_LU": "fr_LU",
    "de_AT": "de_AT", "de_CH": "de_CH",
    "es_MX": "es_MX", "es_AR": "es_AR", "es_CO": "es_CO", "es_US": "es_US",
    "it_CH": "it_CH", "nl_BE": "nl_BE",
    "zh_TW": "zh_TW", "zh_CN": "zh_CN", "zh_HK": "zh_CN",
}


def locale_from_accept_language(header):
    """Pick a locale from an Accept-Language header.

    The header is a comma-separated list of language tags with optional
    quality values, e.g. ``de-DE,de;q=0.9,en;q=0.8``. The first tag the
    system supports wins; ``None`` is returned when nothing matches.

    A region is honoured when the language has a regional variant, so
    ``pt-BR`` gives Brazilian Portuguese and ``pt-PT`` European Portuguese.
    """
    if not header:
        return None
    for part in header.split(","):
        tag = part.split(";")[0].strip()
        if not tag:
            continue
        parts = tag.replace("-", "_").split("_")
        language = parts[0].lower()
        region = parts[1].upper() if len(parts) > 1 else ""
        if region:
            regional = f"{language}_{region}"
            if regional in _LOCALE_ALIASES:
                return _LOCALE_ALIASES[regional]
        candidate = _LANGUAGE_TO_LOCALE.get(language)
        if candidate:
            return candidate
    return None


def requested_locale():
    """The locale to render weekday names in, for this request."""
    if DATE_LOCALE and DATE_LOCALE.lower() != "auto":
        return DATE_LOCALE
    detected = locale_from_accept_language(request.headers.get("Accept-Language"))
    return detected or "en_US"


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


def format_date(value, locale_name=None):
    """Format an ISO date as ``Wednesday 21.10.2026``.

    The forecast API returns plain ``YYYY-MM-DD`` dates already expressed in
    the queried location's local time, so there is no timezone to convert.

    The weekday name is localised using the C library's locale data.
    """
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value)
    weekday = weekday_names(locale_name)[parsed.weekday()]
    return f"{weekday} {parsed.strftime('%d.%m.%Y')}"


def _locale_candidates(locale_name):
    """The names to try when switching to a locale, in order.

    The C library does not agree on how a locale is spelled. Windows accepts
    the bare name (``de_DE``), while glibc usually wants a codeset suffix
    (``de_DE.UTF-8`` or ``de_DE.utf8``) and rejects the bare form even when
    that locale is installed. Rather than pick one platform's convention, try
    the bare name first and then the two common codeset spellings.
    """
    yield locale_name
    if "." not in locale_name:
        yield f"{locale_name}.UTF-8"
        yield f"{locale_name}.utf8"


@lru_cache(maxsize=32)
def weekday_names(locale_name=None):
    """Return the seven weekday names, Monday first, for a locale.

    ``datetime.strftime`` reads the process-wide ``LC_TIME`` locale, so the
    locale is switched only while the names are read and the previous value
    is always restored. The result is cached, so the switch happens once per
    locale rather than once per row. An unavailable locale falls back to
    English rather than raising.
    """
    if not locale_name:
        return tuple(date(2026, 1, 5 + offset).strftime("%A") for offset in range(7))

    previous = locale.setlocale(locale.LC_TIME, None)
    for candidate in _locale_candidates(locale_name):
        try:
            locale.setlocale(locale.LC_TIME, candidate)
            break
        except locale.Error:
            continue
    else:
        locale.setlocale(locale.LC_TIME, previous)
        app.logger.warning(
            "Locale %r is not available on this system; using English weekday names",
            locale_name,
        )
        return tuple(date(2026, 1, 5 + offset).strftime("%A") for offset in range(7))
    try:
        # 2026-01-05 is a Monday, so the first seven days cover every weekday.
        return tuple(date(2026, 1, 5 + offset).strftime("%A") for offset in range(7))
    finally:
        locale.setlocale(locale.LC_TIME, previous)


def format_rain_chance(value):
    """Human-readable rain probability, with a fallback for missing values."""
    if value is None:
        return "chance of rain unknown"
    try:
        return f"{round_half_up(float(value))}% chance of rain"
    except (TypeError, ValueError):
        return "chance of rain unknown"


def format_temperature(high, low):
    """Compact high/low temperature label, or an empty string when unknown."""
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


def fetch_forecast(latitude, longitude, locale_name=None):
    """Return the daily forecast as a list of dicts.

    An empty list means the service responded but had no forecast for the
    location; transport and payload problems raise :class:`WeatherUnavailable`.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": DAILY_FIELDS,
        "timezone": "auto",
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
            "date": format_date(day, locale_name),
            "rain_label": format_rain_chance(chance),
            "temp_label": format_temperature(
                highs[index] if index < len(highs) else None,
                lows[index] if index < len(lows) else None,
            ),
            "chance": chance,
            "severity": band,
            "severity_label": severity_label(band),
            "umbrella": needs_umbrella(chance),
        })
    return forecast


# --- Routes ------------------------------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    weather_data = None
    error = None
    city = None
    display_city = None

    if request.method == 'POST':
        city = (request.form.get('city') or '').strip()
        if not city:
            error = "Please enter a city name."
        else:
            try:
                latitude, longitude, display_city = get_coordinates(city)
                weather_data = fetch_forecast(latitude, longitude, requested_locale())
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
        error=error,
        city=city,
        display_city=display_city or city,
    )


if __name__ == '__main__':
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
