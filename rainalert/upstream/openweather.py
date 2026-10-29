"""OpenWeather: the forecast when Open-Meteo will not give one.

Open-Meteo's free tier limits requests per IP address, and the host this
site runs on shares its address with other apps, so on a bad day the whole
allowance is gone before the site has asked for anything. This module is the
second source: with ``OPENWEATHER_API_KEY`` set, a request Open-Meteo has
refused is asked of OpenWeather's One Call 4.0 instead, on a quota of the
site's own.

One Call 4.0 has an endpoint for each timeline, so a forecast is two calls:
the days, and the hours from now. The hours are an addition to the forecast,
as they are for Open-Meteo, so a forecast with no hours still makes a page.
The current hour is not asked for at all: every answer carries the place's
offset from UTC, and the clock gives the rest.

The answer is translated into the shape Open-Meteo sends, so the validator,
the parser and everything above them are unchanged and never learn which
service a forecast came from. A page never mixes the two: the whole forecast
comes from one of them.

OpenWeather bills calls beyond its free thousand a day, so the calls are
counted and stop at ``OPENWEATHER_DAILY_LIMIT``. The key travels in the
query string, so nothing here logs a URL or an exception's text.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import requests

from rainalert import config
from rainalert.errors import WeatherUnavailable

log = logging.getLogger(__name__)

BASE_URL = "https://api.openweathermap.org/data/4.0/onecall/timeline"
DAILY_URL = BASE_URL + "/1day"
HOURLY_URL = BASE_URL + "/1h"

# The days and the hours.
CALLS_PER_FORECAST = 2

# The scale the reader chose, in OpenWeather's words for it.
UNITS = {"celsius": "metric", "fahrenheit": "imperial"}

# Open-Meteo's week is seven days; the daily timeline sends up to ten.
DAYS = 7

HOURS_PER_DAY = 24

_budget_lock = threading.Lock()
_budget = {"day": None, "calls": 0}


def reset_budget():
    """Start the day's count again. The tests use it between cases."""
    with _budget_lock:
        _budget.update(day=None, calls=0)


def _take_calls(count):
    """Count ``count`` calls against today's allowance; false when they do
    not fit in what is left of it.

    The day is the UTC day, which is the day OpenWeather counts in.
    """
    today = datetime.now(timezone.utc).date()
    with _budget_lock:
        if _budget["day"] != today:
            _budget.update(day=today, calls=0)
        if _budget["calls"] + count > config.OPENWEATHER_DAILY_LIMIT:
            return False
        _budget["calls"] += count
        return True


def fallback(latitude, longitude, unit=None):
    """The forecast in Open-Meteo's shape, or ``None`` when there is none.

    ``None`` covers every reason there can be no fallback - no key, the
    day's allowance spent, a refusal, a broken answer - so the caller keeps
    the failure it already has. Nothing here raises.
    """
    if not config.OPENWEATHER_API_KEY:
        return None
    if not _take_calls(CALLS_PER_FORECAST):
        log.warning("OpenWeather fallback skipped: the day's %s calls are "
                    "spent or too few are left", config.OPENWEATHER_DAILY_LIMIT)
        return None
    try:
        days = _request(DAILY_URL, latitude, longitude, unit)
    except WeatherUnavailable as exc:
        log.warning("OpenWeather fallback failed: %s", exc)
        return None
    try:
        hours = _request(HOURLY_URL, latitude, longitude, unit)
    except WeatherUnavailable as exc:
        # The hours are an addition to the week, here as everywhere.
        log.warning("OpenWeather hours failed, the week goes without them: %s", exc)
        hours = None
    try:
        return _translate(days, hours)
    except WeatherUnavailable as exc:
        log.warning("OpenWeather fallback failed: %s", exc)
        return None


def _request(url, latitude, longitude, unit):
    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": config.OPENWEATHER_API_KEY,
        "units": UNITS.get(unit or config.DEFAULT_TEMPERATURE_UNIT, "metric"),
    }
    try:
        response = requests.get(url, params=params, timeout=config.WEATHER_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        raise WeatherUnavailable(f"OpenWeather returned HTTP {status}") from None
    except requests.Timeout:
        raise WeatherUnavailable("the OpenWeather request timed out") from None
    except requests.RequestException as exc:
        # The class, not the text: the text of a request error is the URL.
        raise WeatherUnavailable(
            f"the OpenWeather request failed ({type(exc).__name__})") from None
    except ValueError:
        raise WeatherUnavailable("the OpenWeather answer was not JSON") from None


def _local(timestamp, offset):
    """A Unix time as the location's own wall-clock time, naive."""
    moment = datetime.fromtimestamp(int(timestamp) + offset, tz=timezone.utc)
    return moment.replace(tzinfo=None)


def _percent(chance):
    """OpenWeather's 0-1 chance as Open-Meteo's whole percent."""
    if chance is None:
        return None
    return round(float(chance) * 100)


def _number(value):
    """A reading as a number, or ``None`` when the answer has none."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _translate(days, hours):
    """OpenWeather's two answers as an Open-Meteo-shaped payload."""
    try:
        return _translate_unchecked(days, hours)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError,
            OverflowError, OSError):
        raise WeatherUnavailable("the OpenWeather answer was not a forecast") from None


def _hours_of_the_days(body, offset):
    """The hourly records as full local days, 00 to 23.

    The records run from the current hour for a short while, and the strip
    is the whole local day. Every day the records touch is filled out to 24
    hours, and an hour that was not reported is unknown - which includes the
    hours of today that have already gone, because this service no longer
    reports them.
    """
    known = {}
    for record in body["data"]:
        moment = _local(record["dt"], offset)
        known[moment.replace(minute=0, second=0, microsecond=0)] = (
            _percent(record.get("pop")))
    times, chances = [], []
    for day in sorted({moment.date() for moment in known}):
        for hour in range(HOURS_PER_DAY):
            moment = datetime(day.year, day.month, day.day, hour)
            times.append(moment.strftime("%Y-%m-%dT%H:00"))
            chances.append(known.get(moment))
    return times, chances


def _translate_unchecked(days_body, hours_body):
    offset = int(days_body["timezone_offset"])
    records = days_body["data"][:DAYS]
    if not records:
        raise ValueError("no days")

    dates, chances, highs, lows, amounts = [], [], [], [], []
    for record in records:
        dates.append(_local(record["dt"], offset).date().isoformat())
        chances.append(_percent(record.get("pop")))
        highs.append(record["temp"]["max"])
        lows.append(record["temp"]["min"])
        # Rain and snow are millimetres of water either way. A day that
        # reports neither has not said it is dry, so its amount is unknown.
        rain, snow = _number(record.get("rain")), _number(record.get("snow"))
        amounts.append(None if rain is None and snow is None
                       else round((rain or 0) + (snow or 0), 1))

    now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    payload = {
        "daily": {
            "time": dates,
            "precipitation_probability_max": chances,
            "temperature_2m_max": highs,
            "temperature_2m_min": lows,
            "precipitation_sum": amounts,
            # This service does not say how many hours the rain lasts, and
            # an unknown is not shown, rather than shown as none.
            "precipitation_hours": [None] * len(dates),
        },
        # The place's own clock: the offset is in every answer, so the
        # current hour needs no call of its own.
        "current": {"time": now.strftime("%Y-%m-%dT%H:%M")},
        "utc_offset_seconds": offset,
    }
    if hours_body is not None:
        try:
            times, hour_chances = _hours_of_the_days(hours_body, offset)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError,
                OSError):
            log.warning("OpenWeather hours could not be read, the week goes "
                        "without them")
        else:
            payload["hourly"] = {"time": times,
                                 "precipitation_probability": hour_chances}
    return payload
