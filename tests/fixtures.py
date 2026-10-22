"""What the test suites share: the mocked upstream answers and a test case
with both services mocked.

Everything is mocked at the HTTP boundary, so a test that uses these never
touches Nominatim or Open-Meteo.
"""

import os
import unittest
from datetime import datetime
from unittest import mock

import requests

from app import app
from rainalert.domain.model import Day, Hour
from rainalert.upstream import geocoding

# The top of the repository, for the tests that read a file from it.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


FORECAST_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23"],
        "precipitation_probability_max": [100, 86, 40],
        "temperature_2m_max": [11.1, 14.0, 16.7],
        "temperature_2m_min": [8.5, 8.6, 10.3],
    },
    "hourly": {
        "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
        "precipitation_probability": [0] * 24,
    },
    "current": {"time": "2026-10-21T09:00"},
    "utc_offset_seconds": 3600,
}


def hourly_payload(chances, day="2026-10-21", now="2026-10-21T09:00"):
    """A forecast payload with the given hourly chances for one day.

    The daily values are fixed, so a test can check that the hourly strip
    leaves the daily list exactly as it was.
    """
    return {
        "daily": {
            "time": [day, "2026-10-22", "2026-10-23"],
            "precipitation_probability_max": [100, 86, 40],
            "temperature_2m_max": [11.1, 14.0, 16.7],
            "temperature_2m_min": [8.5, 8.6, 10.3],
        },
        "hourly": {
            "time": [f"{day}T{hour:02d}:00" for hour in range(len(chances))],
            "precipitation_probability": list(chances),
        },
        "current": {"time": now},
        "utc_offset_seconds": 3600,
    }


class FakeLocation:
    def __init__(self, latitude=51.5074, longitude=-0.1278, display_name="London, England, UK"):
        self.latitude = latitude
        self.longitude = longitude
        self.raw = {"display_name": display_name}


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else FORECAST_PAYLOAD
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


class AppTestCase(unittest.TestCase):
    """Base class that mocks both upstream services."""

    def setUp(self):
        geocoding.get_coordinates.cache_clear()
        self.geocode_patcher = mock.patch.object(
            geocoding.geolocator, "geocode", return_value=FakeLocation()
        )
        self.get_patcher = mock.patch.object(
            requests, "get", return_value=FakeResponse()
        )
        self.mock_geocode = self.geocode_patcher.start()
        self.mock_get = self.get_patcher.start()
        self.addCleanup(self.geocode_patcher.stop)
        self.addCleanup(self.get_patcher.stop)

        self.client = app.test_client()


def week(chances, dates=None):
    """The days of a forecast, one per chance, starting on 21 October."""
    dates = dates or [f"2026-10-{21 + offset:02d}" for offset in range(len(chances))]
    return tuple(Day(iso_date=day, chance=chance)
                 for day, chance in zip(dates, chances))


def remaining(hours):
    """Today's hours that are still to come, from ``{"chance": ...}`` dicts.

    ``None`` stays ``None``: no hourly data at all, which is not the same
    as a today with no hours left.
    """
    if hours is None:
        return None
    return [Hour(moment=datetime(2026, 10, 21, 12 + offset), chance=hour["chance"],
                 past=hour.get("past", False))
            for offset, hour in enumerate(hours)]


DONATION_URL = "https://buymeacoffee.com/rainalert"


DONATION_HREF = f'href="{DONATION_URL}"'
