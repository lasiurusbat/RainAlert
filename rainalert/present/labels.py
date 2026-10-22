"""The words and figures the page shows: dates, chances, amounts, bands.

Every visible label is made here, from the values the rules in
:mod:`rainalert.domain.rain` decide on, so a label never makes a decision
of its own.
"""

from datetime import date

from rainalert.domain.rain import rain_chance, round_half_up


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


# The bar height in the strip, in percent per step. The height is bucketed
# into steps so it can live in the stylesheet as a class rather than as an
# inline style; the exact percentage travels in the tooltip and in the
# screen-reader text.
HOUR_HEIGHT_STEP = 5


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
