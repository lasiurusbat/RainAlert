"""The three ways a forecast can fail to arrive, and what each one says.

The distinction between the first two matters: a network blip must not tell
a reader that their valid city does not exist. Each failure has one entry
in :data:`FAILURES`, and every route reads its message and its status code
from there, so the page, the alert poll and the calendar export cannot
drift apart. The internal text of the exception is logged, never shown.
"""

from dataclasses import dataclass


class CityNotFound(Exception):
    """The geocoder has no match for the requested city."""


class GeocodingUnavailable(Exception):
    """The geocoding service could not be reached or returned an error."""


class WeatherUnavailable(Exception):
    """The forecast service could not be reached or returned an error."""


# The answer to a request that names no city at all.
MISSING_CITY = "Please enter a city name."


@dataclass(frozen=True)
class Failure:
    """What the app says when a forecast could not be fetched."""

    # The sentence on a page. A page can offer to try again; the alert poll
    # and the calendar export cannot, so they get the shorter sentence.
    page_message: str
    api_message: str
    # The status of a city's page and of the API. The start page always
    # answers 200: a failed search is not a missing page.
    status: int
    # The warning to log, with the city as its argument; None logs nothing,
    # because a city nobody knows is not a fault.
    log: str | None = None


FAILURES = {
    CityNotFound: Failure(
        page_message="City not found. Please try a different name (e.g., 'Paris').",
        api_message="City not found. Please try a different name (e.g., 'Paris').",
        # A city's page that names a city nobody knows is a missing page, and
        # says so with its status code. A page that says "not found" but
        # answers 200 is a soft 404, and search engines treat it as one.
        status=404,
    ),
    GeocodingUnavailable: Failure(
        page_message=("The geocoding service is unavailable right now. "
                      "Please try again in a moment."),
        api_message="The geocoding service is unavailable right now.",
        # The upstream is down, not the page: 503 says "come back later" and
        # keeps the address out of the index for now.
        status=503,
        log="Geocoding service unavailable for %r",
    ),
    WeatherUnavailable: Failure(
        page_message=("The weather service is unavailable right now. "
                      "Please try again in a moment."),
        api_message="The weather service is unavailable right now.",
        status=503,
        log="Forecast service unavailable for %r",
    ),
}

# The exceptions a route catches, for an ``except`` clause.
FORECAST_ERRORS = tuple(FAILURES)


def failure_for(error):
    """The :class:`Failure` for an exception out of :data:`FORECAST_ERRORS`."""
    return FAILURES[type(error)]
