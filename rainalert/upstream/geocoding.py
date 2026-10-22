"""Nominatim (OpenStreetMap): a city name to coordinates.

Nominatim's usage policy asks callers to identify themselves, so the user
agent is configuration. geopy defaults to a 1 second read timeout, which is
short enough to fail against a healthy but slow service, so the timeout is
configuration too.
"""

import logging
from functools import lru_cache

from geopy.exc import GeocoderQueryError, GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from rainalert import config
from rainalert.errors import CityNotFound, GeocodingUnavailable

log = logging.getLogger(__name__)

geolocator = Nominatim(user_agent=config.NOMINATIM_USER_AGENT,
                       timeout=config.GEOCODER_TIMEOUT)


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
        log.exception("Unexpected geocoder error for %r", city_name)
        raise GeocodingUnavailable("unexpected geocoder error") from exc

    if location is None:
        # The service answered normally and simply had no match.
        raise CityNotFound(city_name)

    raw = getattr(location, "raw", None) or {}
    display_name = raw.get("display_name")
    label = display_name.split(",")[0].strip() if display_name else city_name
    return location.latitude, location.longitude, label
