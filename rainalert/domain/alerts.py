"""What is worth telling a reader about: the hourly summary and the
notification.

Both read :class:`~rainalert.domain.model.Hour` objects, so the rule is
decided on the forecast itself and not on the dicts the page is rendered
from. The thresholds are read from :mod:`rainalert.config` each time.
"""

from rainalert import config
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
    if all(each == "unknown" for each in bands):
        # An unknown chance is not a wet hour, but it is also not a dry one,
        # so it is never called "possible" or "likely".
        band = "unknown"
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
