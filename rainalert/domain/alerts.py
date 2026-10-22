"""What is worth telling a reader about: the banner, the tab title, the
hourly summary and the notification.

Both read :class:`~rainalert.domain.model.Hour` objects, so the rule is
decided on the forecast itself and not on the dicts the page is rendered
from. The thresholds are read from :mod:`rainalert.config` each time.
"""

from rainalert import config
from rainalert.domain.days import day_name
from rainalert.domain.rain import (rain_chance, round_half_up, severity_band,
                                   severity_label)


def clock(hour):
    """The hour as a clock time, "09:00"."""
    return f"{hour.moment.hour:02d}:00"


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
    upcoming = [hour for hour in hours if not hour.past]
    if not upcoming:
        return ""

    # Group the wet hours into contiguous windows.
    windows = []
    window = []
    for hour in upcoming:
        probability = rain_chance(hour.chance)
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
    bands = [severity_band(hour.chance) for hour in first]
    band = "high" if "high" in bands else "moderate"
    # A window only holds hours whose chance is a number at or above the
    # threshold, so the band is never "unknown" here: an unknown chance is
    # not a wet hour, but it is also not a dry one, and it never enters a
    # window at all.
    peak = max(rain_chance(hour.chance) or 0 for hour in first)
    if len(first) == 1:
        span = f"at about {clock(first[0])}"
    else:
        span = f"from about {clock(first[0])} to {clock(first[-1])}"

    sentence = f"{severity_label(band).lower()} {span}, up to {round_half_up(peak)}%"
    if len(windows) > 1:
        sentence += ", and at other times too"

    return f"{sentence[0].upper()}{sentence[1:]}. Bring an umbrella."


# --- Notifications -----------------------------------------------------------
# Two things are worth interrupting a reader for: rain in the hour they are
# in right now, and rain about to start. Everything else is either already on
# the page or too far away to be worth a notification.
#
# Each event carries a key. The browser keeps the keys of the events it has
# already shown, so the same rain is never announced twice, and a poll that
# lands in the same wet hour has nothing new to say.


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
    remaining = [hour for hour in (hours or []) if not hour.past]
    if not remaining:
        return None

    current = remaining[0]
    current_chance = rain_chance(current.chance)
    if current_chance is not None and current_chance >= threshold:
        return {
            "key": f"now:{current.day}",
            "title": f"{severity_label(severity_band(current_chance))} right now",
            "body": notification_body(
                current_chance, city, "right now", threshold, personal),
        }

    for hour in remaining[1:]:
        chance = rain_chance(hour.chance)
        if chance is None or chance < threshold:
            continue
        lead = (hour.moment - current.moment).total_seconds() / 3600
        if lead > config.NOTIFICATION_LEAD_HOURS:
            # Too far off to be worth saying now. A later poll catches it
            # as it comes closer, because the hours are in order.
            break
        label = clock(hour)
        return {
            "key": f"hour:{hour.day}T{label}",
            "title": f"{severity_label(severity_band(chance))} from {label}",
            "body": notification_body(
                chance, city, f"at {label}", threshold, personal),
        }
    return None


# --- Today, and the first wet day ---------------------------------------------
# The banner and the tab title are one alert, and this is the rule they
# share. Today is judged on the hours that are left rather than on the daily
# maximum: the maximum covers the whole day, so at 18:00 it still counts the
# morning's downpour while the reader can only walk into the evening. A
# today with no hours left drops out entirely, and a day the service did not
# report is never counted as dry.


def remaining_hour_chance(hours):
    """The highest rain chance among the hours that are still to come.

    ``None`` means the service reported no usable value for any of them.
    """
    chances = [rain_chance(hour.chance) for hour in hours or []]
    known = [chance for chance in chances if chance is not None]
    if not known:
        return None
    return max(known)


def judge_days(days, remaining_hours=None):
    """Each day of the week with the chance it is judged on.

    Returns the judged days, as ``(index, day, chance, by_hours)`` tuples,
    and whether today is over. ``chance`` is ``None`` for a day the service
    did not report. ``by_hours`` says the chance is today's remaining hours
    rather than the daily maximum, so the sentence can say which it is.

    ``remaining_hours`` are today's hours that have not happened yet;
    ``None`` means there is no hourly data, and today is judged on its daily
    maximum like any other day.
    """
    judged = []
    today_over = False
    for index, day in enumerate(days or []):
        chance = rain_chance(day.chance)
        if index == 0 and remaining_hours is not None:
            if not remaining_hours:
                # Today is over. The reader wants to know about the days
                # ahead, not about a day that has been and gone.
                today_over = True
                continue
            remaining = remaining_hour_chance(remaining_hours)
            if remaining is not None:
                judged.append((index, day, remaining, True))
                continue
        judged.append((index, day, chance, False))
    return judged, today_over


def first_wet_day(judged):
    """The first judged day at or above the umbrella threshold, or ``None``.

    The same threshold puts the umbrella on a day's column, so the banner,
    the tab and the week never disagree about whether rain is worth
    noticing.
    """
    return next((entry for entry in judged
                 if entry[2] is not None
                 and entry[2] >= config.UMBRELLA_THRESHOLD), None)


def _when(entry):
    """How a sentence names a judged day."""
    index, day, _, by_hours = entry
    if by_hours:
        return "for the rest of today"
    return day_name(day.iso_date, index, "caption")


# --- The headline ------------------------------------------------------------
# One line above the daily list that says what the week looks like. It names
# the first day worth mentioning: a day that reaches the umbrella threshold,
# a day that is merely possible, or the week as a whole when no day is.
#
# The band name in the sentence is the same one the row in the list carries,
# so the banner and the list never disagree about how wet a day is.


def forecast_headline(days, remaining_hours=None):
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

    Today is judged on the hours that are left (see :func:`judge_days`),
    and the sentence says which figure it is using: "Rain likely for the
    rest of today (80%)." The hourly figures and the daily figure are two
    different quantities, and each one is labelled with which it is.

    A day whose chance the service did not report is never counted as dry.
    When the week is quiet but some days are unreported, the sentence says
    "most of" rather than claiming the whole week is dry - and when more of
    the week is unreported than is known to be dry, it says the chance is
    unknown instead, because "no rain likely for most of" would be a claim
    about days nobody reported.
    """
    if not days:
        return None

    judged, today_over = judge_days(days, remaining_hours)
    known = [entry for entry in judged if entry[2] is not None]
    wet = first_wet_day(judged)
    possible = next((entry for entry in known
                     if severity_band(entry[2]) == "moderate"), None)

    if wet is not None:
        band = severity_band(wet[2])
        return {
            "text": f"{_headline_sentence(band, _when(wet), wet[2])} Bring an umbrella.",
            "severity": band,
            "umbrella": True,
        }

    if possible is not None:
        band = severity_band(possible[2])
        return {
            "text": _headline_sentence(band, _when(possible), possible[2]),
            "severity": band,
            "umbrella": False,
        }

    count = len(judged)
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


def tab_alert(days, remaining_hours=None):
    """What the tab title and the favicon should say about a forecast.

    Returns ``None`` when there is nothing worth alerting about, which is
    the case for a dry week, for an unreported week and for an error page.
    Otherwise it returns a dict with:

    ``when``
        how the day is named - "today", "tomorrow" or "Thursday";
    ``chance``
        the rain chance the alert is about.

    The title itself is put together by ``page_title``, which is the only
    place that builds one, so that the title a reader sees in the tab and
    the title a search engine shows in its results are the same title.

    The day is the banner's own first wet day (:func:`first_wet_day`), so
    the tab and the banner can never disagree about whether rain is worth
    noticing, or about which day it falls on.
    """
    wet = first_wet_day(judge_days(days, remaining_hours)[0])
    if wet is None:
        return None
    index, day, chance, _ = wet
    return {
        "when": day_name(day.iso_date, index, "tab"),
        "chance": chance,
    }
