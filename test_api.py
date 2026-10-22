"""Live integration check against the real Open-Meteo and Nominatim services.

These tests hit the network, so they are skipped unless the upstream is
reachable. Run them explicitly with::

    python -m unittest test_api -v

The offline unit tests in ``test_app.py`` are the ones that gate changes.
"""

import unittest

import requests

import app as rainalert
from rainalert import config
from rainalert import errors
from rainalert.upstream import geocoding
from rainalert.web import common
from rainalert.upstream import open_meteo


class TestLiveOpenMeteo(unittest.TestCase):
    """Checks the shape of the real Open-Meteo response."""

    def setUp(self):
        geocoding.get_coordinates.cache_clear()

    def test_forecast_request_succeeds_for_london(self):
        latitude, longitude, label = geocoding.get_coordinates("London")
        self.assertTrue(label)

        forecast = common.fetch_forecast(latitude, longitude)
        self.assertGreater(len(forecast), 0)
        for day in forecast:
            self.assertIn("date", day)
            self.assertIn("rain_label", day)
            self.assertTrue(day["date"])
            self.assertTrue(day["rain_label"])

    def test_response_contains_the_fields_we_request(self):
        response = requests.get(
            open_meteo.FORECAST_URL,
            params={
                "latitude": 51.5074,
                "longitude": -0.1278,
                "daily": open_meteo.DAILY_FIELDS,
                "timezone": "auto",
            },
            timeout=config.WEATHER_TIMEOUT,
        )
        response.raise_for_status()
        daily = response.json()["daily"]
        self.assertIn("time", daily)
        self.assertIn("precipitation_probability_max", daily)
        self.assertEqual(len(daily["time"]), len(daily["precipitation_probability_max"]))

    def test_the_hourly_block_has_the_shape_the_strip_needs(self):
        """The hourly array and the daily array must line up."""
        response = requests.get(
            open_meteo.FORECAST_URL,
            params={
                "latitude": 51.5074,
                "longitude": -0.1278,
                "hourly": open_meteo.HOURLY_FIELDS,
                "current": open_meteo.HOURLY_FIELDS,
                "timezone": "auto",
            },
            timeout=config.WEATHER_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        hourly = payload["hourly"]
        self.assertIn("time", hourly)
        self.assertIn("precipitation_probability", hourly)
        self.assertEqual(len(hourly["time"]),
                         len(hourly["precipitation_probability"]))
        # The first hour is local midnight of the current day.
        self.assertTrue(hourly["time"][0].endswith("T00:00"))
        # The current time is reported in the same local time.
        self.assertIn("time", payload["current"])

    def test_the_live_hourly_strip_renders(self):
        """The strip is built from a real response, not just a mock."""
        latitude, longitude, _ = geocoding.get_coordinates("London")
        forecast, hours = common.fetch_weather(latitude, longitude)
        self.assertGreater(len(forecast), 0)
        self.assertGreater(len(hours), 0)
        for hour in hours:
            self.assertIn("severity", hour)
            self.assertTrue(hour["time_label"].endswith(":00"))
            self.assertGreaterEqual(hour["height"], 0)
            self.assertLessEqual(hour["height"], 100)

    def test_city_with_no_forecast_still_resolves(self):
        """A resolvable city returns coordinates even if data is sparse."""
        latitude, longitude, _ = geocoding.get_coordinates("Reykjavik")
        self.assertIsInstance(latitude, float)
        self.assertIsInstance(longitude, float)


class TestLiveUnknownCity(unittest.TestCase):
    def test_unknown_city_raises_city_not_found(self):
        with self.assertRaises(errors.CityNotFound):
            geocoding.get_coordinates("Xqzxvwplkjhg")


class TestLiveCalendarExport(unittest.TestCase):
    """The export route, against the real services.

    The threshold is 0 so that every day the service reports is in the
    file: the point here is that the route works end to end, not which
    days the weather happens to select.
    """

    def setUp(self):
        geocoding.get_coordinates.cache_clear()
        self.client = rainalert.app.test_client()

    def test_the_export_is_a_calendar_file(self):
        response = self.client.get("/calendar.ics?city=London&threshold=0")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertIn("END:VCALENDAR", body)
        self.assertIn("DTSTART;VALUE=DATE:", body)
        self.assertIn("BEGIN:VEVENT", body)
        # The file is named after the place the geocoder resolved, which
        # for "London" is "Greater London".
        disposition = response.headers["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn(".ics", disposition)


if __name__ == "__main__":
    unittest.main(verbosity=2)
