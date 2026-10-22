"""The three ways a forecast can fail to arrive.

The distinction between the first two matters: a network blip must not tell
a reader that their valid city does not exist. The routes translate each one
into a message and a status code; the internal text is logged, never shown.
"""


class CityNotFound(Exception):
    """The geocoder has no match for the requested city."""


class GeocodingUnavailable(Exception):
    """The geocoding service could not be reached or returned an error."""


class WeatherUnavailable(Exception):
    """The forecast service could not be reached or returned an error."""
