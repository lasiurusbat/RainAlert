"""Turn an Open-Meteo response into a :class:`~rainalert.domain.model.Forecast`.

The response is parsed once per request: the current time is read once,
the hours are grouped by day once, and today's hours are picked out of
those groups rather than parsed again.

The strip shows the city's local day, one column per hour. The hours run
00 to 23 in the city's own timezone - the same local time the daily
forecast is dated in - so "today" means the same thing in both lists.
"""

from datetime import datetime, timedelta, timezone

from rainalert.domain.model import Day, Forecast, Hour

HOURS_PER_DAY = 24


def _as_list(value):
    """The value as a list of entries, or an empty one.

    The service sends its values as arrays. A field that is not an array
    cannot be read as one, and a field that cannot be read is an empty
    one rather than a failure: the parser never raises on the shape of
    the answer.
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def parse_hour_timestamp(value):
    """Parse an Open-Meteo local timestamp such as ``2026-10-21T15:00``."""
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def local_now(payload):
    """The local hour the forecast is current for.

    The API reports the current time in the queried location's own timezone,
    which is the same local time the hourly and daily data are dated in. The
    UTC offset is only a fallback, for a response without a current block.

    The result is always a naive local time, so it can be compared with the
    timestamps parsed out of the hourly array. A current block that cannot be
    read is no current block: the strip still draws, it just carries no
    now-marker.
    """
    if not isinstance(payload, dict):
        return None
    current = payload.get("current")
    if not isinstance(current, dict):
        current = {}
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


def _daily_block(payload):
    """The daily block of the answer, or an empty one.

    The service sends the block as an object with an array of days in it.
    A block that is not an object carries no days, and a forecast with no
    days is a forecast the page says there is no data for.
    """
    if not isinstance(payload, dict):
        return {}
    daily = payload.get("daily")
    return daily if isinstance(daily, dict) else {}


def parse_forecast(payload, on_hourly_error=None):
    """The whole forecast: the days, each with its hours, and today's hours.

    The daily list is the primary result. The hours are an addition to it:
    a response without an hourly block gives days without hours, and an
    hourly block that cannot be read is a missing feature, not a broken
    forecast. ``on_hourly_error`` is called with the exception in that case
    and the days come back without hours; without it, the exception is
    raised.

    Nothing in the answer can make this raise. A field that is not the
    shape the service documents is read as no values at all, so a strange
    answer gives a page with fewer numbers on it rather than a broken
    one.
    """
    daily = _daily_block(payload)
    dates = _as_list(daily.get("time")) or _as_list(daily.get("time_string"))
    chances = _as_list(daily.get("precipitation_probability_max"))
    highs = _as_list(daily.get("temperature_2m_max"))
    lows = _as_list(daily.get("temperature_2m_min"))
    amounts = _as_list(daily.get("precipitation_sum"))
    hours_of_rain = _as_list(daily.get("precipitation_hours"))

    try:
        hourly_days, now = _parse_hourly_days(payload)
        today = _today_hours(hourly_days, now)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        if on_hourly_error is None:
            raise
        on_hourly_error(exc)
        hourly_days, today = [], ()
    hours_by_date = dict(hourly_days)

    def at(values, index):
        return values[index] if index < len(values) else None

    days = tuple(
        Day(
            iso_date=day,
            chance=chance,
            high=at(highs, index),
            low=at(lows, index),
            amount=at(amounts, index),
            rain_hours=at(hours_of_rain, index),
            hours=hours_by_date.get(day) or (),
        )
        for index, (day, chance) in enumerate(zip(dates, chances))
    )
    return Forecast(days=days, today=today)


def _parse_hourly_days(payload):
    """The hourly rain chances, split by the day they belong to.

    The service answers with one array of timestamps for the whole range,
    and the strip draws one day at a time: the reader picks a day out of the
    week and the graph shows that day. So the hours have to be grouped by
    the day they fall on, and the groups come back in the order of the
    daily list.

    Returns a list of ``(date, hours)`` pairs and the current local hour. An
    empty list means the response carried no hourly data; the daily list
    still renders on its own.

    A block that is there but cannot be read raises, and the caller turns
    that into a missing strip: the hours are an addition to the forecast,
    and an addition that cannot be read is a missing feature rather than a
    broken forecast.
    """
    daily = _daily_block(payload)
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if hourly is None:
        return [], None
    if not isinstance(hourly, dict):
        raise ValueError("the hourly block is not an object")
    times = hourly.get("time")
    if times is not None and not isinstance(times, (list, tuple)):
        raise ValueError("the hourly times are not a list")
    chances = hourly.get("precipitation_probability")
    if chances is not None and not isinstance(chances, (list, tuple)):
        raise ValueError("the hourly chances are not a list")
    times = list(times or [])
    chances = list(chances or [])
    if not times:
        return [], None
    now = local_now(payload)

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
    days = []
    for day in _as_list(daily.get("time")):
        todays = [entry for entry in entries
                  if entry[0].date().isoformat() == day]
        days.append((day, _build_hours(todays, now)))

    if not days:
        # There is no daily list to line the hours up with, so the first day
        # of the hourly array is the day the strip draws.
        if not entries:
            return [], now
        return [(entries[0][0].date().isoformat(),
                 _build_hours(entries[:HOURS_PER_DAY], now))], now

    if not days[0][1]:
        # The hourly array does not start on the first day of the daily
        # list. The strip still needs a day to draw, so it falls back to the
        # first day of the array, as it always has.
        days[0] = (days[0][0], _build_hours(entries[:HOURS_PER_DAY], now))

    return days, now


def _today_hours(hourly_days, now):
    """Today's hours, out of the hours grouped by day.

    The current time decides which day is "today" when it is available,
    because that is the day the now-marker belongs to. The first group is
    the fallback.
    """
    if not hourly_days:
        return ()
    today = now.date().isoformat() if now is not None else None
    if today:
        for day, hours in hourly_days:
            if day == today and hours:
                return hours
    return hourly_days[0][1]


def _build_hours(entries, now):
    """Turn (timestamp, chance) pairs into :class:`Hour` objects."""
    return tuple(
        Hour(moment=moment, chance=chance,
             past=now is not None and moment < now,
             now=now is not None and moment == now)
        for moment, chance in entries
    )
