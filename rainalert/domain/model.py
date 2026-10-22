"""The forecast as the app understands it, before any of it is worded.

The service answers with parallel arrays; the parser turns them into these
objects once per request, and everything after that - the alerts, the
notification, the page - reads them instead of the arrays.

A chance is kept exactly as the service reported it: a number, ``None``, or
something that is not a number at all. The rules in
:mod:`rainalert.domain.rain` decide what an unreadable value means, so the
model never quietly turns one into a zero.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Hour:
    """One hour of one day, in the city's own local time."""

    # A naive local time, the same local time the daily dates are in.
    moment: datetime
    chance: object
    # Whether the hour is over, and whether it is the hour the city is in
    # now. Both are false when the response did not say what time it is.
    past: bool = False
    now: bool = False

    @property
    def day(self):
        """The ISO date the hour belongs to."""
        return self.moment.date().isoformat()


@dataclass(frozen=True)
class Day:
    """One day of the forecast, with the hours that fall on it."""

    iso_date: str
    chance: object
    high: object = None
    low: object = None
    # The day's rain in millimetres, and the number of hours it lasts.
    amount: object = None
    rain_hours: object = None
    hours: tuple = ()


@dataclass(frozen=True)
class Forecast:
    """The week, and the hours of the day the city is in now."""

    days: tuple = ()
    # The hours of the city's current local day, for the alerts that are
    # about the hours still to come. Empty when the response had no hours.
    today: tuple = ()
