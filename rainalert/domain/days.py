"""How the app names a day of the forecast.

There is one rule: the first day is today and the second is tomorrow, in
the city's local time - the same local time the week is dated in - and
every later day is named by its English weekday. The banner, the tab title,
the day panel and the hourly summary all name days by it, in the form each
of them needs, so they can never call different days "today".
"""

from datetime import date

# The seven weekday names, Monday first, matching date.weekday().
#
# They are hard-coded rather than taken from strftime("%A"), because
# strftime reads the process-wide LC_TIME locale: on a German Windows
# machine, or in a container with LANG set, it would render the weekday in
# that language. The rest of the page is English, so a half-translated date
# would be worse than a consistently English one.
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday")

# The forms a day's name takes. The first two days have names of their
# own; the rest are their weekday, with what the form puts around it.
#
#   panel    the day panel's heading     Today    Tomorrow   Friday
#   tab      the tab title               today    tomorrow   Friday
#   caption  a sentence about the day    today    tomorrow   on Friday
#   summary  the hourly summary          for the rest of today
#                                                 tomorrow   on Friday
#
# The summary of the day that is running says "for the rest of today",
# because only that day has hours left to come. The tab title says "Rain
# Friday", not "Rain on Friday".
FORMS = {
    "panel": ("Today", "Tomorrow", "{weekday}"),
    "tab": ("today", "tomorrow", "{weekday}"),
    "caption": ("today", "tomorrow", "on {weekday}"),
    "summary": ("for the rest of today", "tomorrow", "on {weekday}"),
}


def weekday_name(iso_date):
    """The English weekday of an ISO date, or ``None`` when it is unreadable."""
    try:
        parsed = date.fromisoformat(str(iso_date))
    except (TypeError, ValueError):
        return None
    return WEEKDAY_NAMES[parsed.weekday()]


def day_name(iso_date, index, form="caption"):
    """The name of the day at ``index`` in the week, in the given form.

    A later day whose date cannot be read is named by how far off it is -
    "in 3 days" - rather than by a weekday nobody knows. The panel, which
    puts the name in a heading, leaves it empty instead.
    """
    first, second, later = FORMS[form]
    if index == 0:
        return first
    if index == 1:
        return second
    weekday = weekday_name(iso_date)
    if weekday is None:
        return "" if form == "panel" else f"in {index} days"
    return later.format(weekday=weekday)
