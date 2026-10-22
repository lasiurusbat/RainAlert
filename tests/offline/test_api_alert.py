"""The alert poll and the notification control on the page.
"""

from rainalert import config, errors
from tests.fixtures import AppTestCase, FakeResponse, hourly_payload


class TestAlertEndpoint(AppTestCase):
    """The endpoint the page polls for something worth saying."""

    def setUp(self):
        super().setUp()
        self.mock_get.return_value = FakeResponse(
            payload=hourly_payload([0] * 10 + [80] + [0] * 13))

    def alert(self, query=""):
        response = self.client.get(f"/api/alert{query}")
        return response, response.get_json()

    def test_it_needs_a_city(self):
        response, data = self.alert()
        self.assertEqual(response.status_code, 400)
        self.assertIn("city name", data["error"])

    def test_it_answers_with_the_event(self):
        response, data = self.alert("?city=London")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["city"], "London")
        self.assertEqual(data["event"]["key"], "hour:2026-10-21T10:00")
        self.assertEqual(data["event"]["title"], "Rain likely from 10:00")

    def test_it_tells_the_browser_how_often_to_poll(self):
        _, data = self.alert("?city=London")
        self.assertEqual(data["poll_minutes"], config.NOTIFICATION_POLL_MINUTES)
        self.assertEqual(data["lead_hours"], config.NOTIFICATION_LEAD_HOURS)

    def test_the_readers_own_threshold_is_used_when_it_is_sent(self):
        _, data = self.alert("?city=London&threshold=90")
        self.assertEqual(data["threshold"], 90)
        self.assertTrue(data["personal_threshold"])
        self.assertIsNone(data["event"])

    def test_without_a_threshold_the_apps_own_is_used(self):
        _, data = self.alert("?city=London")
        self.assertEqual(data["threshold"], config.UMBRELLA_THRESHOLD)
        self.assertFalse(data["personal_threshold"])

    def test_an_unknown_city_is_reported(self):
        self.mock_geocode.return_value = None
        response, data = self.alert("?city=Nowhereville")
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", data["error"])

    def test_a_geocoder_outage_is_not_reported_as_a_missing_city(self):
        self.mock_geocode.side_effect = errors.GeocodingUnavailable("down")
        response, data = self.alert("?city=London")
        self.assertEqual(response.status_code, 503)
        self.assertIn("geocoding service", data["error"])

    def test_a_weather_outage_is_reported(self):
        self.mock_get.side_effect = errors.WeatherUnavailable("down")
        response, data = self.alert("?city=London")
        self.assertEqual(response.status_code, 503)
        self.assertIn("weather service", data["error"])

    def test_the_forecast_is_fetched_with_a_timeout(self):
        self.alert("?city=London")
        _, kwargs = self.mock_get.call_args
        self.assertGreater(kwargs["timeout"], 0)

    def test_a_dry_day_answers_with_no_event(self):
        self.mock_get.return_value = FakeResponse(
            payload=hourly_payload([0] * 24))
        _, data = self.alert("?city=London")
        self.assertIsNone(data["event"])


class TestNotificationControl(AppTestCase):
    """The browser-side half of the notification: the button on the page.

    The rule that decides what a notification says is tested above, and the
    button's own behaviour is tested in test_browser.py, which drives a
    real browser. What is left here is the markup the script needs.
    """

    def body_with_forecast(self):
        self.mock_get.return_value = FakeResponse(
            payload=hourly_payload([0] * 10 + [80] + [0] * 13))
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_the_button_is_on_the_forecast_page(self):
        body = self.body_with_forecast()
        self.assertIn('id="notify-toggle"', body)
        self.assertIn("Notify me", body)

    def test_the_button_is_hidden_until_the_script_has_run(self):
        """A button that cannot work yet must not be on the page."""
        body = self.body_with_forecast()
        button = body[body.index('id="notify-toggle"'):]
        button = button[:button.index(">")]
        self.assertIn("hidden", button)

    def test_the_button_sits_with_the_hourly_title(self):
        """It belongs to the strip: the notification says what it says."""
        body = self.body_with_forecast()
        head = body[body.index("hourly-head"):body.index("hourly-summary")]
        self.assertIn('id="notify-toggle"', head)

    def test_there_is_no_button_without_hourly_data(self):
        """The notification needs the hours to say anything about."""
        self.mock_get.return_value = FakeResponse(payload={
            "daily": {
                "time": ["2026-10-21"],
                "precipitation_probability_max": [80],
                "temperature_2m_max": [12.0],
                "temperature_2m_min": [8.0],
            }
        })
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertNotIn('id="notify-toggle"', body)

    def test_there_is_no_button_on_the_start_page(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('id="notify-toggle"', body)
