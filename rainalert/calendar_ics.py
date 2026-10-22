"""The rainy days as an iCalendar file (RFC 5545).

Tier 2, the last browser-side piece: the rainy days in the reader's own
calendar. The calendar app then does the alerting, which is the point of
it - RainAlert needs no server, no account and no scheduler for the reader
to be told about rain, because software they already have does the telling.

The file is built here rather than in the browser, so the rule that decides
which days go into it is one piece of code with the offline test suite
behind it. The browser's part is narrow: it says which threshold the reader
is using, and it keeps the link away when there is nothing to export.

Nothing here knows about HTTP; the route that serves the file lives with
the other routes.
"""

import re
from datetime import date, datetime, timedelta, timezone

from rainalert.domain.rain import chance_number, severity_band, severity_label


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
