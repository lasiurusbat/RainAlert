"""The rain rules: how a chance is read, which band it falls in, and when
it is worth carrying an umbrella.

Nothing here knows about Flask, the network or the page. The thresholds are
read from :mod:`rainalert.config` each time they are needed, so a test that
patches one is seen here.
"""

from decimal import ROUND_HALF_UP, Decimal

from rainalert import config


def round_half_up(value):
    """Round to the nearest integer, with .5 going up.

    Python's built-in ``round`` uses banker's rounding, so ``round(8.5)`` is 8
    and ``round(9.5)`` is 10. For temperatures, where halves are common, that
    reads as an off-by-one error.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def needs_umbrella(chance):
    """Whether the day is wet enough to be worth carrying an umbrella."""
    probability = rain_chance(chance)
    return probability is not None and probability >= config.UMBRELLA_THRESHOLD


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
