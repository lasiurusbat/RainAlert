"""Open-Meteo: the forecast for a pair of coordinates.

One request per page load: the daily fields, the hourly rain chance and the
current hour all come in the same call, in the city's own local time
(``timezone=auto``). Do not convert those dates to the viewer's timezone.
"""

import copy
import logging
import threading
import time

import requests

from rainalert import config
from rainalert.domain.parse import parse_forecast
from rainalert.errors import WeatherUnavailable

log = logging.getLogger(__name__)


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# The daily fields. The chance is the figure the week is built on, the
# temperatures are the figures beside it, and the last two say how much rain
# falls and how long it lasts - the day panel shows them for the day the
# reader picks.
DAILY_FIELDS = ("precipitation_probability_max,temperature_2m_max,"
                "temperature_2m_min,precipitation_sum,precipitation_hours")

# The hourly rain chance for today, and the same field for the current hour.
# Both come in the same request, so the strip costs no extra request.
HOURLY_FIELDS = "precipitation_probability"


# The forecasts the server has fetched lately, by place and scale. The free
# service limits requests per IP address and answers HTTP 429 beyond it, so a
# forecast fetched a few minutes ago is reused rather than asked for again.
# This is the server's own copy only: the browser and the service worker
# still never keep a forecast. Only a good answer is stored, so a failure is
# always retried.
_cache = {}
_cache_lock = threading.Lock()
MAX_CACHED_FORECASTS = 512


def clear_cache():
    """Forget every stored forecast. The tests use it between cases."""
    with _cache_lock:
        _cache.clear()


def _cached(key):
    ttl = config.WEATHER_CACHE_SECONDS
    if ttl <= 0:
        return None
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if time.monotonic() - stored_at >= ttl:
            del _cache[key]
            return None
    return copy.deepcopy(payload)


def _store(key, payload):
    if config.WEATHER_CACHE_SECONDS <= 0:
        return
    with _cache_lock:
        if len(_cache) >= MAX_CACHED_FORECASTS and key not in _cache:
            # Dicts keep insertion order, so the first key is the oldest.
            del _cache[next(iter(_cache))]
        _cache[key] = (time.monotonic(), copy.deepcopy(payload))


def fetch_payload(latitude, longitude, unit=None):
    """The forecast service's answer, from the server's copy when it is fresh.

    ``WEATHER_CACHE_SECONDS`` says how long a copy stays fresh. A failed or
    broken answer is never kept, so the next request asks again.
    """
    key = (latitude, longitude, unit or config.DEFAULT_TEMPERATURE_UNIT)
    payload = _cached(key)
    if payload is None:
        payload = _request_payload(latitude, longitude, unit)
        _store(key, payload)
    return payload


def _request_payload(latitude, longitude, unit=None):
    """The forecast service's answer, as the JSON it sent.

    The daily and the hourly fields come from a single request: Open-Meteo
    serves them together, and asking for both in one call keeps the app to
    one request per page load. A transport or payload problem raises
    :class:`WeatherUnavailable`.

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
        "temperature_unit": unit or config.DEFAULT_TEMPERATURE_UNIT,
    }
    try:
        response = requests.get(FORECAST_URL, params=params, timeout=config.WEATHER_TIMEOUT)
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
    if not _is_a_forecast(payload):
        raise WeatherUnavailable("the forecast response was not a forecast")
    return payload


# The fields the daily block carries, and the shape each one has to have.
# A field that is not there is a field the service did not send, and a
# field that is there but is not a list is not a forecast.
DAILY_ARRAYS = ("time", "precipitation_probability_max", "temperature_2m_max",
                "temperature_2m_min", "precipitation_sum",
                "precipitation_hours")


def _is_a_forecast(payload):
    """Whether the answer is shaped like a forecast.

    The service is a third party, so its answer is checked before it is
    used. An answer that is not a forecast at all - a list, a string, an
    error page served as JSON - is not a forecast with nothing in it: it
    is a broken answer, and it is reported as one, so the reader is told
    to come back in a moment rather than shown an empty week.

    A block that is there but is the wrong shape is a broken answer in
    the same way. The hourly block is not checked: the hours are an
    addition to the forecast, and a missing or unreadable strip is a
    missing feature rather than a broken forecast.
    """
    if not isinstance(payload, dict):
        return False
    daily = payload.get("daily")
    if daily is None:
        # No daily block at all: the service answered, and it had no
        # forecast to give. The page says so and stays up.
        return True
    if not isinstance(daily, dict):
        return False
    return all(daily.get(field) is None
               or isinstance(daily.get(field), (list, tuple))
               for field in DAILY_ARRAYS)


def _hourly_failed(exc):
    # A missing hourly strip is a missing feature, not a broken forecast.
    log.warning("Hourly forecast could not be parsed: %s", exc)


def load_forecast(latitude, longitude, unit=None):
    """The forecast for a place, parsed once: the days and today's hours."""
    payload = fetch_payload(latitude, longitude, unit)
    return parse_forecast(payload, on_hourly_error=_hourly_failed)
