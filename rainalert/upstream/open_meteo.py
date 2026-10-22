"""Open-Meteo: the forecast for a pair of coordinates.

One request per page load: the daily fields, the hourly rain chance and the
current hour all come in the same call, in the city's own local time
(``timezone=auto``). Do not convert those dates to the viewer's timezone.
"""

import logging

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


def fetch_payload(latitude, longitude, unit=None):
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
        return response.json()
    except ValueError as exc:
        raise WeatherUnavailable("the forecast response was not valid JSON") from exc


def _hourly_failed(exc):
    # A missing hourly strip is a missing feature, not a broken forecast.
    log.warning("Hourly forecast could not be parsed: %s", exc)


def load_forecast(latitude, longitude, unit=None):
    """The forecast for a place, parsed once: the days and today's hours."""
    payload = fetch_payload(latitude, longitude, unit)
    return parse_forecast(payload, on_hourly_error=_hourly_failed)
