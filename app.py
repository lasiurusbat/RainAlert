"""RainAlert: look up the 7-day rain chance for any city.

Two free, keyless APIs are used:
  * Nominatim (OpenStreetMap) turns a city name into coordinates.
  * Open-Meteo returns the daily forecast for those coordinates.
"""

import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

import requests
from flask import (Flask, Response, abort, jsonify, make_response, redirect,
                   render_template, request, send_from_directory)
from geopy.exc import GeocoderQueryError, GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from rainalert import config
from rainalert.data.cities import CITY_NAMES, CITY_SLUGS, CURATED_CITIES
from rainalert.data.releases import RELEASES
from rainalert.errors import CityNotFound, GeocodingUnavailable, WeatherUnavailable

app = Flask(__name__)

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

geolocator = Nominatim(user_agent=config.NOMINATIM_USER_AGENT, timeout=config.GEOCODER_TIMEOUT)


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

# The same names, shortened. The week is a row of seven narrow columns, and
# "Wednesday" does not fit in one of them. These are hard-coded for the same
# reason the long ones are: no locale, no strftime.
WEEKDAY_SHORT_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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


def format_date_parts(value):
    """The short forms of a date, for the week that is a row of columns.

    Returns the abbreviated weekday ("Thu") and the day and month
    ("22.10"). The long form stays in :func:`format_date`, and the page
    carries it for screen readers, so nothing is lost by shortening what
    is on the page.
    """
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "", ""
    return (WEEKDAY_SHORT_NAMES[parsed.weekday()],
            parsed.strftime("%d.%m"))


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


def format_rain_chance_short(value):
    """The rain chance as a bare number, for the hourly strip.

    The strip has one narrow column per hour of the day, and "100%" does
    not fit in one of them while "100" does. The unit is stated by the
    sentence above the strip and by the table below it.

    A value the service did not report is a question mark, not a zero.
    """
    if value is None:
        return "?"
    try:
        return f"{round_half_up(float(value))}"
    except (TypeError, ValueError):
        return "?"


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


def format_precipitation(value):
    """The day's rain in millimetres, as a short label.

    The service reports the day's total in millimetres, and the panel shows
    it with one decimal, because a difference between 4 mm and 5 mm is the
    difference between a drizzle and a shower.

    A day with nothing in it says nothing at all. The figure is only
    interesting when there is rain in it, and "0 mm" beside a chance of
    rain would read as a contradiction: the two come from different parts
    of the model, and a day can be likely to rain and still come out at
    nothing measurable.
    """
    if value is None:
        return ""
    try:
        millimetres = float(value)
    except (TypeError, ValueError):
        return ""
    if millimetres <= 0:
        return ""
    return f"{millimetres:.1f} mm"


def format_rain_hours(value):
    """How long the rain lasts, as a short label.

    The service reports the number of hours with precipitation, and the
    figure is shown only when there is rain to last. A day the model
    expects none says nothing here, for the same reason as the
    millimetres do.
    """
    if value is None:
        return ""
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return ""
    if hours <= 0:
        return ""
    return f"{round_half_up(hours)} h of rain"


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


def chance_number(value):
    """The rain chance as the whole number the page shows, or ``None``.

    This is the number the reader sees next to the date, and it is the number
    a personal alert threshold is compared against, so the two can never
    disagree: a row shown as "45%" is 45 here, not 44.6. A value the service
    did not report is ``None``, so it is never counted as a dry day.
    """
    probability = rain_chance(value)
    if probability is None:
        return None
    return round_half_up(probability)


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
    if probability < config.SEVERITY_LOW_MAX:
        return "low"
    if probability <= config.SEVERITY_MODERATE_MAX:
        return "moderate"
    return "high"


def needs_umbrella(chance):
    """Whether the day is wet enough to be worth carrying an umbrella."""
    probability = rain_chance(chance)
    return probability is not None and probability >= config.UMBRELLA_THRESHOLD


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


def parse_hourly_days(payload):
    """The hourly rain chances, split by the day they belong to.

    The service answers with one array of timestamps for the whole range,
    and the strip draws one day at a time: the reader picks a day out of the
    week and the graph shows that day. So the hours have to be grouped by
    the day they fall on, and the groups come back in the order of the
    daily list.

    Returns a list of ``(date, hours)`` pairs. An empty list means the
    response carried no hourly data; the daily list still renders on its own.
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
    now = local_now(payload)
    days = []
    for day in (daily.get("time") or []):
        todays = [entry for entry in entries
                  if entry[0].date().isoformat() == day]
        days.append((day, _build_hours(todays, now)))

    if not days:
        # There is no daily list to line the hours up with, so the first day
        # of the hourly array is the day the strip draws.
        if not entries:
            return []
        return [(entries[0][0].date().isoformat(),
                 _build_hours(entries[:HOURS_PER_DAY], now))]

    if not days[0][1]:
        # The hourly array does not start on the first day of the daily
        # list. The strip still needs a day to draw, so it falls back to the
        # first day of the array, as it always has.
        days[0] = (days[0][0], _build_hours(entries[:HOURS_PER_DAY], now))

    return days


def parse_today_hours(payload):
    """Today's hourly rain chances, one entry per hour, in local time.

    The current time decides which day is "today" when it is available,
    because that is the day the now-marker belongs to. The first daily
    entry is the fallback.

    An empty list means the response carried no hourly data; the daily list
    still renders on its own.
    """
    days = parse_hourly_days(payload)
    if not days:
        return []
    now = local_now(payload)
    today = now.date().isoformat() if now is not None else None
    if today:
        for day, hours in days:
            if day == today and hours:
                return hours
    return days[0][1]


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
            # The bare number, for the strip's own value row: one narrow
            # column per hour does not have room for the sign.
            "chance_short": format_rain_chance_short(chance),
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


def summarise_hours(hours, when="for the rest of today"):
    """A one-line summary of when rain is likely in the given hours.

    The threshold is the umbrella threshold, so the sentence agrees with the
    umbrella icon on the daily list. Only hours that have not happened yet
    count: a window that has already passed is not an alert.

    ``when`` says which day the sentence is about: "for the rest of today"
    for the day that is running, and "tomorrow" or "on Friday" for a day
    that is still to come.

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
        if probability is not None and probability >= config.UMBRELLA_THRESHOLD:
            window.append(hour)
        elif window:
            windows.append(window)
            window = []
    if window:
        windows.append(window)

    if not windows:
        return f"No rain likely {when}."

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


def day_panel_name(iso_date, index):
    """How the day panel names a day: Today, Tomorrow, or the weekday.

    The same rule as :func:`forecast_day_label`, in the capitalised form the
    panel needs: the first two days have names of their own, and the rest
    are named by their English weekday.
    """
    if index == 0:
        return "Today"
    if index == 1:
        return "Tomorrow"
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return ""
    return WEEKDAY_NAMES[parsed.weekday()]


def day_phrases(index, day_name):
    """How a sentence refers to a day of the week.

    Returns two phrases: the short one, for a caption ("today", "tomorrow",
    "on Friday"), and the one the hourly summary uses. The summary of the
    day that is running says "for the rest of today", because only that day
    has hours left to come; a day that is still to come is named outright.
    """
    if index == 0:
        return "today", "for the rest of today"
    if index == 1:
        return "tomorrow", "tomorrow"
    return f"on {day_name}", f"on {day_name}"


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
                 if entry[1] >= config.UMBRELLA_THRESHOLD), None)
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


# --- The tab title and the favicon --------------------------------------------
# The title and the favicon are the alert a visitor sees without looking at
# the page: a tab left open in the background tells them at a glance whether
# the weather changed while they were away.
#
# Both are driven by the same forecast the headline uses and by the same
# threshold, so the tab and the banner can never disagree.

# The title says "Rain tomorrow" and not the day's date: a tab title is
# read at a glance, and "tomorrow" is the thing a reader is asking about.
TAB_TITLE_PREFIX = "Rain"
TAB_TITLE_SUFFIX = "Rain Alert"
DEFAULT_TAB_TITLE = "Rain Alert"

# The favicon that says "rain is coming", and the one that says nothing.
FAVICON_DEFAULT = "favicon.svg"
FAVICON_RAIN = "favicon-rain.svg"


def tab_day_label(iso_date, index):
    """How the tab title names a day: "today", "tomorrow" or "Thursday".

    The same days the banner names, but without the banner's "on", because
    a title reads "Rain Thursday", not "Rain on Thursday".
    """
    if index == 0:
        return "today"
    if index == 1:
        return "tomorrow"
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return f"in {index} days"
    return WEEKDAY_NAMES[parsed.weekday()]


def tab_alert(forecast, remaining_hours=None):
    """What the tab title and the favicon should say about a forecast.

    Returns ``None`` when there is nothing worth alerting about, which is
    the case for a dry week, for an unreported week and for an error page.
    Otherwise it returns a dict with:

    ``when``
        how the day is named - "today", "tomorrow" or "Thursday";
    ``chance``
        the rain chance the alert is about.

    The title itself is put together by :func:`page_title`, which is the
    only place that builds one, so that the title a reader sees in the tab
    and the title a search engine shows in its results are the same title.

    The alert fires at ``UMBRELLA_THRESHOLD`` - the same threshold that
    puts the ☔ on a row and makes the banner say "Bring an umbrella." One
    threshold for all three means the tab, the banner and the row can never
    disagree about whether rain is worth noticing.

    Today is judged on the hours that are left, exactly as the banner
    judges it, so the title does not say "Rain today" at 18:00 when the
    morning's downpour has already been and gone. A day whose chance the
    service did not report is never counted as dry, so a quiet week with an
    unreported day is not "no rain" either - it simply has no alert.
    """
    if not forecast:
        return None

    for index, day in enumerate(forecast):
        chance = rain_chance(day.get("chance"))
        when = tab_day_label(day.get("iso_date"), index)
        if index == 0 and remaining_hours is not None:
            if not remaining_hours:
                # Today is over. The reader wants to know about the days
                # ahead, not about a day that has been and gone.
                continue
            remaining = remaining_hour_chance(remaining_hours)
            if remaining is not None:
                chance = remaining
        if chance is None:
            # An unreported day is not a dry day, so it is not an alert.
            continue
        if chance >= config.UMBRELLA_THRESHOLD:
            return {
                "when": when,
                "chance": chance,
            }
    return None


# --- The page's address and its metadata --------------------------------------
# A search engine finds the site by its pages, and it needs three things from
# each of them: a title that says what the page is about, a description that
# says the same thing in a sentence, and an address that is the page's own.
# The app has all three, and they are decided here, in one place, so that
# the title a reader sees in the tab and the title a search engine shows in
# its results can never drift apart.


def city_slug(value):
    """A URL-safe slug for a city name: "Sao Paulo" -> "sao-paulo".

    The accents are folded away and everything else that is not a letter or
    a digit becomes a dash, so the slug is safe in an address bar and in a
    file name. The name it stands for is looked up separately, because a
    slug cannot carry the punctuation a real name has.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def city_from_slug(slug):
    """The city a slug stands for.

    The curated list wins, because a slug cannot carry a city's accents or
    its punctuation and the geocoder needs the name. Anything else falls
    back to the slug with its dashes turned back into spaces, which is the
    name for every city whose name is made of letters and spaces.

    Only the first letter of that fallback name is capitalised: a name is
    not a sentence, and capitalising every word would turn "St John's" into
    "St John'S".
    """
    key = str(slug or "").strip().lower()
    if not key:
        return ""
    if key in CITY_SLUGS:
        return CITY_SLUGS[key]
    name = key.replace("-", " ")
    return name[:1].upper() + name[1:]


def city_path(city_name):
    """The address of a city's page.

    The address is made of the name the city was asked for, never of the
    name the geocoder answers with: the geocoder's own name is a full
    address ("London, United Kingdom"), and an address built from it would
    not be the same one the reader asked for.

    A city that is in the curated list keeps the slug the list gives it, so
    that the address in the city index, the address in the sitemap and the
    address the page claims for itself are the same one. Any other city
    gets a slug of its own.
    """
    name = str(city_name or "").strip()
    slug = CITY_NAMES.get(name.lower())
    if not slug:
        slug = city_slug(name)
    if not slug:
        return ""
    return f"/city/{slug}"


def short_city_name(city, display_city=None):
    """The city's own name, without the state and the country.

    The geocoder answers with a full address - "London, Greater London,
    England, United Kingdom" - which is more than a title or a heading can
    carry, and more than a reader scanning the page needs. The first part
    of it is the city.

    A city that is in the curated list keeps the name the list gives it,
    because the list has the name written the way it is usually written.
    """
    name = str(city or "").strip()
    if name.lower() in CITY_NAMES:
        return name
    if display_city:
        first = str(display_city).split(",")[0].strip()
        if first:
            return first
    return name


def page_title(city, alert=None):
    """The title of the page.

    The title is the alert: it names the first wet day, and the favicon
    changes with it. On a city's page the city is in the title as well,
    because a title that says only "Rain tomorrow" tells a reader - or a
    search engine - nothing about which city the page is about. The app's
    name stays a suffix, in the usual "page - site" order, so that a reader
    with a row of tabs open can still tell which one is Rain Alert.
    """
    if alert:
        when = alert["when"]
        if city:
            return f"{TAB_TITLE_PREFIX} {when} in {city} - {TAB_TITLE_SUFFIX}"
        return f"{TAB_TITLE_PREFIX} {when} - {TAB_TITLE_SUFFIX}"
    if city:
        return f"7-day rain chance for {city} - {TAB_TITLE_SUFFIX}"
    # The start page leads with the name, because there the name is what
    # the page is: a page for every city, not a page about one.
    return f"{TAB_TITLE_SUFFIX} - 7-day rain chance for any city"


def page_description(city=None, forecast=None, headline=None):
    """The description of the page: the sentence under the title in a search
    result.

    On a city's page it is the headline the page already shows, so that the
    snippet in the search results says the same thing as the page does.
    """
    if city and forecast:
        sentence = (f"The chance of rain in {city} for the next 7 days, "
                    f"hour by hour for today.")
        if headline:
            sentence += " " + headline["text"]
        return sentence
    if city:
        return (f"The 7-day rain chance for {city}: rain unlikely, rain "
                f"possible or rain likely for every day, and today's "
                f"forecast hour by hour.")
    return ("The chance of rain for the next seven days in any city, hour by "
            "hour for today. Rain unlikely, rain possible or rain likely, "
            "every day. Free, no signup.")


def canonical_url(path):
    """The absolute address of a page on this site."""
    return f"{config.SITE_URL}{path}"


def structured_data(city=None, forecast=None):
    """The page in a machine-readable form.

    Three things are described: the site, the app, and - on a city's page -
    the week itself, day by day. A search engine reads this to work out
    what the page is about, and a rich result may be built from it.
    """
    graph = [
        {
            "@type": "Organization",
            "@id": f"{config.SITE_URL}/#organization",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "logo": f"{config.SITE_URL}/static/icon-512.png",
        },
        {
            "@type": "WebSite",
            "@id": f"{config.SITE_URL}/#website",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "description": "The 7-day rain chance for any city.",
            "inLanguage": "en",
            "publisher": {"@id": f"{config.SITE_URL}/#organization"},
        },
        {
            "@type": "WebApplication",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "applicationCategory": "WeatherApplication",
            "operatingSystem": "Any",
            "description": page_description(),
            "offers": {
                "@type": "Offer",
                "price": "0",
                "priceCurrency": "EUR",
            },
        },
    ]
    if city and forecast:
        graph.append({
            "@type": "ItemList",
            "name": f"7-day rain chance for {city}",
            "numberOfItems": len(forecast),
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index + 1,
                    "item": {
                        "@type": "Thing",
                        "name": f"{day['date']}: {day['rain_sr_label']}",
                        "description": (f"{day['severity_label']}. "
                                        f"Temperature {day['temp_label']}."),
                    },
                }
                for index, day in enumerate(forecast)
            ],
        })
    return {"@context": "https://schema.org", "@graph": graph}


# --- Notifications -----------------------------------------------------------
# Two things are worth interrupting a reader for: rain in the hour they are
# in right now, and rain about to start. Everything else is either already on
# the page or too far away to be worth a notification.
#
# Each event carries a key. The browser keeps the keys of the events it has
# already shown, so the same rain is never announced twice, and a poll that
# lands in the same wet hour has nothing new to say.


def alert_threshold(personal):
    """The rain chance at which an alert is worth giving.

    The reader's own threshold is used when they have set one - it answers
    their question, not the app's. Without one, the app's umbrella threshold
    is used, which is the advice the rest of the page gives.

    The second value says which of the two it is, so the alert can say so:
    the reader's own limit and the app's advice never stand in for each
    other. A notification and a calendar export both use this, so the two
    always draw the line in the same place.
    """
    if personal is None or str(personal).strip() == "":
        return config.UMBRELLA_THRESHOLD, False
    try:
        value = int(str(personal).strip())
    except (TypeError, ValueError):
        return config.UMBRELLA_THRESHOLD, False
    return max(0, min(100, value)), True


def hour_moment(hour):
    """The local time of an hourly entry, as a datetime."""
    try:
        return datetime.fromisoformat(
            f"{hour.get('day')}T{int(hour.get('hour', 0)):02d}:00")
    except (TypeError, ValueError):
        return None


def notification_body(chance, city, when, threshold, personal):
    """The sentence under a notification's title."""
    percent = round_half_up(chance)
    sentence = f"{percent}% chance of rain in {city} {when}."
    if personal:
        # The reader's own limit, in their own words. The umbrella is the
        # app's advice and belongs to the page, not to this notification.
        sentence += f" Above your {threshold}% threshold."
    elif percent >= config.UMBRELLA_THRESHOLD:
        sentence += " Bring an umbrella."
    return sentence


def notification_event(hours, threshold, city, personal=False):
    """The one notification worth showing right now, or ``None``.

    Rain in the current hour is worth interrupting the reader for: it is
    happening now, and the umbrella is the answer to it. The key is the day,
    so a wet afternoon is announced once and not once an hour.

    Rain further ahead is only worth a notification once it is close enough
    to act on. The first wet hour within ``NOTIFICATION_LEAD_HOURS`` is the
    one, and its key is the hour, so the same rain is not announced twice
    when the forecast shifts a little.

    A day the service did not report is never a wet hour: an unknown chance
    is not a chance of anything.
    """
    entries = [hour for hour in (hours or []) if hour.get("day")]
    remaining = [hour for hour in entries if not hour.get("past")]
    if not remaining:
        return None

    current = remaining[0]
    current_moment = hour_moment(current)
    if current_moment is None:
        return None

    current_chance = rain_chance(current.get("chance"))
    if current_chance is not None and current_chance >= threshold:
        return {
            "key": f"now:{current.get('day')}",
            "title": f"{severity_label(severity_band(current_chance))} right now",
            "body": notification_body(
                current_chance, city, "right now", threshold, personal),
        }

    for hour in remaining[1:]:
        chance = rain_chance(hour.get("chance"))
        if chance is None or chance < threshold:
            continue
        moment = hour_moment(hour)
        if moment is None:
            continue
        lead = (moment - current_moment).total_seconds() / 3600
        if lead > config.NOTIFICATION_LEAD_HOURS:
            # Too far off to be worth saying now. A later poll catches it
            # as it comes closer, because the hours are in order.
            break
        label = hour.get("time_label") or f"{moment.hour:02d}:00"
        return {
            "key": f"hour:{hour.get('day')}T{int(hour.get('hour', 0)):02d}:00",
            "title": f"{severity_label(severity_band(chance))} from {label}",
            "body": notification_body(
                chance, city, f"at {label}", threshold, personal),
        }
    return None


# --- Calendar export ---------------------------------------------------------
# Tier 2, the last browser-side piece: the rainy days in the reader's own
# calendar. The calendar app then does the alerting, which is the point of
# it - RainAlert needs no server, no account and no scheduler for the
# reader to be told about rain, because software they already have does the
# telling.
#
# The file is built here rather than in the browser, so the rule that decides
# which days go into it is one piece of code with the offline test suite
# behind it. The browser's part is narrow: it says which threshold the
# reader is using, and it keeps the link away when there is nothing to
# export.

# The name the calendar gets in the reader's calendar app.
CALENDAR_NAME = "Rain forecast"

# The namespace the event ids live in. An event id has to be unique for
# ever, so that importing the file again updates the same events instead of
# adding a second copy of every one of them.
CALENDAR_UID_DOMAIN = "rainalert.live"

# The longest a content line may be, in octets. RFC 5545 asks for 75.
CALENDAR_LINE_OCTETS = 75


def calendar_escape(value):
    """Escape a value for an iCalendar text property.

    Four characters have to be escaped in a text value: the backslash, the
    semicolon, the comma and the newline. A city name with a comma in it
    would otherwise split the value in two, and a line break inside a
    description would end the line early.
    """
    text = str(value if value is not None else "")
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return text


def calendar_fold(line, limit=CALENDAR_LINE_OCTETS):
    """Fold a content line to the length RFC 5545 asks for.

    A long description has to be split over several lines, and every line
    after the first starts with a space. The split is counted in octets
    rather than in characters, so a name with an umlaut in it is never cut
    in half.
    """
    parts = []
    current = ""
    size = 0
    for character in line:
        width = len(character.encode("utf-8"))
        if size + width > limit:
            parts.append(current)
            # The space that marks the continuation is part of the line, so
            # the content after it gets one octet less.
            current = " "
            size = 1
        current += character
        size += width
    parts.append(current)
    return "\r\n".join(parts)


def calendar_day(iso_date):
    """An ISO date as an iCalendar date: ``2026-10-21`` -> ``20261021``.

    An empty string means the date could not be read, and the day is left
    out of the file rather than written as a broken date.
    """
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return ""
    return parsed.strftime("%Y%m%d")


def calendar_next_day(iso_date):
    """The day after the given one, for the end of an all-day event.

    The end of an all-day event is the start of the next day, and that day
    is not part of the event.
    """
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return ""
    return (parsed + timedelta(days=1)).strftime("%Y%m%d")


def calendar_slug(city):
    """A short, safe name for the file and for the event ids."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(city or "").lower()).strip("-")
    return slug[:40] or "forecast"


def calendar_days(forecast, threshold):
    """The days of the forecast that reach the threshold.

    The number that is compared is the number the page shows, so the
    calendar and the list can never disagree about which days are wet. A
    day the service did not report is never one of them: an unknown chance
    is not a chance of anything.
    """
    days = []
    for day in forecast or []:
        chance = day.get("chance_number")
        if chance is None:
            chance = chance_number(day.get("chance"))
        if chance is None or chance < threshold:
            continue
        days.append(day)
    return days


def calendar_summary(day):
    """The title of an event: the day's own band and its chance.

    The band is the one the row in the list carries, so the calendar and
    the page never disagree about how wet a day is.
    """
    band = day.get("severity") or severity_band(day.get("chance"))
    chance = day.get("chance_number")
    if chance is None:
        chance = chance_number(day.get("chance")) or 0
    return f"{severity_label(band)} - {chance}% chance of rain"


def calendar_description(day, city, threshold, personal):
    """The body of an event: the chance, the city and the threshold.

    The threshold is named, and it is named as the reader's own when they
    have set one, so the event says which answer it is answering. The
    umbrella belongs to the app's advice and is not mixed into the
    reader's own limit, exactly as in the notifications.
    """
    chance = day.get("chance_number")
    if chance is None:
        chance = chance_number(day.get("chance")) or 0
    lines = [f"{chance}% chance of rain in {city} on {day.get('date')}."]
    if personal:
        lines.append(f"At or above your {threshold}% alert threshold.")
    else:
        lines.append("Bring an umbrella.")
    lines.append("Weather data by Open-Meteo.com (CC BY 4.0).")
    return "\n".join(lines)


def build_calendar(forecast, city, threshold, personal=False, now=None):
    """The whole calendar file, as text.

    One all-day event per day that reaches the threshold. The events are
    all-day events because the forecast is a daily maximum: the file says
    which days are wet, and the reader's own calendar app decides when to
    remind them about it.
    """
    days = calendar_days(forecast, threshold)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RainAlert//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{calendar_escape(f'{CALENDAR_NAME} - {city}')}",
    ]
    for day in days:
        start = calendar_day(day.get("iso_date"))
        if not start:
            # A day the service dated unreadably is left out rather than
            # written as a broken date.
            continue
        end = calendar_next_day(day.get("iso_date"))
        uid = f"rainalert-{calendar_slug(city)}-{start}@{CALENDAR_UID_DOMAIN}"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{calendar_escape(uid)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{calendar_escape(calendar_summary(day))}",
            "DESCRIPTION:"
            f"{calendar_escape(calendar_description(day, city, threshold, personal))}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(calendar_fold(line) for line in lines) + "\r\n"


def calendar_failure(message, status):
    """A plain-text answer for a request that cannot be answered.

    The export is a download, so there is no page to render: the reader
    gets a sentence and a status code instead of a broken calendar.
    """
    response = Response(message, status=status, mimetype="text/plain")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


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

    daily = payload.get("daily") or {}
    dates = daily.get("time") or daily.get("time_string") or []
    chances = daily.get("precipitation_probability_max") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    amounts = daily.get("precipitation_sum") or []
    hours_of_rain = daily.get("precipitation_hours") or []

    # The hours of every day, split by the day they fall on. The strip draws
    # the day the reader picks, so the hours have to be grouped before the
    # days are built.
    try:
        hourly_days = parse_hourly_days(payload)
    except (TypeError, ValueError) as exc:
        # A missing hourly strip is a missing feature, not a broken forecast.
        app.logger.warning("Hourly forecast could not be parsed: %s", exc)
        hourly_days = []
    hours_by_date = {day: hours for day, hours in hourly_days}

    forecast = []
    for index, (day, chance) in enumerate(zip(dates, chances)):
        band = severity_band(chance)
        weekday_short, date_short = format_date_parts(day)
        day_name = day_panel_name(day, index)
        when, when_summary = day_phrases(index, day_name)
        day_hours = hours_by_date.get(day) or []
        forecast.append({
            "date": format_date(day),
            # The raw date, kept so the headline can name the weekday without
            # having to take the formatted date apart again.
            "iso_date": day,
            # The short forms, for the week that is a row of seven narrow
            # columns. The long date is still on the page, for screen
            # readers.
            "weekday_short": weekday_short,
            "date_short": date_short,
            # The visible number, and the full phrase for the screen reader.
            # The column heading above the list says "chance of rain" once.
            "rain_label": format_rain_chance(chance),
            "rain_sr_label": describe_rain_chance(chance),
            "temp_label": format_temperature(
                highs[index] if index < len(highs) else None,
                lows[index] if index < len(lows) else None,
            ),
            # What the day panel says about this day: which day it is, how
            # much rain falls in it and how long it lasts. The panel is
            # built from the same chance the column shows, so the two can
            # never disagree.
            "day_name": day_name,
            "day_label": f"{day_name} {date_short}".strip(),
            "chance_label": (
                f"{chance_number(chance)}% chance of rain"
                if chance_number(chance) is not None
                else ""
            ),
            "amount_label": format_precipitation(
                amounts[index] if index < len(amounts) else None),
            "hours_label": format_rain_hours(
                hours_of_rain[index] if index < len(hours_of_rain) else None),
            "chance": chance,
            # The number the row shows, and the number a personal alert
            # threshold in the browser is compared against. The browser
            # reads it from the markup, so the threshold and the number on
            # the page are always the same value.
            "chance_number": chance_number(chance),
            "severity": band,
            "severity_label": severity_label(band),
            # The panel names the band in words. A day the service did not
            # report is named as such, and the panel leaves the figures out
            # altogether: a day with no chance reported is never counted as
            # a dry one.
            "band_label": ("Rain not reported" if band == "unknown"
                           else severity_label(band)),
            "umbrella": needs_umbrella(chance),
            # The hours of this day, for the strip the reader can pick.
            # The strip and the panel are the same day, so the two can
            # never be about different days.
            "hours": day_hours,
            # The title the strip carries while this day is the one that
            # shows, and the sentence under it.
            "hourly_title": f"{day_name}, hour by hour",
            "hourly_summary": (summarise_hours(day_hours, when_summary)
                               if day_hours else ""),
            # How a caption names this day.
            "day_when": when,
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
def inject_site_info():
    """Make the donation link and the build's identity available to every
    template.

    They are read from the module on each request, not copied at import
    time, so a test can switch the donation link on and off.
    """
    return {
        "donation_url": config.DONATION_URL,
        "app_version": config.APP_VERSION,
        "app_commit": config.APP_COMMIT,
    }


def temperature_unit_from_request():
    """The temperature scale this request asks for.

    The unit comes from the query string on a GET and from the form on a
    POST. Anything unrecognised falls back to the default rather than
    failing: a stray query parameter should not break the page.
    """
    source = request.form if request.method == "POST" else request.args
    unit = (source.get("unit") or "").strip().lower()
    if unit in config.TEMPERATURE_UNITS:
        return unit
    return config.DEFAULT_TEMPERATURE_UNIT


@app.route('/', methods=['GET', 'POST'])
def index():
    """The start page, and the result of a search.

    A POST carries the city in the form; a GET carries it in the query
    string, which is how the temperature switch and the browser's own
    remembered city ask for the same forecast. Either way the page is the
    same page, and the city it is about has an address of its own that the
    page points at.

    A GET with a city is sent on to that address. A city has one address,
    and it is the one a reader can share, bookmark and a search engine can
    index; the query string is only ever the way in. The redirect is
    permanent, because the city page is the address from now on, and it
    costs nothing: the address is worked out before the forecast is
    fetched, so the extra hop asks the server for no more than a header.
    """
    source = request.form if request.method == 'POST' else request.args
    city = (source.get('city') or '').strip()
    unit = temperature_unit_from_request()
    if request.method == 'POST' and not city:
        return render_forecast_page(
            "", unit, error="Please enter a city name.")
    if request.method == 'GET' and city:
        target = city_path(city)
        if target:
            if unit != config.DEFAULT_TEMPERATURE_UNIT:
                target += f"?unit={unit}"
            return redirect(target, code=301)
    return render_forecast_page(city, unit)


def render_forecast_page(city, unit, city_page=False, error=None, status=200):
    """The page: the start page, a forecast, or a message.

    Every page of the site is rendered here, whichever address it was asked
    for, so that the title, the description, the canonical link and the
    structured data are decided in one place and cannot disagree with each
    other.

    ``city_page`` says that the page was asked for at a city's own address.
    That makes the difference between a page that is missing - a city
    nobody knows, which answers ``404`` - and a search that did not work,
    which answers ``200`` and says what went wrong.
    """
    weather_data = None
    hourly_data = None
    headline = None
    display_city = None
    alert = None

    if error is None and city:
        try:
            latitude, longitude, display_city = get_coordinates(city)
            weather_data, hourly_data = fetch_weather(
                latitude, longitude, unit)
            # The umbrella advice is about the hours ahead, so the
            # headline is told which of today's hours are still to come.
            remaining_hours = [hour for hour in (hourly_data or [])
                               if not hour.get("past")]
            headline = forecast_headline(
                weather_data or [], remaining_hours)
            # The tab title and the favicon are the same alert as the
            # banner, decided by the same threshold, so they can never
            # disagree with it.
            alert = tab_alert(weather_data or [], remaining_hours)
        except CityNotFound:
            error = "City not found. Please try a different name (e.g., 'Paris')."
            if city_page:
                # A city's page that names a city nobody knows is a missing
                # page, and says so with its status code. A page that says
                # "not found" but answers 200 is a soft 404, and search
                # engines treat it as one.
                status = 404
        except GeocodingUnavailable:
            app.logger.warning("Geocoding service unavailable for %r", city)
            error = ("The geocoding service is unavailable right now. "
                     "Please try again in a moment.")
            if city_page:
                # The upstream is down, not the page: 503 says "come back
                # later" and keeps the address out of the index for now.
                status = 503
        except WeatherUnavailable:
            app.logger.warning("Forecast service unavailable for %r", city)
            error = ("The weather service is unavailable right now. "
                     "Please try again in a moment.")
            if city_page:
                status = 503

    # The saved city and the personal alert threshold live in the browser's
    # localStorage, so the server has to tell the page what kind of page it
    # is. A start page - no city at all - may load a remembered city by
    # itself; any other page already shows what the reader came for, and
    # reloading it would throw their forecast away.
    autoload = not city and error is None

    # The strip draws the day the reader picks, so it needs at least one day
    # that has hours in it. A forecast without any hourly data has no graph
    # at all, and says nothing about one.
    has_hourly = any(day.get("hours") for day in (weather_data or []))

    # How many days the app's own threshold would put into a calendar. The
    # browser uses it to decide whether the export link is worth offering:
    # a link that would download an empty calendar is not an offer.
    calendar_days_count = len(
        calendar_days(weather_data or [], config.UMBRELLA_THRESHOLD))

    # Whether the page carries a forecast, an error, or nothing at all. The
    # browser uses it to decide whether a search that was just submitted
    # should be remembered: only a search that worked is worth remembering.
    if error:
        search_status = "error"
    elif weather_data:
        search_status = "ok"
    else:
        search_status = "none"

    # The address this page claims for itself. A forecast has an address of
    # its own, so that a city is one page and not many; the start page is
    # the site itself.
    canonical_path = city_path(city) if city else "/"

    # The name the page calls the city by: the city on its own, without the
    # state and the country the geocoder adds.
    page_city = short_city_name(city, display_city)

    title = page_title(page_city, alert)
    description = page_description(page_city, weather_data, headline)
    # A page with an error on it is not worth indexing: there is no
    # forecast on it, and indexing it would fill the results with pages
    # that say nothing.
    robots = ("noindex, follow" if error
              else "index, follow, max-image-preview:large")

    # The temperature switch asks for the same page in the other scale, so
    # the links point at the page's own address and keep the unit.
    unit_links = {option: f"{canonical_path}?unit={option}"
                  for option in config.TEMPERATURE_UNITS}

    response = make_response(render_template(
        'index.html',
        weather_data=weather_data,
        has_hourly=has_hourly,
        headline=headline,
        error=error,
        city=city,
        display_city=display_city or city,
        page_city=page_city,
        unit=unit,
        temperature_units=config.TEMPERATURE_UNITS,
        unit_links=unit_links,
        page_title=title,
        page_description=description,
        canonical_url=canonical_url(canonical_path),
        robots=robots,
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(page_city, weather_data),
        favicon=(FAVICON_RAIN if alert else FAVICON_DEFAULT),
        autoload=autoload,
        search_status=search_status,
        calendar_days=calendar_days_count,
    ))
    response.status_code = status
    return response


@app.route('/city/<path:city_slug>')
def city_page(city_slug):
    """The forecast for one city, at the city's own address.

    Every city has one address, and that address is the canonical one: the
    page says so with a canonical link, so a search engine indexes the
    city's page rather than the many ways of asking for the same forecast.
    An address that is not the canonical one is sent there for good, so
    that "/city/London" and "/city/london" are one page and not two.

    A city that the geocoder does not know is a ``404`` and not a page with
    a message on it, because a page that says "not found" but answers
    ``200`` is a soft 404 and search engines treat it as one.
    """
    city = city_from_slug(city_slug)
    if not city:
        abort(404)
    canonical = city_path(city)
    if request.path != canonical:
        return redirect(canonical, code=301)
    return render_forecast_page(city, temperature_unit_from_request(),
                                 city_page=True)


@app.route('/cities')
def cities_index():
    """The index of the cities the site has a page for.

    It is the front door of the crawlable part of the site: every city on
    it has a page of its own, and the links on it are how a crawler finds
    them. The list is short on purpose - the geocoder is rate-limited, and
    every address here is a forecast the app has to fetch.
    """
    return render_template(
        'cities.html',
        page_title="Rain forecasts by city - Rain Alert",
        page_description=("The 7-day rain chance for a city: rain unlikely, "
                          "rain possible or rain likely for every day, and "
                          "today's forecast hour by hour."),
        canonical_url=canonical_url("/cities"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
        cities=[{"slug": slug, "name": name} for slug, name in CURATED_CITIES],
    )


@app.route('/release-notes')
def release_notes():
    """What each release brought.

    The notes are written by hand, in `rainalert/data/releases.py`, the
    same way the API reference is: they describe the app rather than being
    generated from it. The page is a page like any other, with the same panel and the
    same background, and the footer links to it from everywhere else.
    """
    return render_template(
        'release_notes.html',
        page_title="Release notes - Rain Alert",
        page_description=("What changed in each release of Rain Alert: the "
                          "night street page, the calendar export, the "
                          "browser notification and the installable app."),
        canonical_url=canonical_url("/release-notes"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
        releases=RELEASES,
    )


@app.route('/robots.txt')
def robots():
    """Where the crawlers may go.

    The alert poll and the calendar export are not pages, and fetching them
    costs two upstream requests each, so they are kept out of the crawl. The
    sitemap says where the pages are.
    """
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "Disallow: /calendar.ics",
        "",
        f"Sitemap: {canonical_url('/sitemap.xml')}",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route('/sitemap.xml')
def sitemap():
    """The pages of the site, for the crawlers.

    The home page and the city index are here, and so is every city that
    has a page of its own. The dates are today's, because the forecast on
    every one of these pages changes.
    """
    today = date.today().isoformat()
    urls = [
        ("/", "1.0", "daily"),
        ("/cities", "0.8", "weekly"),
        ("/release-notes", "0.4", "monthly"),
    ]
    for slug, _name in CURATED_CITIES:
        urls.append((f"/city/{slug}", "0.7", "daily"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, changefreq in urls:
        body.extend([
            "  <url>",
            f"    <loc>{canonical_url(path)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
    body.append("</urlset>")
    return Response("\n".join(body) + "\n", mimetype="application/xml")


@app.errorhandler(404)
def page_not_found(error):
    """The page for an address that is not on this site.

    A real ``404`` with a search form on it, rather than Flask's bare
    error page: a crawler that lands on a missing address should be told
    so clearly, and a reader who mistyped one should be able to search
    from there.
    """
    response = make_response(render_template(
        '404.html',
        page_title="Page not found - Rain Alert",
        page_description=("The 7-day rain chance for any city: rain "
                          "unlikely, rain possible or rain likely for every "
                          "day, and today's forecast hour by hour."),
        canonical_url=canonical_url("/"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
    ), 404)
    return response


def noindex(response):
    """Keep a response out of the search results.

    The alert poll and the calendar export are not pages: they are an
    endpoint the page uses and a file the page hands over. Indexing either
    of them would put a JSON blob or a download in the results, and
    crawling them costs two upstream requests each.
    """
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.route('/api/alert')
def api_alert():
    """What the browser should tell the reader, if anything.

    The page polls this every ``NOTIFICATION_POLL_MINUTES`` while it is
    open. The answer is one event at most - the one thing worth interrupting
    the reader for - and the browser keeps the keys of the events it has
    already shown, so the same news is never announced twice.

    The city comes from the page, so the reader never has to type it again.
    The threshold is the reader's own, and is optional: without one the
    app's umbrella threshold is used, which is the advice the page gives.
    """
    city = (request.args.get('city') or '').strip()
    if not city:
        return noindex(jsonify(
            {"error": "Please enter a city name."})), 400

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        _, hours = fetch_weather(latitude, longitude)
    except CityNotFound:
        return noindex(jsonify({
            "error": "City not found. Please try a different name "
                     "(e.g., 'Paris')."})), 404
    except GeocodingUnavailable:
        app.logger.warning("Geocoding service unavailable for %r", city)
        return noindex(jsonify({
            "error": "The geocoding service is unavailable right now."})), 503
    except WeatherUnavailable:
        app.logger.warning("Forecast service unavailable for %r", city)
        return noindex(jsonify({
            "error": "The weather service is unavailable right now."})), 503

    remaining = [hour for hour in (hours or []) if not hour.get("past")]
    now = remaining[0].get("time_label") if remaining else None
    return noindex(jsonify({
        "city": display_city,
        "now": now,
        "threshold": threshold,
        "personal_threshold": personal,
        "lead_hours": config.NOTIFICATION_LEAD_HOURS,
        "poll_minutes": config.NOTIFICATION_POLL_MINUTES,
        "event": notification_event(hours, threshold, display_city, personal),
    }))


@app.route('/calendar.ics')
def calendar_export():
    """The rainy days as a calendar file the reader can import.

    The city comes from the page, and the threshold is the reader's own
    when they have set one - the same split the notifications use, for the
    same reason. Without a threshold the app's umbrella threshold is used,
    which is the advice the rest of the page gives.

    The file is built here, on the server, so the rule that decides which
    days go into it is one piece of code with the offline test suite
    behind it, and not a string in the browser's script.
    """
    city = (request.args.get('city') or '').strip()
    if not city:
        return calendar_failure("Please enter a city name.", 400)

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        forecast = fetch_forecast(latitude, longitude)
    except CityNotFound:
        return calendar_failure(
            "City not found. Please try a different name (e.g., 'Paris').", 404)
    except GeocodingUnavailable:
        app.logger.warning("Geocoding service unavailable for %r", city)
        return calendar_failure(
            "The geocoding service is unavailable right now.", 503)
    except WeatherUnavailable:
        app.logger.warning("Forecast service unavailable for %r", city)
        return calendar_failure(
            "The weather service is unavailable right now.", 503)

    body = build_calendar(forecast, display_city, threshold, personal)
    response = Response(body, mimetype="text/calendar")
    response.headers['Content-Disposition'] = (
        f'attachment; filename="rain-alert-{calendar_slug(display_city)}.ics"')
    # The file holds a forecast, so it is never a copy of an old one.
    response.headers['Cache-Control'] = 'no-store'
    # It is a download, not a page: it has no business in the results.
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@app.route('/manifest.json')
def manifest():
    """The web app manifest, so the site can be installed on a phone.

    It is served from the root so that its scope can be the whole site:
    the page is at "/", the alert poll is at "/api/alert" and the worker is
    at "/service-worker.js", and a manifest served from a subdirectory
    would default to a scope of that subdirectory.
    """
    response = send_from_directory(app.static_folder, 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    # The manifest names the icons and the colours of the installed app, so
    # a changed one has to reach the phone straight away.
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/service-worker.js')
def service_worker():
    """The service worker, served from the root so that it covers the app.

    A worker served from "/static/" would only control "/static/", so it
    is served from the root instead. The Service-Worker-Allowed header is
    belt and braces: the scope of a worker is its own path unless the
    server widens it.
    """
    response = send_from_directory(app.static_folder, 'service-worker.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    # A worker that is cached is a worker that never updates.
    response.headers['Cache-Control'] = 'no-cache'
    return response


if __name__ == '__main__':
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
