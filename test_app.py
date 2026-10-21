"""Tests for the RainAlert app.

Everything is mocked at the HTTP boundary, so the suite runs offline and
never touches Nominatim or Open-Meteo.
"""

import unittest
from unittest import mock

import requests

import app as rainalert


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
        rainalert.get_coordinates.cache_clear()
        self.geocode_patcher = mock.patch.object(
            rainalert.geolocator, "geocode", return_value=FakeLocation()
        )
        self.get_patcher = mock.patch.object(
            rainalert.requests, "get", return_value=FakeResponse()
        )
        self.mock_geocode = self.geocode_patcher.start()
        self.mock_get = self.get_patcher.start()
        self.addCleanup(self.geocode_patcher.stop)
        self.addCleanup(self.get_patcher.stop)

        app = rainalert.app.test_client()
        self.client = app


class TestHappyPath(AppTestCase):
    def test_get_renders_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Rain Alert", body)
        self.assertIn('name="city"', body)

    def test_post_renders_forecast(self):
        response = self.client.post("/", data={"city": "London"})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Mittwoch 21.10.2026", body)
        self.assertIn("100% chance of rain", body)
        self.assertIn("86% chance of rain", body)
        self.assertNotIn('class="error"', body)

    def test_dates_use_weekday_and_dotted_format(self):
        """Dates render as 'Wednesday 21.10.2026'."""
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("Donnerstag 22.10.2026", body)
        self.assertIn("Freitag 23.10.2026", body)
        # The raw ISO form should no longer leak into the page.
        self.assertNotIn("2026-10-21", body)

    def test_dates_follow_the_requested_locale(self):
        """With the locale set to English the weekday name is English."""
        with mock.patch.object(rainalert, "DATE_LOCALE", "en_US"):
            response = self.client.post("/", data={"city": "London"})
            body = response.get_data(as_text=True)
            self.assertIn("Wednesday 21.10.2026", body)
            self.assertNotIn("Mittwoch", body)

    def test_forecast_is_fetched_with_a_timeout(self):
        self.client.post("/", data={"city": "London"})
        _, kwargs = self.mock_get.call_args
        self.assertIn("timeout", kwargs, "requests.get must pass a timeout")
        self.assertGreater(kwargs["timeout"], 0)

    def test_forecast_is_fetched_with_the_right_coordinates(self):
        self.client.post("/", data={"city": "London"})
        _, kwargs = self.mock_get.call_args
        self.assertAlmostEqual(kwargs["params"]["latitude"], 51.5074)
        self.assertAlmostEqual(kwargs["params"]["longitude"], -0.1278)

    def test_city_name_is_not_title_cased(self):
        """'st john's' must reach the geocoder unmodified."""
        self.client.post("/", data={"city": "st john's"})
        args, _ = self.mock_geocode.call_args
        self.assertEqual(args[0], "st john's")

    def test_display_name_is_not_mangled(self):
        """The page shows the geocoder's name, not a title-cased guess."""
        self.mock_geocode.return_value = FakeLocation(
            display_name="St. John's, Newfoundland, Canada"
        )
        response = self.client.post("/", data={"city": "st john's"})
        body = response.get_data(as_text=True)
        self.assertIn("St. John&#39;s", body)
        self.assertNotIn("St John&#39;S", body)

    def test_whitespace_only_city_is_rejected(self):
        response = self.client.post("/", data={"city": "   "})
        body = response.get_data(as_text=True)
        self.assertIn("Please enter a city name.", body)

    def test_submitted_city_is_preserved_in_the_input(self):
        response = self.client.post("/", data={"city": "st john's"})
        body = response.get_data(as_text=True)
        self.assertIn('value="st john&#39;s"', body)


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


class TestEmptyForecast(AppTestCase):
    def test_empty_daily_data_shows_the_no_forecast_message(self):
        """The 'no forecast' branch must actually be reachable."""
        empty = FakeResponse(payload={"daily": {"time": [], "precipitation_probability_max": []}})
        self.mock_get.return_value = empty
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("No forecast data available", body)

    def test_missing_daily_key_shows_the_no_forecast_message(self):
        self.mock_get.return_value = FakeResponse(payload={})
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("No forecast data available", body)

    def test_null_precipitation_value_is_handled(self):
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [None, 80],
                "temperature_2m_max": [None, 14.0],
                "temperature_2m_min": [None, 8.0],
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("unknown", body)
        self.assertIn("80% chance of rain", body)

    def test_mismatched_array_lengths_do_not_crash(self):
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22", "2026-10-23"],
                "precipitation_probability_max": [100, 50],
                "temperature_2m_max": [11.0],
                "temperature_2m_min": [],
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        response = self.client.post("/", data={"city": "London"})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Mittwoch 21.10.2026", body)
        self.assertIn("Donnerstag 22.10.2026", body)
        self.assertNotIn("23.10.2026", body)


class TestRainSeverity(AppTestCase):
    """Tier 1: each day is colour-coded by how wet it is expected to be."""

    def _forecast_for(self, chances):
        """POST a forecast with the given daily rain chances."""
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + i:02d}" for i in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_severity_bands_cover_the_thresholds(self):
        self.assertEqual(rainalert.severity_band(0), "low")
        self.assertEqual(rainalert.severity_band(29), "low")
        self.assertEqual(rainalert.severity_band(30), "moderate")
        self.assertEqual(rainalert.severity_band(60), "moderate")
        self.assertEqual(rainalert.severity_band(61), "high")
        self.assertEqual(rainalert.severity_band(100), "high")

    def test_missing_chance_gets_the_unknown_band(self):
        self.assertEqual(rainalert.severity_band(None), "unknown")
        self.assertEqual(rainalert.severity_band("not a number"), "unknown")

    def test_bands_are_configurable(self):
        with mock.patch.object(rainalert, "SEVERITY_LOW_MAX", 10):
            with mock.patch.object(rainalert, "SEVERITY_MODERATE_MAX", 40):
                self.assertEqual(rainalert.severity_band(5), "low")
                self.assertEqual(rainalert.severity_band(20), "moderate")
                self.assertEqual(rainalert.severity_band(80), "high")

    def test_umbrella_threshold(self):
        self.assertFalse(rainalert.needs_umbrella(49))
        self.assertTrue(rainalert.needs_umbrella(50))
        self.assertTrue(rainalert.needs_umbrella(100))
        self.assertFalse(rainalert.needs_umbrella(None))

    def test_each_day_gets_a_severity_class(self):
        body = self._forecast_for([10, 45, 80])
        self.assertIn("severity-low", body)
        self.assertIn("severity-moderate", body)
        self.assertIn("severity-high", body)

    def test_each_day_gets_a_text_label(self):
        """Severity must not be conveyed by colour alone."""
        body = self._forecast_for([10, 45, 80])
        # Screen readers get the band name on each row.
        self.assertIn("Rain unlikely.", body)
        self.assertIn("Rain possible.", body)
        self.assertIn("Rain likely.", body)

    def test_a_legend_explains_the_bands(self):
        """The colour key appears once, above the list."""
        body = self._forecast_for([10, 45, 80])
        self.assertIn("severity-legend", body)
        # One legend, not one per row.
        self.assertEqual(body.count("severity-legend"), 1)
        self.assertEqual(body.count("legend-item"), 3)

    def test_umbrella_icon_only_above_the_threshold(self):
        body = self._forecast_for([10, 45, 80])
        # One umbrella for the 80% day, none for the 10% or 45% days.
        self.assertEqual(body.count("☔"), 1)

    def test_umbrella_icon_is_absent_when_nothing_is_wet(self):
        body = self._forecast_for([5, 20])
        self.assertNotIn("☔", body)

    def test_unknown_chance_renders_the_unknown_class(self):
        body = self._forecast_for([None])
        self.assertIn("severity-unknown", body)
        self.assertIn("Unknown.", body)


class TestHourlyStrip(AppTestCase):
    """Tier 1: an hour-by-hour strip for today."""

    def _body_for(self, chances, now="2026-10-21T09:00"):
        payload = hourly_payload(chances, now=now)
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_the_strip_renders(self):
        body = self._body_for([0] * 24)
        self.assertIn("hourly-strip", body)
        self.assertIn("Today, hour by hour", body)

    def test_one_bar_per_hour(self):
        body = self._body_for([0] * 24)
        self.assertEqual(body.count('class="hour severity-'), 24)

    def test_the_daily_list_still_renders(self):
        """The strip is added to the page, not swapped for the forecast."""
        body = self._body_for([0] * 24)
        self.assertIn("Mittwoch 21.10.2026", body)
        self.assertIn("weather-list", body)

    def test_the_strip_does_not_break_the_daily_values(self):
        body = self._body_for([0] * 24)
        self.assertIn("100% chance of rain", body)
        self.assertIn("86% chance of rain", body)

    def test_the_current_hour_is_marked(self):
        body = self._body_for([0] * 24, now="2026-10-21T09:00")
        self.assertIn("hour-now", body)

    def test_no_current_hour_when_the_service_omits_it(self):
        """A response without a current block still renders a strip."""
        payload = hourly_payload([0] * 24)
        del payload["current"]
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("hourly-strip", body)
        # The now-marker falls back to the UTC offset, which is the real
        # wall clock here, so the hour it points at is not fixed. What
        # matters is that the strip still renders.
        self.assertEqual(body.count('class="hour severity-'), 24)

    def test_each_bar_carries_its_severity_band(self):
        body = self._body_for([10] * 8 + [45] * 8 + [80] * 8)
        self.assertIn("severity-low", body)
        self.assertIn("severity-moderate", body)
        self.assertIn("severity-high", body)

    def test_the_exact_value_is_in_the_tooltip(self):
        """The bar shows a rounded height; the percentage is still readable."""
        body = self._body_for([63] * 24)
        self.assertIn("63% chance of rain", body)

    def test_the_tooltip_is_not_announced_twice(self):
        """The tooltip is a data attribute, not a title attribute.

        A title attribute would be read by a screen reader as well as by
        the .sr-only span, so the value would be announced twice.
        """
        body = self._body_for([63] * 24)
        self.assertNotIn('title="09:00', body)
        self.assertIn('data-tip="09:00', body)

    def test_the_exact_value_is_in_the_table_view(self):
        """No value is reachable only by hovering."""
        body = self._body_for([37] * 24)
        self.assertIn("hourly-table", body)
        self.assertIn("37% chance of rain", body)

    def test_the_table_view_lists_every_hour(self):
        body = self._body_for([0] * 24)
        self.assertEqual(body.count("<th scope=\"row\">"), 24)

    def test_hours_are_labelled_in_local_time(self):
        body = self._body_for([0] * 24)
        self.assertIn("00:00", body)
        self.assertIn("23:00", body)

    def test_a_missing_hourly_block_leaves_the_page_intact(self):
        """No hourly data means no strip, not a broken page."""
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [100, 86],
                "temperature_2m_max": [11.1, 14.0],
                "temperature_2m_min": [8.5, 8.6],
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertNotIn("hourly-strip", body)
        self.assertIn("Mittwoch 21.10.2026", body)
        self.assertIn("100% chance of rain", body)

    def test_a_null_hour_is_not_treated_as_zero(self):
        """A missing value gets its own marker, not an empty bar."""
        body = self._body_for([None] * 24)
        self.assertIn("hour-bar-unknown", body)
        self.assertIn("chance of rain unknown", body)

    def test_an_unreadable_hour_is_treated_as_unknown(self):
        """A value that is not a number is unknown, not zero."""
        body = self._body_for(["not a number"] * 24)
        self.assertIn("hour-bar-unknown", body)
        self.assertIn("chance of rain unknown", body)

    def test_a_mismatched_hourly_array_does_not_crash(self):
        payload = hourly_payload([10, 20, 30])
        payload["hourly"]["time"] = payload["hourly"]["time"][:2]
        self.mock_get.return_value = FakeResponse(payload=payload)
        response = self.client.post("/", data={"city": "London"})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("hourly-strip", body)

    def test_unparseable_hourly_timestamps_are_skipped(self):
        payload = hourly_payload([10] * 24)
        payload["hourly"]["time"] = ["not-a-time"] + payload["hourly"]["time"][1:]
        self.mock_get.return_value = FakeResponse(payload=payload)
        response = self.client.post("/", data={"city": "London"})
        self.assertEqual(response.status_code, 200)

    def test_the_strip_costs_no_extra_request(self):
        """The daily and hourly data come from one call."""
        self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_get.call_count, 1)

    def test_the_request_asks_for_hourly_data(self):
        self.client.post("/", data={"city": "London"})
        _, kwargs = self.mock_get.call_args
        self.assertIn("hourly", kwargs["params"])
        self.assertIn("precipitation_probability", kwargs["params"]["hourly"])


class TestHourlySummary(AppTestCase):
    """The one-line summary of when rain is likely today."""

    def _summary_for(self, chances, now="2026-10-21T09:00"):
        payload = hourly_payload(chances, now=now)
        hours = rainalert.parse_today_hours(payload)
        return rainalert.summarise_hours(hours)

    def test_a_wet_window_is_reported(self):
        chances = [0] * 9 + [80] * 4 + [0] * 11
        summary = self._summary_for(chances)
        self.assertIn("from about 09:00 to 12:00", summary)
        self.assertIn("80%", summary)
        self.assertIn("umbrella", summary)

    def test_a_single_wet_hour_is_reported(self):
        chances = [0] * 9 + [80] + [0] * 14
        summary = self._summary_for(chances)
        self.assertIn("at about 09:00", summary)

    def test_a_dry_day_says_so(self):
        summary = self._summary_for([0] * 24)
        self.assertIn("No rain likely", summary)

    def test_a_past_window_is_not_reported(self):
        """A window that has already passed is not an alert."""
        chances = [90] * 8 + [0] * 16
        summary = self._summary_for(chances, now="2026-10-21T09:00")
        self.assertIn("No rain likely", summary)

    def test_a_window_starting_now_is_reported(self):
        chances = [0] * 9 + [90] * 3
        summary = self._summary_for(chances, now="2026-10-21T09:00")
        self.assertIn("from about 09:00 to 11:00", summary)

    def test_the_summary_ends_in_a_period(self):
        """User-facing sentences end in a period."""
        summary = self._summary_for([80] * 24)
        self.assertTrue(summary.endswith("."))

    def test_the_summary_appears_on_the_page(self):
        payload = hourly_payload([0] * 9 + [80] * 4 + [0] * 11)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("hourly-summary", body)
        self.assertIn("from about 09:00 to 12:00", body)

    def test_two_windows_are_both_mentioned(self):
        chances = [0] * 9 + [80] * 2 + [0] * 3 + [80] * 2 + [0] * 8
        summary = self._summary_for(chances)
        self.assertIn("and at other times too", summary)

    def test_the_umbrella_threshold_decides_the_window(self):
        """A window is a window only at or above the umbrella threshold."""
        below = self._summary_for([0] * 9 + [49] * 3 + [0] * 12)
        self.assertIn("No rain likely", below)
        at = self._summary_for([0] * 9 + [50] * 3 + [0] * 12)
        self.assertIn("from about 09:00 to 11:00", at)

    def test_the_summary_starts_with_a_capital(self):
        summary = self._summary_for([80] * 24)
        self.assertTrue(summary[0].isupper())

    def test_an_unknown_hour_is_not_called_possible(self):
        """A missing value is not a wet hour, and not a dry one either."""
        chances = [0] * 9 + [None] * 3 + [0] * 12
        summary = self._summary_for(chances)
        self.assertIn("No rain likely", summary)


class TestHourlyParsing(unittest.TestCase):
    """The hourly parsing itself, without the HTTP layer."""

    def test_a_day_of_hours_is_parsed(self):
        payload = hourly_payload([0, 10, 20] * 8)
        hours = rainalert.parse_today_hours(payload)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[0]["hour_label"], "00")
        self.assertEqual(hours[23]["hour_label"], "23")

    def test_hours_before_now_are_marked_past(self):
        payload = hourly_payload([0] * 24, now="2026-10-21T09:00")
        hours = rainalert.parse_today_hours(payload)
        self.assertTrue(hours[8]["past"])
        self.assertFalse(hours[9]["past"])

    def test_the_current_hour_is_marked_now(self):
        payload = hourly_payload([0] * 24, now="2026-10-21T09:00")
        hours = rainalert.parse_today_hours(payload)
        self.assertTrue(hours[9]["now"])
        self.assertFalse(hours[10]["now"])

    def test_only_todays_hours_are_kept(self):
        """The strip shows one local day, not the whole forecast week."""
        payload = hourly_payload([0] * 24)
        payload["hourly"]["time"] = (
            [f"2026-10-20T{hour:02d}:00" for hour in range(24)]
            + [f"2026-10-21T{hour:02d}:00" for hour in range(24)]
        )
        payload["hourly"]["precipitation_probability"] = [5] * 48
        hours = rainalert.parse_today_hours(payload)
        self.assertEqual(len(hours), 24)
        self.assertTrue(all(hour["day"] == "2026-10-21" for hour in hours))

    def test_today_follows_the_current_time(self):
        """The strip shows the day the now-marker is on.

        The daily array and the current time can disagree: the daily list
        starts on the first forecast day, which is not always the day the
        clock says it is. The now-marker has to land on a bar, so the strip
        follows the current time.
        """
        payload = hourly_payload([0] * 24, day="2026-10-21",
                                  now="2026-10-22T03:00")
        payload["hourly"]["time"] = (
            [f"2026-10-21T{hour:02d}:00" for hour in range(24)]
            + [f"2026-10-22T{hour:02d}:00" for hour in range(24)]
        )
        payload["hourly"]["precipitation_probability"] = [5] * 48
        hours = rainalert.parse_today_hours(payload)
        self.assertEqual(len(hours), 24)
        self.assertTrue(all(hour["day"] == "2026-10-22" for hour in hours))
        self.assertTrue(any(hour["now"] for hour in hours))

    def test_a_day_with_23_hours_is_kept_whole(self):
        """A clock-change day is not truncated to 24 entries."""
        payload = hourly_payload([5] * 23, day="2026-10-21")
        hours = rainalert.parse_today_hours(payload)
        self.assertEqual(len(hours), 23)

    def test_an_empty_hourly_block_gives_no_hours(self):
        self.assertEqual(rainalert.parse_today_hours({}), [])
        self.assertEqual(rainalert.parse_today_hours({"hourly": {}}), [])

    def test_the_height_is_bucketed_into_steps(self):
        self.assertEqual(rainalert.hour_height_step(0), 0)
        self.assertEqual(rainalert.hour_height_step(2), 0)
        self.assertEqual(rainalert.hour_height_step(3), 5)
        self.assertEqual(rainalert.hour_height_step(100), 100)
        self.assertEqual(rainalert.hour_height_step(130), 100)
        self.assertEqual(rainalert.hour_height_step(None), 0)

    def test_the_local_now_falls_back_to_the_utc_offset(self):
        """Without a current block the offset still says what time it is."""
        payload = hourly_payload([0] * 24)
        del payload["current"]
        self.assertIsNotNone(rainalert.local_now(payload))

    def test_the_local_now_is_none_without_any_time_information(self):
        self.assertIsNone(rainalert.local_now({}))

    def test_an_unparseable_timestamp_is_rejected(self):
        self.assertIsNone(rainalert.parse_hour_timestamp("not-a-time"))
        self.assertIsNone(rainalert.parse_hour_timestamp(None))
        self.assertIsNotNone(rainalert.parse_hour_timestamp("2026-10-21T15:00"))


class TestCaching(AppTestCase):
    def test_repeated_lookups_hit_the_geocoder_once(self):
        for _ in range(3):
            self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_geocode.call_count, 1)

    def test_different_cities_are_cached_separately(self):
        self.client.post("/", data={"city": "London"})
        self.client.post("/", data={"city": "Paris"})
        self.assertEqual(self.mock_geocode.call_count, 2)

    def test_failures_are_not_cached(self):
        self.mock_geocode.side_effect = RuntimeError("boom")
        self.client.post("/", data={"city": "London"})
        self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_geocode.call_count, 2)


class TestForecastParsing(unittest.TestCase):
    def test_format_date(self):
        self.assertEqual(
            rainalert.format_date("2026-10-21"), "Wednesday 21.10.2026")
        self.assertEqual(
            rainalert.format_date("2026-10-22"), "Thursday 22.10.2026")
        self.assertEqual(
            rainalert.format_date("2026-11-01"), "Sunday 01.11.2026")

    def test_format_date_pads_day_and_month(self):
        self.assertEqual(
            rainalert.format_date("2026-01-05"), "Monday 05.01.2026")

    def test_format_date_leaves_unparseable_values_alone(self):
        self.assertEqual(rainalert.format_date("not-a-date"), "not-a-date")
        self.assertEqual(rainalert.format_date(None), "None")

    def test_format_rain_chance(self):
        self.assertEqual(rainalert.format_rain_chance(100), "100% chance of rain")
        self.assertEqual(rainalert.format_rain_chance(86.4), "86% chance of rain")
        self.assertEqual(rainalert.format_rain_chance(0), "0% chance of rain")
        self.assertEqual(
            rainalert.format_rain_chance(None), "chance of rain unknown"
        )

    def test_format_temperature(self):
        self.assertEqual(rainalert.format_temperature(11.1, 8.4), "11° / 8°")
        self.assertEqual(rainalert.format_temperature(14.0, None), "14°")
        self.assertEqual(rainalert.format_temperature(None, None), "")

    def test_half_rounds_up(self):
        """Temperatures ending in .5 must round up, not to even."""
        self.assertEqual(rainalert.format_temperature(8.5, 9.5), "9° / 10°")
        self.assertEqual(rainalert.round_half_up(8.5), 9)
        self.assertEqual(rainalert.round_half_up(9.5), 10)
        # Negative halves round away from zero, so -0.5C reads as -1C.
        self.assertEqual(rainalert.round_half_up(-0.5), -1)


class TestLocalisation(unittest.TestCase):
    def test_weekday_names_are_localised(self):
        self.assertEqual(
            rainalert.weekday_names("de_DE")[2], "Mittwoch")
        self.assertEqual(
            rainalert.weekday_names("fr_FR")[2], "mercredi")
        self.assertEqual(
            rainalert.weekday_names("nl_NL")[2], "woensdag")
        self.assertEqual(
            rainalert.weekday_names("es_ES")[2], "miércoles")

    def test_weekday_names_cover_all_seven_days(self):
        names = rainalert.weekday_names("de_DE")
        self.assertEqual(len(names), 7)
        self.assertEqual(len(set(names)), 7)
        self.assertEqual(names[0], "Montag")
        self.assertEqual(names[6], "Sonntag")

    def test_format_date_uses_the_locale(self):
        self.assertEqual(
            rainalert.format_date("2026-10-21", "de_DE"), "Mittwoch 21.10.2026")
        self.assertEqual(
            rainalert.format_date("2026-10-21", "fr_FR"), "mercredi 21.10.2026")
        self.assertEqual(
            rainalert.format_date("2026-10-21", "nl_NL"), "woensdag 21.10.2026")

    def test_unknown_locale_falls_back_to_english(self):
        self.assertEqual(
            rainalert.format_date("2026-10-21", "xx_XX"), "Wednesday 21.10.2026")

    def test_locale_name_variants_are_tried(self):
        """A locale must be found however the platform spells it.

        Windows accepts the bare name ``de_DE``; glibc usually wants a
        codeset suffix and rejects the bare form even when the locale is
        installed. The bare name has to work on both, and an explicit
        codeset must not be mangled.
        """
        candidates = list(rainalert._locale_candidates("de_DE"))
        self.assertEqual(candidates[0], "de_DE")
        self.assertIn("de_DE.UTF-8", candidates)
        self.assertIn("de_DE.utf8", candidates)

        # A name that already carries a codeset is left alone.
        self.assertEqual(
            list(rainalert._locale_candidates("de_DE.UTF-8")), ["de_DE.UTF-8"])

    def test_locale_with_codeset_still_localises(self):
        self.assertEqual(
            rainalert.weekday_names("de_DE.UTF-8")[2], "Mittwoch")

    def test_ambient_locale_is_restored(self):
        """Formatting must not leave the process locale switched."""
        import locale as locale_module

        previous = locale_module.setlocale(locale_module.LC_TIME, None)
        # The accepted spelling differs per platform, so use one this system
        # actually takes. The bare name works on Windows; glibc wants a
        # codeset suffix.
        ambient = None
        for candidate in rainalert._locale_candidates("fr_FR"):
            try:
                locale_module.setlocale(locale_module.LC_TIME, candidate)
                ambient = candidate
                break
            except locale_module.Error:
                continue
        self.assertIsNotNone(ambient, "fr_FR should be available on this system")

        try:
            # Clear the cache, or the cached names are returned without the
            # locale ever being switched and the test proves nothing.
            rainalert.weekday_names.cache_clear()
            rainalert.format_date("2026-10-21", "de_DE")
            self.assertEqual(
                locale_module.setlocale(locale_module.LC_TIME, None), ambient)
        finally:
            locale_module.setlocale(locale_module.LC_TIME, previous)

    def test_accept_language_parsing(self):
        self.assertEqual(
            rainalert.locale_from_accept_language("de-DE,de;q=0.9,en;q=0.8"),
            "de_DE")
        self.assertEqual(
            rainalert.locale_from_accept_language("fr-FR,fr;q=0.9"), "fr_FR")
        self.assertEqual(
            rainalert.locale_from_accept_language("nl-NL,nl;q=0.9"), "nl_NL")
        self.assertEqual(
            rainalert.locale_from_accept_language("pt-BR,pt;q=0.9"), "pt_BR")
        self.assertEqual(
            rainalert.locale_from_accept_language("en-GB,en;q=0.9"), "en_GB")
        self.assertIsNone(rainalert.locale_from_accept_language("zz-ZZ"))
        self.assertIsNone(rainalert.locale_from_accept_language(""))
        self.assertIsNone(rainalert.locale_from_accept_language(None))

    def test_request_uses_the_configured_locale(self):
        with mock.patch.object(rainalert, "DATE_LOCALE", "de_DE"):
            with rainalert.app.test_request_context("/"):
                self.assertEqual(rainalert.requested_locale(), "de_DE")

    def test_request_falls_back_to_accept_language(self):
        with mock.patch.object(rainalert, "DATE_LOCALE", "auto"):
            headers = {"Accept-Language": "nl-NL,nl;q=0.9"}
            with rainalert.app.test_request_context("/", headers=headers):
                self.assertEqual(rainalert.requested_locale(), "nl_NL")

    def test_request_falls_back_to_english(self):
        with mock.patch.object(rainalert, "DATE_LOCALE", "auto"):
            with rainalert.app.test_request_context("/"):
                self.assertEqual(rainalert.requested_locale(), "en_US")


DONATION_URL = "https://buymeacoffee.com/rainalert"
DONATION_HREF = f'href="{DONATION_URL}"'


class TestCleanDonationUrl(unittest.TestCase):
    """The donation link goes into every page, so it is validated."""

    def test_accepts_an_https_link(self):
        self.assertEqual(rainalert.clean_donation_url(DONATION_URL), DONATION_URL)

    def test_trims_surrounding_whitespace(self):
        self.assertEqual(
            rainalert.clean_donation_url(f"  {DONATION_URL}\n"), DONATION_URL)

    def test_empty_and_missing_values_mean_no_link(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(rainalert.clean_donation_url(value), "")

    def test_rejects_anything_that_is_not_an_absolute_https_link(self):
        for value in (
            "http://buymeacoffee.com/rainalert",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "//buymeacoffee.com/rainalert",
            "/donate",
            "buymeacoffee.com/rainalert",
            "https://",
            "https://buymeacoffee.com/a b",
            'https://buymeacoffee.com/"onmouseover="x',
            "https://[broken",
        ):
            with self.subTest(value=value):
                self.assertEqual(rainalert.clean_donation_url(value), "")


class TestDonationLink(AppTestCase):
    """The optional Buy Me a Coffee link."""

    def setUp(self):
        super().setUp()
        # A fixed locale keeps these tests independent of the locales that
        # happen to be installed on the machine running them.
        locale_patcher = mock.patch.object(rainalert, "DATE_LOCALE", "C")
        locale_patcher.start()
        self.addCleanup(locale_patcher.stop)

    def post(self, city="London"):
        return self.client.post("/", data={"city": city}).get_data(as_text=True)

    def test_no_link_by_default(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            for body in (self.client.get("/").get_data(as_text=True), self.post()):
                self.assertNotIn("buymeacoffee", body)
                self.assertNotIn("Buy me a coffee", body)
                self.assertNotIn('class="donate"', body)

    def test_start_page_has_only_the_footer_link(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.client.get("/").get_data(as_text=True)
        self.assertEqual(body.count(DONATION_HREF), 1)
        self.assertNotIn('class="donate"', body)

    def test_forecast_page_has_the_line_under_the_results_and_the_footer_link(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertEqual(body.count(DONATION_HREF), 2)
        self.assertIn("Saved you from getting wet?", body)
        self.assertIn("help keep Rain Alert free", body)
        # The line sits after the forecast list and before the footer.
        self.assertLess(body.index("weather-list"), body.index('class="donate"'))
        self.assertLess(body.index('class="donate"'), body.index("<footer"))

    def test_link_opens_safely_in_a_new_tab(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        anchors = [
            part.split(">", 1)[0] for part in body.split("<a ")
            if part.startswith(DONATION_HREF)
        ]
        self.assertEqual(len(anchors), 2)
        for anchor in anchors:
            self.assertIn('target="_blank"', anchor)
            self.assertIn('rel="noopener noreferrer"', anchor)

    def test_link_is_announced_as_a_donation_that_opens_a_new_tab(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertIn("(donation, opens in a new tab)", body)

    def test_no_line_under_the_results_on_error_pages(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            empty = self.client.post("/", data={"city": ""}).get_data(as_text=True)
            self.mock_geocode.return_value = None
            missing = self.post("Nowhereville")
        for body in (empty, missing):
            self.assertIn('class="error"', body)
            self.assertNotIn('class="donate"', body)

    def test_no_line_under_the_results_when_there_is_no_forecast(self):
        self.mock_get.return_value = FakeResponse({"daily": {}})
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertIn("No forecast data available", body)
        self.assertNotIn('class="donate"', body)

    def test_an_unsafe_value_in_the_environment_is_ignored(self):
        self.assertEqual(rainalert.clean_donation_url("javascript:alert(1)"), "")
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            self.assertNotIn("javascript:", self.post())


class TestAttribution(AppTestCase):
    """Open-Meteo's licence (CC BY 4.0) requires a credit; OSM data needs one too."""

    def setUp(self):
        super().setUp()
        locale_patcher = mock.patch.object(rainalert, "DATE_LOCALE", "C")
        locale_patcher.start()
        self.addCleanup(locale_patcher.stop)

    def assert_credits(self, body):
        self.assertIn('href="https://open-meteo.com/"', body)
        self.assertIn("Open-Meteo.com", body)
        self.assertIn('href="https://creativecommons.org/licenses/by/4.0/"', body)
        self.assertIn('href="https://www.openstreetmap.org/copyright"', body)
        self.assertIn("OpenStreetMap", body)

    def test_credits_are_on_the_start_page(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            self.assert_credits(self.client.get("/").get_data(as_text=True))

    def test_credits_are_on_the_forecast_page(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assert_credits(body)

    def test_credits_are_on_error_pages(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            body = self.client.post("/", data={"city": ""}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assert_credits(body)

    def test_credits_are_in_the_footer_and_open_safely(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            body = self.client.get("/").get_data(as_text=True)
        footer = body[body.index("<footer"):body.index("</footer>")]
        self.assertIn("open-meteo.com", footer)
        for anchor in footer.split("<a ")[1:]:
            opening = anchor.split(">", 1)[0]
            self.assertIn('rel="noopener noreferrer"', opening)


if __name__ == "__main__":
    unittest.main(verbosity=2)