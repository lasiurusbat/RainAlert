"""What the route modules share: the forecast in the form the template
renders it, and the way a failure is reported.

These two functions sit between the upstream clients and the templates, so
they are the last place a forecast is turned into the dicts a page is
rendered from.
"""

import unittest
from unittest import mock

import requests
from flask import Flask

from rainalert.errors import CityNotFound, WeatherUnavailable, failure_for
from rainalert.web import common
from tests.fixtures import FORECAST_PAYLOAD, FakeResponse, hourly_payload


class TestFetchWeather(unittest.TestCase):
    """The forecast as the template sees it: a list of days and a list of
    hours.
    """

    def fetch(self, payload=None, unit=None):
        with mock.patch.object(requests, "get",
                               return_value=FakeResponse(payload=payload)):
            return common.fetch_weather(51.5, -0.12, unit)

    def test_the_days_and_the_hours_come_back_together(self):
        days, hours = self.fetch()
        self.assertEqual(len(days), 3)
        self.assertEqual(len(hours), 24)

    def test_a_day_is_the_dict_the_template_renders(self):
        days, _ = self.fetch()
        day = days[0]
        self.assertEqual(day["date"], "Wednesday 21.10.2026")
        self.assertEqual(day["weekday_short"], "Wed")
        self.assertEqual(day["date_short"], "21.10")
        self.assertEqual(day["rain_label"], "100%")
        self.assertEqual(day["chance_number"], 100)
        self.assertEqual(day["severity"], "high")
        self.assertTrue(day["umbrella"])

    def test_the_hours_are_the_dicts_the_template_renders(self):
        _, hours = self.fetch()
        hour = hours[0]
        self.assertEqual(hour["hour_label"], "00")
        self.assertIn("chance", hour)

    def test_the_unit_is_passed_on_to_the_service(self):
        """The service does the arithmetic, so it is the one asked."""
        with mock.patch.object(requests, "get",
                               return_value=FakeResponse()) as get:
            common.fetch_weather(51.5, -0.12, "fahrenheit")
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["temperature_unit"], "fahrenheit")

    def test_a_broken_hourly_block_leaves_the_days(self):
        """The hours are an addition to the week, not part of it."""
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [80, 20],
            },
            "hourly": "junk",
        }
        days, hours = self.fetch(payload)
        self.assertEqual(len(days), 2)
        self.assertEqual(hours, [])

    def test_a_broken_service_is_raised(self):
        """A broken answer is the service's problem, and the page says so.

        The exception is raised rather than swallowed, so the route can
        turn it into the 503 the reader should see.
        """
        with mock.patch.object(requests, "get",
                               side_effect=requests.ConnectionError("down")):
            with self.assertRaises(WeatherUnavailable):
                common.fetch_weather(51.5, -0.12)


class TestReportFailure(unittest.TestCase):
    """A failure is described once, and the log says what happened."""

    def test_the_failure_table_answers_for_the_exception(self):
        """The page, the API and the calendar all read the same table, so
        the three cannot drift apart."""
        failure = failure_for(WeatherUnavailable())
        self.assertEqual(failure.status, 503)
        self.assertIn("unavailable", failure.page_message)
        self.assertTrue(failure.api_message)
        self.assertTrue(failure.log)

    def test_the_log_says_why_the_forecast_failed(self):
        """A bare "service unavailable" cannot tell a rate limit from an
        outage; the exception's text is what can."""
        app = Flask(__name__)
        error = WeatherUnavailable("the forecast service returned HTTP 429")
        with app.app_context(), self.assertLogs(app.logger, "WARNING") as logs:
            common.report_failure(error, "London")
        self.assertIn("Forecast service unavailable for 'London'",
                      logs.output[0])
        self.assertIn("returned HTTP 429", logs.output[0])

    def test_the_reason_is_logged_and_never_shown(self):
        app = Flask(__name__)
        error = WeatherUnavailable("the forecast service returned HTTP 429")
        with app.app_context(), self.assertLogs(app.logger, "WARNING"):
            failure = common.report_failure(error, "London")
        self.assertNotIn("429", failure.page_message)
        self.assertNotIn("429", failure.api_message)

    def test_a_missing_city_is_not_a_broken_service(self):
        """The two are different failures, and they answer differently."""
        self.assertEqual(failure_for(CityNotFound()).status, 404)
        self.assertEqual(failure_for(WeatherUnavailable()).status, 503)


class TestTheForecastIsReadOnce(unittest.TestCase):
    """One page load costs one request, not two.

    The daily list and the hourly strip come from the same answer, so the
    service is asked once and the answer is read once.
    """

    def fetch(self, payload=None):
        with mock.patch.object(requests, "get",
                               return_value=FakeResponse(payload=payload)):
            return common.fetch_weather(51.5, -0.12)

    def test_one_request_per_forecast(self):
        with mock.patch.object(requests, "get",
                               return_value=FakeResponse()) as get:
            common.fetch_weather(51.5, -0.12)
        self.assertEqual(get.call_count, 1)

    def test_the_hours_belong_to_the_first_day(self):
        """The strip shows one local day, not the whole forecast week."""
        payload = hourly_payload([5] * 24)
        days, hours = self.fetch(payload)
        self.assertEqual(len(days), 3)
        self.assertEqual(len(hours), 24)
        self.assertTrue(all(hour["day"] == "2026-10-21" for hour in hours))

    def test_the_daily_list_is_not_changed_by_the_hours(self):
        """The strip is an addition: the week's own numbers are its own."""
        payload = hourly_payload([5] * 24)
        days, _ = self.fetch(payload)
        self.assertEqual([day["rain_label"] for day in days],
                         ["100%", "86%", "40%"])
