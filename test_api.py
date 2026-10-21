"""Live integration check against the real Open-Meteo and Nominatim services.

These tests hit the network, so they are skipped unless the upstream is
reachable. Run them explicitly with::

    python -m unittest test_api -v

The offline unit tests in ``test_app.py`` are the ones that gate changes.
"""

import unittest

import requests

import app as rainalert


class TestLiveOpenMeteo(unittest.TestCase):
    """Checks the shape of the real Open-Meteo response."""

    def setUp(self):
        rainalert.get_coordinates.cache_clear()

    def test_forecast_request_succeeds_for_london(self):
        latitude, longitude, label = rainalert.get_coordinates("London")
        self.assertTrue(label)

        forecast = rainalert.fetch_forecast(latitude, longitude)
        self.assertGreater(len(forecast), 0)
        for day in forecast:
            self.assertIn("date", day)
            self.assertIn("rain_label", day)
            self.assertTrue(day["date"])
            self.assertTrue(day["rain_label"])

    def test_response_contains_the_fields_we_request(self):
        response = requests.get(
            rainalert.FORECAST_URL,
            params={
                "latitude": 51.5074,
                "longitude": -0.1278,
                "daily": rainalert.DAILY_FIELDS,
                "timezone": "auto",
            },
            timeout=rainalert.WEATHER_TIMEOUT,
        )
        response.raise_for_status()
        daily = response.json()["daily"]
        self.assertIn("time", daily)
        self.assertIn("precipitation_probability_max", daily)
        self.assertEqual(len(daily["time"]), len(daily["precipitation_probability_max"]))

    def test_city_with_no_forecast_still_resolves(self):
        """A resolvable city returns coordinates even if data is sparse."""
        latitude, longitude, _ = rainalert.get_coordinates("Reykjavik")
        self.assertIsInstance(latitude, float)
        self.assertIsInstance(longitude, float)


class TestLiveUnknownCity(unittest.TestCase):
    def test_unknown_city_raises_city_not_found(self):
        with self.assertRaises(rainalert.CityNotFound):
            rainalert.get_coordinates("Xqzxvwplkjhg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
