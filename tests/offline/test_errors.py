"""The failures: a city nobody knows, and an upstream that is down.
"""

import unittest
from unittest import mock

import requests

from rainalert import errors
from tests.fixtures import AppTestCase, FakeResponse


class TestGeocodingErrors(AppTestCase):
    def test_unknown_city_reports_not_found(self):
        self.mock_geocode.return_value = None
        response = self.client.post("/", data={"city": "Nowhereville"})
        body = response.get_data(as_text=True)
        self.assertIn("City not found", body)

    def test_geocoder_timeout_does_not_report_not_found(self):
        """A network failure must not masquerade as a missing city."""
        from geopy.exc import GeocoderTimedOut

        self.mock_geocode.side_effect = GeocoderTimedOut("read timeout")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unavailable", body.lower())
        self.assertNotIn("City not found", body)

    def test_geocoder_service_error_does_not_report_not_found(self):
        from geopy.exc import GeocoderUnavailable

        self.mock_geocode.side_effect = GeocoderUnavailable("429 rate limited")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unavailable", body.lower())
        self.assertNotIn("City not found", body)

    def test_geocoder_query_error_reports_not_found(self):
        from geopy.exc import GeocoderQueryError

        self.mock_geocode.side_effect = GeocoderQueryError("Unable to geocode")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("City not found", body)

    def test_internal_geocoder_error_does_not_leak_details(self):
        self.mock_geocode.side_effect = RuntimeError("secret internal detail")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertNotIn("secret internal detail", body)
        self.assertIn("unavailable", body.lower())


class TestWeatherErrors(AppTestCase):
    def test_weather_timeout_reports_service_unavailable(self):
        self.mock_get.side_effect = requests.Timeout("read timeout")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unavailable", body.lower())
        self.assertNotIn("timeout=", body)

    def test_weather_connection_error_does_not_leak_details(self):
        self.mock_get.side_effect = requests.ConnectionError("refused to 10.0.0.5:443")
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertNotIn("10.0.0.5", body)
        self.assertIn("unavailable", body.lower())

    def test_weather_http_error_reports_service_unavailable(self):
        self.mock_get.return_value = FakeResponse(status_code=500)
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unavailable", body.lower())

    def test_invalid_json_reports_service_unavailable(self):
        bad = mock.Mock()
        bad.raise_for_status.return_value = None
        bad.json.side_effect = ValueError("not json")
        self.mock_get.return_value = bad
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unavailable", body.lower())


class TestFailureTable(unittest.TestCase):
    """Every failure is described once, for every route that can hit it."""

    def test_every_message_is_a_sentence(self):
        """User-facing messages are plain sentences ending in a period."""
        for exc, failure in errors.FAILURES.items():
            for message in (failure.page_message, failure.api_message):
                with self.subTest(exc=exc.__name__, message=message):
                    self.assertTrue(message[0].isupper())
                    self.assertTrue(message.endswith("."))

    def test_a_missing_city_is_a_404_and_an_outage_a_503(self):
        self.assertEqual(errors.FAILURES[errors.CityNotFound].status, 404)
        self.assertEqual(errors.FAILURES[errors.GeocodingUnavailable].status, 503)
        self.assertEqual(errors.FAILURES[errors.WeatherUnavailable].status, 503)

    def test_an_outage_never_says_the_city_is_missing(self):
        """A network blip must not tell a reader their city does not exist."""
        for exc in (errors.GeocodingUnavailable, errors.WeatherUnavailable):
            failure = errors.FAILURES[exc]
            self.assertNotIn("not found", failure.page_message)
            self.assertNotIn("not found", failure.api_message)

    def test_only_an_outage_is_logged(self):
        """A city nobody knows is not a fault, so it is not logged."""
        self.assertIsNone(errors.FAILURES[errors.CityNotFound].log)
        self.assertIsNotNone(errors.FAILURES[errors.GeocodingUnavailable].log)
        self.assertIsNotNone(errors.FAILURES[errors.WeatherUnavailable].log)
