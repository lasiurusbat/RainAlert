"""Tests for the RainAlert app.

Everything is mocked at the HTTP boundary, so the suite runs offline and
never touches Nominatim or Open-Meteo.
"""

import json
import os
import re
import unittest
from datetime import date
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
        self.assertIn("Wednesday 21.10.2026", body)
        self.assertIn("100%", body)
        self.assertIn("86%", body)
        self.assertNotIn('class="error"', body)

    def test_dates_use_weekday_and_dotted_format(self):
        """Dates render as 'Wednesday 21.10.2026'."""
        response = self.client.post("/", data={"city": "London"})
        body = response.get_data(as_text=True)
        self.assertIn("Thursday 22.10.2026", body)
        self.assertIn("Friday 23.10.2026", body)
        # The raw ISO form should no longer leak into the page.
        self.assertNotIn("2026-10-21", body)

    def test_weekdays_are_english_whatever_the_browser_asks_for(self):
        """The page is English, so the weekday names are English too.

        A half-translated date inside an English page is worse than a
        consistently English one, so the browser's language is ignored.
        """
        for header in ("de-DE,de;q=0.9,en;q=0.8", "nl-NL,nl;q=0.9", "fr-FR"):
            response = self.client.get(
                "/city/london", headers={"Accept-Language": header})
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
        self.assertIn("80%", body)

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
        self.assertIn("Wednesday 21.10.2026", body)
        self.assertIn("Thursday 22.10.2026", body)
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


class TestRainChanceLabel(AppTestCase):
    """'Chance of rain' is said once, in the column heading.

    The rows carry the number alone. Repeating the phrase on every row
    said nothing after the first one and made the list hard to scan.
    """

    def _body_for(self, chances):
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

    def _rows(self, body):
        """The visible chance of each row, in order."""
        return re.findall(
            r'<span class="chance" aria-hidden="true">([^<]*)</span>', body)

    def test_the_phrase_is_said_once(self):
        """The column heading carries the wording, not the rows."""
        body = self._body_for([10, 45, 80])
        self.assertEqual(body.count(">Rain chance<"), 1)

    def test_the_heading_is_its_own_element(self):
        """The heading is a class of its own, so CSS can line it up."""
        body = self._body_for([10])
        self.assertIn('<span class="column-head">Rain chance</span>', body)

    def test_the_heading_is_above_the_list(self):
        """The heading belongs to the list, so it sits directly above it."""
        body = self._body_for([10, 45, 80])
        self.assertLess(body.index("Rain chance"), body.index("weather-list"))

    def test_the_rows_carry_the_number_alone(self):
        body = self._body_for([10, 45, 80])
        self.assertEqual(self._rows(body), ["10%", "45%", "80%"])

    def test_a_row_does_not_repeat_the_phrase(self):
        """The whole point: the phrase is not in the visible list.

        It stays in the hidden span, because that is the text a screen
        reader gets instead of the bare number.
        """
        body = self._body_for([10, 45, 80])
        listing = body[body.index('class="weather-list"'):]
        visible = re.sub(r'<span class="sr-only">.*?</span>', "", listing,
                         flags=re.DOTALL)
        self.assertNotIn("chance of rain", visible)

    def test_the_screen_reader_still_gets_the_phrase(self):
        """The visible number is hidden from readers, so the phrase stands in."""
        body = self._body_for([10])
        self.assertIn('<span class="sr-only">10% chance of rain</span>', body)

    def test_the_umbrella_is_announced_too(self):
        body = self._body_for([80])
        self.assertIn("Take an umbrella.", body)

    def test_an_unknown_chance_is_not_shown_as_zero(self):
        """A missing value must never read as a dry day."""
        body = self._body_for([None])
        self.assertIn('<span class="chance" aria-hidden="true">unknown</span>', body)
        self.assertNotIn('<span class="chance" aria-hidden="true">0%</span>', body)

    def test_the_hourly_table_cell_is_the_number_alone(self):
        """The table has a real column heading, so the cell can be short."""
        payload = hourly_payload([63] * 24)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("<th scope=\"col\">Rain chance</th>", body)
        self.assertIn("<td>63%</td>", body)

    def test_the_hourly_tooltip_keeps_the_phrase(self):
        """A tooltip stands on its own, so it carries the whole wording."""
        payload = hourly_payload([63] * 24)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("63% chance of rain", body)


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
        self.assertIn("Wednesday 21.10.2026", body)
        self.assertIn("weather-list", body)

    def test_the_strip_does_not_break_the_daily_values(self):
        body = self._body_for([0] * 24)
        self.assertIn('<span class="chance" aria-hidden="true">100%</span>', body)
        self.assertIn('<span class="chance" aria-hidden="true">86%</span>', body)

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
        self.assertIn("Wednesday 21.10.2026", body)
        self.assertIn('<span class="chance" aria-hidden="true">100%</span>', body)

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


class TestForecastHeadline(AppTestCase):
    """The one-line headline above the daily list."""

    def _forecast(self, chances, days=None):
        """A forecast list in the shape app.py builds it."""
        dates = days or [f"2026-10-{21 + offset:02d}" for offset in range(len(chances))]
        forecast = []
        for day, chance in zip(dates, chances):
            band = rainalert.severity_band(chance)
            forecast.append({
                "date": rainalert.format_date(day),
                "iso_date": day,
                "rain_label": rainalert.format_rain_chance(chance),
                "chance": chance,
                "severity": band,
                "severity_label": rainalert.severity_label(band),
                "umbrella": rainalert.needs_umbrella(chance),
            })
        return forecast

    def _headline(self, chances, days=None, hours=None):
        return rainalert.forecast_headline(
            self._forecast(chances, days), hours)

    def test_a_wet_day_names_the_day_and_the_chance(self):
        headline = self._headline([0, 80, 0, 0, 0, 0, 0])
        self.assertIn("Rain likely tomorrow", headline["text"])
        self.assertIn("80%", headline["text"])
        self.assertIn("Bring an umbrella", headline["text"])
        self.assertEqual(headline["severity"], "high")
        self.assertTrue(headline["umbrella"])

    def test_today_is_named_today(self):
        headline = self._headline([80, 0, 0, 0, 0, 0, 0])
        self.assertIn("today", headline["text"])

    def test_a_later_day_is_named_by_its_weekday(self):
        """Beyond tomorrow the banner names the weekday, like the list does."""
        # 2026-10-24 is a Saturday.
        headline = self._headline([0, 0, 0, 55, 0, 0, 0])
        self.assertIn("Saturday", headline["text"])
        self.assertIn("55%", headline["text"])

    def test_the_first_wet_day_wins(self):
        headline = self._headline([0, 60, 90, 0, 0, 0, 0])
        self.assertIn("tomorrow", headline["text"])
        self.assertIn("60%", headline["text"])
        self.assertNotIn("90%", headline["text"])

    def test_a_possible_day_says_possible(self):
        """Below the umbrella threshold the banner does not urge an umbrella."""
        headline = self._headline([0, 45, 0, 0, 0, 0, 0])
        self.assertIn("Rain possible tomorrow", headline["text"])
        self.assertIn("45%", headline["text"])
        self.assertNotIn("umbrella", headline["text"].lower())
        self.assertEqual(headline["severity"], "moderate")
        self.assertFalse(headline["umbrella"])

    def test_a_dry_week_says_so(self):
        headline = self._headline([0, 5, 10, 0, 0, 0, 0])
        self.assertIn("No rain likely for the next 7 days", headline["text"])
        self.assertEqual(headline["severity"], "low")
        self.assertFalse(headline["umbrella"])

    def test_a_week_with_an_unknown_day_is_not_called_dry(self):
        """A missing value is not a 0% chance, so the week is not all dry."""
        headline = self._headline([0, 5, None, 0, 0, 0, 0])
        self.assertIn("most of", headline["text"])
        self.assertNotIn("No rain likely for the next", headline["text"])

    def test_a_week_with_no_values_at_all_says_the_chance_is_unknown(self):
        headline = self._headline([None] * 7)
        self.assertIn("unknown", headline["text"])
        self.assertEqual(headline["severity"], "unknown")

    def test_a_week_that_is_mostly_unknown_says_so(self):
        """A claim about "most of" would be a claim about unreported days."""
        headline = self._headline([5, None, None, None, None, None, None])
        self.assertIn("unknown", headline["text"])
        self.assertEqual(headline["severity"], "unknown")
        self.assertNotIn("No rain likely", headline["text"])

    def test_today_is_judged_on_the_hours_that_are_left(self):
        """The daily maximum covers the whole day, but the reader has today."""
        hours = [{"chance": 5, "past": False}]
        # The daily maximum is 100, but only a dry evening is left.
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertNotIn("Rain likely today", headline["text"])

    def test_todays_sentence_says_which_figure_it_uses(self):
        """The hourly figure and the daily figure are different quantities."""
        hours = [{"chance": 80, "past": False}]
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("for the rest of today", headline["text"])
        self.assertIn("80%", headline["text"])
        # The daily maximum is 100, and the sentence does not quote it.
        self.assertNotIn("100%", headline["text"])

    def test_the_hours_that_are_left_can_still_make_today_wet(self):
        hours = [{"chance": 80, "past": False}]
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("Rain likely for the rest of today", headline["text"])
        self.assertIn("80%", headline["text"])

    def test_the_umbrella_advice_is_dropped_when_today_is_already_over(self):
        """The rain is behind us, so an umbrella would be no use."""
        hours = [{"chance": 0, "past": False}]
        headline = self._headline([80, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertNotIn("today", headline["text"])
        self.assertNotIn("umbrella", headline["text"].lower())
        self.assertFalse(headline["umbrella"])

    def test_today_is_left_out_once_the_day_is_over(self):
        """A day that has been and gone is not worth the banner's one line."""
        headline = self._headline([80, 40, 0, 0, 0, 0, 0], hours=[])
        self.assertIn("tomorrow", headline["text"])
        self.assertNotIn("today", headline["text"])

    def test_the_week_is_described_as_the_rest_of_it_when_today_is_over(self):
        headline = self._headline([80, 5, 0, 0, 0, 0, 0], hours=[])
        self.assertIn("the rest of the week", headline["text"])

    def test_the_umbrella_advice_stays_for_a_later_day(self):
        """Only today's advice is affected by the hours that are left."""
        hours = [{"chance": 0, "past": False}]
        headline = self._headline([0, 80, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("Bring an umbrella", headline["text"])

    def test_an_empty_forecast_has_no_headline(self):
        self.assertIsNone(rainalert.forecast_headline([]))

    def test_the_sentence_ends_in_a_period(self):
        for chances in ([0, 80, 0], [0, 45, 0], [0, 5, 0], [None, None]):
            with self.subTest(chances=chances):
                headline = self._headline(chances)
                self.assertTrue(headline["text"].endswith("."))

    def test_the_sentence_starts_with_a_capital(self):
        headline = self._headline([0, 80, 0, 0, 0, 0, 0])
        self.assertTrue(headline["text"][0].isupper())

    def test_the_banner_appears_above_the_list(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("headline", body)
        self.assertLess(body.index("headline"), body.index("weather-list"))
        self.assertLess(body.index("headline"), body.index("hourly-strip"))

    def test_the_banner_is_absent_without_a_forecast(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("headline", body)

    def test_the_banner_is_absent_on_an_error_page(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assertNotIn("headline", body)

    def test_the_banner_agrees_with_the_row_it_names(self):
        """The banner and the list must not disagree about a day."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        # The mocked forecast is wet today and tomorrow, and the mocked
        # current time is 09:00 with a dry day ahead, so the banner names
        # tomorrow - the same 86% the row for tomorrow carries.
        self.assertIn("Rain likely tomorrow (86%)", body)
        self.assertIn('<span class="chance" aria-hidden="true">86%</span>', body)

    def test_the_band_is_in_the_sentence_not_only_in_the_colour(self):
        """Severity never rests on the colour alone."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        # The banner carries a band class, but the sentence names the band.
        banner = body.split('class="headline')[1][:400]
        self.assertIn("Rain likely", banner)


class TestTabAlert(AppTestCase):
    """The tab title and the favicon, which are the alert itself."""

    def _forecast(self, chances, days=None):
        """A forecast list in the shape app.py builds it."""
        dates = days or [f"2026-10-{21 + offset:02d}" for offset in range(len(chances))]
        forecast = []
        for day, chance in zip(dates, chances):
            forecast.append({
                "date": rainalert.format_date(day),
                "iso_date": day,
                "chance": chance,
            })
        return forecast

    def _alert(self, chances, days=None, hours=None):
        return rainalert.tab_alert(self._forecast(chances, days), hours)

    def _body_with(self, payload):
        self.mock_get.return_value = FakeResponse(payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    # -- the day label --------------------------------------------------------

    def test_the_first_day_is_today(self):
        self.assertEqual(rainalert.tab_day_label("2026-10-21", 0), "today")

    def test_the_second_day_is_tomorrow(self):
        self.assertEqual(rainalert.tab_day_label("2026-10-22", 1), "tomorrow")

    def test_a_later_day_is_named_by_its_weekday(self):
        # 2026-10-24 is a Saturday.
        self.assertEqual(rainalert.tab_day_label("2026-10-24", 3), "Saturday")

    def test_an_unreadable_date_still_names_the_day(self):
        self.assertEqual(rainalert.tab_day_label("not a date", 3), "in 3 days")

    # -- when the alert fires -------------------------------------------------

    def test_a_wet_day_alerts(self):
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertIsNotNone(alert)
        self.assertEqual(alert["when"], "tomorrow")
        self.assertEqual(alert["chance"], 80)

    def test_the_title_names_the_day(self):
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertEqual(rainalert.page_title(None, alert),
                         "Rain tomorrow - Rain Alert")

    def test_the_title_names_the_city_as_well(self):
        """A title that says only "Rain tomorrow" says nothing about which
        city the page is about."""
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertEqual(rainalert.page_title("London", alert),
                         "Rain tomorrow in London - Rain Alert")

    def test_a_dry_week_does_not_alert(self):
        self.assertIsNone(self._alert([0, 5, 10, 0, 0, 0, 0]))

    def test_a_day_below_the_umbrella_threshold_does_not_alert(self):
        """The same threshold that puts the umbrella on the row."""
        self.assertIsNone(self._alert([0, 49, 0, 0, 0, 0, 0]))

    def test_a_day_at_the_umbrella_threshold_alerts(self):
        self.assertIsNotNone(self._alert([0, 50, 0, 0, 0, 0, 0]))

    def test_the_first_wet_day_wins(self):
        alert = self._alert([0, 60, 90, 0, 0, 0, 0])
        self.assertEqual(alert["when"], "tomorrow")
        self.assertEqual(alert["chance"], 60)

    def test_an_unreported_day_does_not_alert(self):
        """A missing value is not a 0% chance, so it is not a dry day."""
        self.assertIsNone(self._alert([None, None, None]))

    def test_an_unreported_day_does_not_hide_a_wet_one(self):
        alert = self._alert([None, 80, None])
        self.assertEqual(alert["when"], "tomorrow")

    def test_an_empty_forecast_does_not_alert(self):
        self.assertIsNone(rainalert.tab_alert([]))

    # -- today is judged on the hours that are left ----------------------------

    def test_today_is_judged_on_the_hours_that_are_left(self):
        """The daily maximum covers the whole day, but the reader has today."""
        hours = [{"chance": 5, "past": False}]
        alert = self._alert([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIsNone(alert)

    def test_the_hours_that_are_left_can_still_make_today_wet(self):
        hours = [{"chance": 80, "past": False}]
        alert = self._alert([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertEqual(alert["when"], "today")
        self.assertEqual(alert["chance"], 80)

    def test_a_day_that_is_over_is_left_out(self):
        """A day that has been and gone is not worth the title."""
        alert = self._alert([80, 60, 0, 0, 0, 0, 0], hours=[])
        self.assertEqual(alert["when"], "tomorrow")

    def test_a_day_that_is_over_does_not_alert_on_its_own(self):
        """Today's downpour is behind us, so it buys no alert."""
        self.assertIsNone(self._alert([80, 5, 0, 0, 0, 0, 0], hours=[]))

    # -- the page -------------------------------------------------------------

    def test_the_title_carries_the_alert(self):
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("<title>Rain tomorrow in London - Rain Alert</title>", body)

    def test_the_favicon_carries_the_alert(self):
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("favicon-rain.svg", body)

    def test_a_dry_forecast_keeps_the_plain_title(self):
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22", "2026-10-23"],
                "precipitation_probability_max": [5, 10, 0],
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
        body = self._body_with(payload)
        self.assertIn("<title>7-day rain chance for London - Rain Alert</title>", body)
        self.assertIn("favicon.svg", body)
        self.assertNotIn("favicon-rain.svg", body)

    def test_an_empty_page_keeps_the_plain_title(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("<title>Rain Alert - 7-day rain chance for any city</title>", body)

    def test_an_error_page_keeps_the_plain_title(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assertIn("<title>7-day rain chance for Nowhereville - Rain Alert</title>", body)
        self.assertNotIn("favicon-rain.svg", body)

    def test_the_title_agrees_with_the_banner(self):
        """The tab and the banner are the same alert, so they cannot disagree."""
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("<title>Rain tomorrow in London - Rain Alert</title>", body)
        self.assertIn("Rain likely tomorrow (86%)", body)


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
        """The row shows the number alone; the wording is in the header."""
        self.assertEqual(rainalert.format_rain_chance(100), "100%")
        self.assertEqual(rainalert.format_rain_chance(86.4), "86%")
        self.assertEqual(rainalert.format_rain_chance(0), "0%")
        self.assertEqual(rainalert.format_rain_chance(None), "unknown")

    def test_describe_rain_chance(self):
        """The full phrase is what a screen reader and a tooltip need."""
        self.assertEqual(
            rainalert.describe_rain_chance(100), "100% chance of rain")
        self.assertEqual(
            rainalert.describe_rain_chance(86.4), "86% chance of rain")
        self.assertEqual(
            rainalert.describe_rain_chance(0), "0% chance of rain")
        self.assertEqual(
            rainalert.describe_rain_chance(None), "chance of rain unknown"
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


class TestTemperatureUnit(AppTestCase):
    """The Celsius/Fahrenheit switch beside the legend."""

    def test_celsius_is_the_default(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        _, kwargs = self.mock_get.call_args
        self.assertEqual(kwargs["params"]["temperature_unit"], "celsius")
        self.assertIn("is-active", body)

    def test_the_unit_is_asked_for_by_name(self):
        """The service converts the values, so the app never does the maths."""
        self.client.post("/", data={"city": "London", "unit": "fahrenheit"})
        _, kwargs = self.mock_get.call_args
        self.assertEqual(kwargs["params"]["temperature_unit"], "fahrenheit")

    def test_the_unit_can_be_switched_with_a_link(self):
        """The switch is a link, so it works without JavaScript."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("unit=fahrenheit", body)
        self.assertIn("unit=celsius", body)

    def test_the_link_keeps_the_city(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("city=London", body)

    def test_a_get_with_a_city_and_a_unit_returns_that_forecast(self):
        body = self.client.get("/?city=London&unit=fahrenheit",
                                follow_redirects=True).get_data(as_text=True)
        _, kwargs = self.mock_get.call_args
        self.assertEqual(kwargs["params"]["temperature_unit"], "fahrenheit")
        self.assertIn("7-day rain chance for London", body)

    def test_the_active_unit_is_marked(self):
        body = self.client.get("/?city=London&unit=fahrenheit",
                                follow_redirects=True).get_data(as_text=True)
        # The Fahrenheit link is the active one, and the Celsius one is not.
        switch = body[body.index("unit-switch"):body.index("weather-list")]
        anchors = [part.split(">", 1)[0] for part in switch.split("<a ")[1:]]
        self.assertEqual(len(anchors), 2)
        by_unit = {anchor.split("unit=")[1].split('"')[0]: anchor
                   for anchor in anchors}
        self.assertIn("is-active", by_unit["fahrenheit"])
        self.assertNotIn("is-active", by_unit["celsius"])

    def test_the_active_unit_is_marked_for_screen_readers(self):
        body = self.client.get("/?city=London&unit=fahrenheit",
                                follow_redirects=True).get_data(as_text=True)
        self.assertIn('aria-current="true"', body)

    def test_an_unknown_unit_falls_back_to_the_default(self):
        """A stray query parameter must not break the page."""
        self.client.get("/?city=London&unit=kelvin", follow_redirects=True)
        _, kwargs = self.mock_get.call_args
        self.assertEqual(kwargs["params"]["temperature_unit"], "celsius")

    def test_the_switch_is_not_on_the_start_page(self):
        """There is nothing to switch until a forecast is on the page."""
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("unit-switch", body)

    def test_the_switch_is_in_the_legend_row(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        legend = body[body.index("severity-legend"):body.index("weather-list")]
        self.assertIn("unit-switch", legend)
        self.assertIn("Rain likely", legend)

    def test_the_switch_does_not_add_a_request(self):
        """Switching the unit re-uses the same single forecast request."""
        self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_get.call_count, 1)

    def test_the_unit_survives_a_new_search(self):
        """Searching another city keeps the scale the reader chose."""
        body = self.client.get("/?city=London&unit=fahrenheit",
                                follow_redirects=True).get_data(as_text=True)
        self.assertIn('name="unit" value="fahrenheit"', body)


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

    def post(self, city="London"):
        return self.client.post("/", data={"city": city}).get_data(as_text=True)

    def test_no_link_by_default(self):
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            for body in (self.client.get("/").get_data(as_text=True), self.post()):
                self.assertNotIn("buymeacoffee", body)
                self.assertNotIn("Buy me a coffee", body)
                self.assertNotIn('class="donate"', body)

    def test_start_page_has_the_line_and_the_footer_link(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.client.get("/").get_data(as_text=True)
        self.assertEqual(body.count(DONATION_HREF), 2)
        self.assertIn('class="donate"', body)

    def test_forecast_page_has_the_line_under_the_button_and_the_footer_link(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertEqual(body.count(DONATION_HREF), 2)
        self.assertIn("Saved you from getting wet?", body)
        self.assertIn("help keep Rain Alert free", body)
        # The line sits between the button and the forecast, and before the
        # footer link.
        self.assertLess(body.index(">Search</button>"), body.index('class="donate"'))
        self.assertLess(body.index('class="donate"'), body.index("weather-list"))
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

    def test_the_line_is_on_error_pages_too(self):
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            empty = self.client.post("/", data={"city": ""}).get_data(as_text=True)
            self.mock_geocode.return_value = None
            missing = self.post("Nowhereville")
        for body in (empty, missing):
            self.assertIn('class="error"', body)
            self.assertIn('class="donate"', body)

    def test_the_line_is_shown_when_there_is_no_forecast(self):
        self.mock_get.return_value = FakeResponse({"daily": {}})
        with mock.patch.object(rainalert, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertIn("No forecast data available", body)
        self.assertIn('class="donate"', body)

    def test_an_unsafe_value_in_the_environment_is_ignored(self):
        self.assertEqual(rainalert.clean_donation_url("javascript:alert(1)"), "")
        with mock.patch.object(rainalert, "DONATION_URL", ""):
            self.assertNotIn("javascript:", self.post())


class TestBuildInfo(AppTestCase):
    """Which build is answering, said in the footer.

    The version and the commit come from the environment, and the release
    build sets them. A development run says "dev" and names no commit,
    because a working tree is not a commit.
    """

    def footer(self, body):
        """The footer's own text, without the rest of the page."""
        start = body.index("<footer")
        return body[start:body.index("</footer>")]

    def test_the_version_is_in_the_footer(self):
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))

    def test_the_commit_is_in_the_footer_when_there_is_one(self):
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"), \
                mock.patch.object(rainalert, "APP_COMMIT", "1a2b3c4"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8 · build 1a2b3c4", self.footer(body))

    def test_no_commit_means_no_build_note(self):
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"), \
                mock.patch.object(rainalert, "APP_COMMIT", ""):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))
        # The word "build" is only in the markup's class name, so it is the
        # separator that marks the build note that has to be absent.
        self.assertNotIn("· build", self.footer(body))

    def test_a_development_build_says_so(self):
        with mock.patch.object(rainalert, "APP_VERSION", "dev"), \
                mock.patch.object(rainalert, "APP_COMMIT", ""):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version dev", self.footer(body))

    def test_the_version_is_on_every_page(self):
        """The forecast page, the city index and the 404 all carry it."""
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"), \
                mock.patch.object(rainalert, "APP_COMMIT", "1a2b3c4"):
            forecast = self.client.post(
                "/", data={"city": "London"}).get_data(as_text=True)
            cities = self.client.get("/cities").get_data(as_text=True)
            missing = self.client.get("/city/nowhereville").get_data(as_text=True)
        for body in (forecast, cities, missing):
            self.assertIn("Version 0.8 · build 1a2b3c4", self.footer(body))

    def test_the_version_is_below_the_credits(self):
        """It sits under the data credits, where the eye goes last."""
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertLess(body.index("OpenStreetMap"), body.index("Version 0.8"))


class TestReleaseNotes(AppTestCase):
    """The release notes, and the link to them.

    The notes are a page like any other, and the footer links to them from
    everywhere else. The footer is one macro, so the link cannot be on one
    page and missing from the next.
    """

    def footer(self, body):
        """The footer's own text, without the rest of the page."""
        start = body.index("<footer")
        return body[start:body.index("</footer>")]

    def pages(self):
        """Every page of the site, and its body."""
        bodies = [self.client.get("/").get_data(as_text=True),
                  self.client.get("/cities").get_data(as_text=True),
                  self.client.get("/city/london").get_data(as_text=True),
                  self.client.get("/no-such-page").get_data(as_text=True)]
        return bodies

    # -- the page ---------------------------------------------------------------

    def test_the_page_answers(self):
        response = self.client.get("/release-notes")
        self.assertEqual(response.status_code, 200)

    def test_the_page_says_what_it_is(self):
        """A title, a description, a canonical link and a social card."""
        body = self.client.get("/release-notes").get_data(as_text=True)
        self.assertIn("<title>Release notes - Rain Alert</title>", body)
        self.assertIn('<meta name="description" content="', body)
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/release-notes">',
            body)
        self.assertIn('<meta property="og:title" content="', body)

    def test_the_page_is_in_the_sitemap(self):
        body = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<loc>https://rainalert.live/release-notes</loc>", body)

    def test_the_page_carries_every_release(self):
        body = self.client.get("/release-notes").get_data(as_text=True)
        for release in rainalert.RELEASES:
            self.assertIn(release["version"], body)
            self.assertIn(release["name"], body)

    def test_the_releases_are_newest_first(self):
        versions = [release["version"] for release in rainalert.RELEASES]
        self.assertEqual(versions, sorted(versions, reverse=True))

    def test_every_release_says_something(self):
        """A release with no points is a heading and nothing else."""
        for release in rainalert.RELEASES:
            self.assertTrue(release["points"], release["version"])
            for point in release["points"]:
                self.assertTrue(point.strip(), release["version"])

    def test_the_page_says_which_build_is_answering(self):
        """The notes and the footer agree about the running build."""
        with mock.patch.object(rainalert, "APP_VERSION", "0.8"):
            body = self.client.get("/release-notes").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))
        self.assertIn('<span class="notes-version">0.8</span>', body)

    # -- the link to it ---------------------------------------------------------

    def test_the_footer_links_to_the_release_notes(self):
        """From every page, including the error page."""
        for body in self.pages():
            self.assertIn('<a class="release-link" href="/release-notes">',
                          self.footer(body))

    def test_the_link_is_after_the_version(self):
        """The version comes first, then the separator, then the link."""
        for body in self.pages():
            footer = self.footer(body)
            self.assertLess(footer.index("Version "),
                             footer.index("Release notes"))
            self.assertIn('<span class="build-sep" aria-hidden="true">|</span>',
                          footer)

    def test_the_page_does_not_link_to_itself(self):
        """A link to the page you are already on is not an offer."""
        body = self.client.get("/release-notes").get_data(as_text=True)
        self.assertNotIn("release-link", body)

    def test_the_footer_is_the_same_on_every_page(self):
        """One macro, so the footer cannot drift from page to page."""
        footers = {self.footer(body) for body in self.pages()}
        self.assertEqual(len(footers), 1)


class TestBrowserPreferences(AppTestCase):
    """Tier 2: the saved city and the personal alert threshold.

    Both live in the browser's localStorage, so the server's part is small:
    the page has to carry the controls, the numbers the threshold is
    compared against, and enough for the script to know what kind of page
    it is looking at. The script's own behaviour is tested in
    test_browser.py, which drives a real browser.
    """

    def _body_for(self, chances):
        """A forecast page with the given daily rain chances."""
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + offset:02d}"
                         for offset in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    # -- the controls ---------------------------------------------------------

    def test_the_preferences_row_is_on_the_page(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="remember-city"', body)
        self.assertIn('id="alert-threshold"', body)

    def test_the_preferences_row_is_on_the_forecast_page(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('id="remember-city"', body)
        self.assertIn('id="alert-threshold"', body)

    def test_the_threshold_is_a_percentage(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="alert-threshold" min="0" max="100"', body)

    def test_the_script_is_loaded(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("app.js", body)
        self.assertIn("defer", body)

    def test_the_row_starts_hidden_without_javascript(self):
        """Without the script neither control can do anything."""
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="no-js"', body)

    # -- the numbers the threshold is compared against ------------------------

    def test_each_day_carries_the_number_it_shows(self):
        """The threshold and the number on the page are the same value."""
        body = self._body_for([10, 45, 80])
        for chance in (10, 45, 80):
            self.assertIn(f'data-chance="{chance}"', body)

    def test_the_number_is_the_rounded_one(self):
        """A day shown as 45% is 45 here, not 44.6."""
        body = self._body_for([44.6, 46.5])
        self.assertIn('data-chance="45"', body)
        self.assertIn('data-chance="47"', body)
        self.assertNotIn('data-chance="44.6"', body)

    def test_an_unreported_day_carries_no_number(self):
        """A missing value is never counted as a dry day."""
        body = self._body_for([None, 80])
        self.assertNotIn('data-chance="None"', body)
        self.assertEqual(body.count('data-chance="'), 1)
        self.assertIn('data-chance="80"', body)

    # -- what kind of page is this --------------------------------------------

    def test_the_start_page_may_load_a_remembered_city(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-autoload="1"', body)

    def test_a_forecast_page_does_not_load_a_remembered_city(self):
        """The reader is already looking at a forecast."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('data-autoload="0"', body)

    def test_an_error_page_does_not_load_a_remembered_city(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('data-autoload="0"', body)

    def test_the_page_says_whether_the_search_worked(self):
        """Only a search that worked is worth remembering."""
        start = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-search="none"', start)

        good = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('data-search="ok"', good)

        self.mock_geocode.return_value = None
        bad = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('data-search="error"', bad)

    def test_the_page_says_which_city_was_searched(self):
        """The script compares it with the city that was submitted."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('data-city="London"', body)

    def test_the_page_says_which_temperature_unit_is_in_use(self):
        """The remembered city is loaded in the scale the page is in."""
        body = self.client.get("/?unit=fahrenheit").get_data(as_text=True)
        self.assertIn('data-unit="fahrenheit"', body)


class TestAlertThreshold(unittest.TestCase):
    """Which rain chance is worth a notification."""

    def test_without_one_the_apps_own_threshold_is_used(self):
        threshold, personal = rainalert.alert_threshold(None)
        self.assertEqual(threshold, rainalert.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_an_empty_threshold_is_the_apps_own(self):
        threshold, personal = rainalert.alert_threshold("  ")
        self.assertEqual(threshold, rainalert.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_the_readers_own_threshold_is_used_when_there_is_one(self):
        threshold, personal = rainalert.alert_threshold(40)
        self.assertEqual(threshold, 40)
        self.assertTrue(personal)

    def test_a_threshold_of_zero_is_not_taken_for_missing(self):
        """Zero is a limit like any other, not an absent one."""
        threshold, personal = rainalert.alert_threshold(0)
        self.assertEqual(threshold, 0)
        self.assertTrue(personal)

    def test_a_nonsense_threshold_falls_back_to_the_apps_own(self):
        threshold, personal = rainalert.alert_threshold("wet")
        self.assertEqual(threshold, rainalert.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_a_threshold_is_capped_at_a_hundred(self):
        threshold, _ = rainalert.alert_threshold(150)
        self.assertEqual(threshold, 100)


class TestNotificationEvent(unittest.TestCase):
    """What is worth interrupting the reader for."""

    def event(self, chances, threshold=None, now="2026-10-21T09:00",
              personal=False, city="London"):
        payload = hourly_payload(chances, now=now)
        hours = rainalert.parse_today_hours(payload)
        if threshold is None:
            threshold = rainalert.UMBRELLA_THRESHOLD
        return rainalert.notification_event(
            hours, threshold, city, personal)

    def test_nothing_to_say_about_a_dry_day(self):
        self.assertIsNone(self.event([0] * 24))

    def test_nothing_to_say_without_hourly_data(self):
        self.assertIsNone(rainalert.notification_event(
            [], rainalert.UMBRELLA_THRESHOLD, "London"))

    def test_rain_in_the_current_hour_is_worth_saying(self):
        event = self.event([0] * 9 + [80] + [0] * 14)
        self.assertIsNotNone(event)
        self.assertEqual(event["key"], "now:2026-10-21")
        self.assertEqual(event["title"], "Rain likely right now")
        self.assertIn("80% chance of rain in London right now.", event["body"])

    def test_rain_about_to_start_is_worth_saying(self):
        event = self.event([0] * 10 + [80] + [0] * 13)
        self.assertEqual(event["key"], "hour:2026-10-21T10:00")
        self.assertEqual(event["title"], "Rain likely from 10:00")
        self.assertIn("80% chance of rain in London at 10:00.", event["body"])

    def test_rain_further_off_than_the_lead_is_not_worth_saying(self):
        """Two hours away is the edge; three is too far to act on."""
        self.assertIsNone(self.event([0] * 12 + [80] + [0] * 11))
        event = self.event([0] * 11 + [80] + [0] * 12)
        self.assertIsNotNone(event)

    def test_hours_that_have_gone_are_not_worth_saying(self):
        """The morning's downpour is not news at nine in the morning."""
        self.assertIsNone(self.event([80] * 9 + [0] * 15))

    def test_an_unreported_hour_is_never_a_wet_hour(self):
        """A missing value is not a chance of rain."""
        payload = hourly_payload(
            [0] * 10 + [None] + [0] * 13, now="2026-10-21T09:00")
        hours = rainalert.parse_today_hours(payload)
        self.assertIsNone(rainalert.notification_event(
            hours, rainalert.UMBRELLA_THRESHOLD, "London"))

    def test_the_readers_own_threshold_decides_what_counts(self):
        """A 20% hour is nothing to the app and something to the reader."""
        self.assertIsNone(self.event([0] * 10 + [20] + [0] * 13, threshold=50))
        event = self.event([0] * 10 + [20] + [0] * 13, threshold=20)
        self.assertEqual(event["title"], "Rain unlikely from 10:00")

    def test_the_readers_own_threshold_is_named_in_the_body(self):
        event = self.event([0] * 10 + [45] + [0] * 13, threshold=40,
                            personal=True)
        self.assertIn("45% chance of rain in London at 10:00.", event["body"])
        self.assertIn("Above your 40% threshold.", event["body"])

    def test_the_apps_own_advice_brings_the_umbrella(self):
        event = self.event([0] * 10 + [80] + [0] * 13)
        self.assertIn("Bring an umbrella.", event["body"])

    def test_the_umbrella_is_not_mixed_into_the_readers_own_alert(self):
        """The reader's limit is their own answer, not the app's advice."""
        event = self.event([0] * 10 + [45] + [0] * 13, threshold=40,
                            personal=True)
        self.assertNotIn("umbrella", event["body"].lower())


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
        self.assertEqual(data["poll_minutes"], rainalert.NOTIFICATION_POLL_MINUTES)
        self.assertEqual(data["lead_hours"], rainalert.NOTIFICATION_LEAD_HOURS)

    def test_the_readers_own_threshold_is_used_when_it_is_sent(self):
        _, data = self.alert("?city=London&threshold=90")
        self.assertEqual(data["threshold"], 90)
        self.assertTrue(data["personal_threshold"])
        self.assertIsNone(data["event"])

    def test_without_a_threshold_the_apps_own_is_used(self):
        _, data = self.alert("?city=London")
        self.assertEqual(data["threshold"], rainalert.UMBRELLA_THRESHOLD)
        self.assertFalse(data["personal_threshold"])

    def test_an_unknown_city_is_reported(self):
        self.mock_geocode.return_value = None
        response, data = self.alert("?city=Nowhereville")
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", data["error"])

    def test_a_geocoder_outage_is_not_reported_as_a_missing_city(self):
        self.mock_geocode.side_effect = rainalert.GeocodingUnavailable("down")
        response, data = self.alert("?city=London")
        self.assertEqual(response.status_code, 503)
        self.assertIn("geocoding service", data["error"])

    def test_a_weather_outage_is_reported(self):
        self.mock_get.side_effect = rainalert.WeatherUnavailable("down")
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


class TestCalendarFile(unittest.TestCase):
    """The calendar file itself: the parts that do not need a server.

    The format is iCalendar (RFC 5545), so a file that is nearly right is a
    file that no calendar app can read.
    """

    def test_the_text_of_a_value_is_escaped(self):
        """A comma would otherwise split the value in two."""
        self.assertEqual(rainalert.calendar_escape("a,b"), "a\\,b")
        self.assertEqual(rainalert.calendar_escape("a;b"), "a\\;b")
        self.assertEqual(rainalert.calendar_escape("a\\b"), "a\\\\b")
        self.assertEqual(rainalert.calendar_escape("a\nb"), "a\\nb")

    def test_a_long_line_is_folded(self):
        """A content line may not be longer than 75 octets."""
        folded = rainalert.calendar_fold("x" * 200)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertTrue(folded.split("\r\n")[1].startswith(" "))

    def test_a_short_line_is_left_alone(self):
        self.assertEqual(rainalert.calendar_fold("SUMMARY:Rain"), "SUMMARY:Rain")

    def test_a_name_with_an_umlaut_is_not_cut_in_half(self):
        """The length is counted in octets, not in characters."""
        folded = rainalert.calendar_fold("SUMMARY:München" * 10)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertIn("München", folded)

    def test_a_date_becomes_an_icalendar_date(self):
        self.assertEqual(rainalert.calendar_day("2026-10-21"), "20261021")
        self.assertEqual(rainalert.calendar_next_day("2026-10-21"), "20261022")

    def test_the_day_after_a_month_is_the_first_of_the_next(self):
        """The end of an all-day event is the start of the next day.

        A month or a year has to roll over, and a leap day has to be
        counted, or the event covers the wrong days.
        """
        self.assertEqual(rainalert.calendar_next_day("2026-10-31"), "20261101")
        self.assertEqual(rainalert.calendar_next_day("2026-12-31"), "20270101")
        self.assertEqual(rainalert.calendar_next_day("2028-02-28"), "20280229")
        self.assertEqual(rainalert.calendar_next_day("2026-02-28"), "20260301")

    def test_an_unreadable_date_is_left_out(self):
        self.assertEqual(rainalert.calendar_day("not a date"), "")
        self.assertEqual(rainalert.calendar_next_day("not a date"), "")

    def test_the_file_name_is_safe(self):
        self.assertEqual(rainalert.calendar_slug("London, England"), "london-england")
        self.assertEqual(rainalert.calendar_slug("../../etc/passwd"), "etc-passwd")
        self.assertEqual(rainalert.calendar_slug(""), "forecast")

    def test_the_calendar_has_a_header_and_a_footer(self):
        text = rainalert.build_calendar([], "London", 50)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))

    def test_the_lines_end_with_carriage_returns(self):
        """A calendar file is read line by line, and the lines end in CRLF."""
        text = rainalert.build_calendar([], "London", 50)
        self.assertIn("\r\n", text)
        self.assertNotIn("\n\n", text)
        for line in text.split("\r\n")[:-1]:
            self.assertNotIn("\n", line)

    def test_no_line_of_the_finished_file_is_too_long(self):
        """The 75-octet limit is a property of the file, not of one value.

        The description, the summary and the calendar name are all built
        out of what the page says, so a long city name can make any of
        them long.
        """
        text = rainalert.build_calendar(
            [{"iso_date": "2026-10-21", "date": "Wednesday 21.10.2026",
              "chance": 80, "chance_number": 80, "severity": "high"}],
            "München, Bayern, Deutschland", 50)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)


class TestCalendarExport(AppTestCase):
    """Tier 2: the rainy days as a calendar file the reader can import.

    The file is built on the server, so the rule that decides which days
    go into it is tested here and not in the browser.
    """

    def payload(self, chances):
        return {
            "daily": {
                "time": [f"2026-10-{21 + offset:02d}"
                         for offset in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }

    def export(self, query="?city=London", chances=(100, 86, 40)):
        self.mock_get.return_value = FakeResponse(
            payload=self.payload(list(chances)))
        return self.client.get("/calendar.ics" + query)

    def text(self, query="?city=London", chances=(100, 86, 40)):
        return self.export(query, chances).get_data(as_text=True)

    def readable(self, query="?city=London", chances=(100, 86, 40)):
        """The file with the folded lines joined back together.

        A long description is split over several lines, so a sentence in it
        is only whole again once the file has been unfolded.
        """
        lines = self.text(query, chances).split("\r\n")
        joined = []
        for line in lines:
            if line.startswith(" ") and joined:
                joined[-1] += line[1:]
            else:
                joined.append(line)
        return "\r\n".join(joined)

    # -- the request -----------------------------------------------------------

    def test_it_needs_a_city(self):
        response = self.export("?city=")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Please enter a city name.",
                      response.get_data(as_text=True))

    def test_the_file_is_a_calendar(self):
        response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response.headers["Content-Type"])
        # The city can be anything, so the file has to say it is UTF-8.
        self.assertIn("charset=utf-8", response.headers["Content-Type"])

    def test_the_file_is_offered_as_a_download(self):
        response = self.export()
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("rain-alert-london.ics",
                      response.headers["Content-Disposition"])

    def test_the_file_is_never_cached(self):
        """It holds a forecast, so a copy of one would be a lie."""
        response = self.export()
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_an_unknown_city_is_reported(self):
        self.mock_geocode.return_value = None
        response = self.export()
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", response.get_data(as_text=True))

    def test_a_geocoder_outage_is_not_reported_as_a_missing_city(self):
        self.mock_geocode.side_effect = rainalert.GeocodingUnavailable("boom")
        response = self.export()
        self.assertEqual(response.status_code, 503)
        self.assertIn("geocoding service is unavailable",
                      response.get_data(as_text=True))

    def test_a_weather_outage_is_reported(self):
        self.mock_get.side_effect = rainalert.WeatherUnavailable("boom")
        response = self.export()
        self.assertEqual(response.status_code, 503)
        self.assertIn("weather service is unavailable",
                      response.get_data(as_text=True))

    # -- which days go in ------------------------------------------------------

    def test_a_wet_day_becomes_an_event(self):
        text = self.text()
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("DTSTART;VALUE=DATE:20261021", text)
        self.assertIn("DTSTART;VALUE=DATE:20261022", text)

    def test_a_dry_day_does_not(self):
        """Only the days that reach the threshold are in the file."""
        text = self.text(chances=(100, 86, 40))
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)
        self.assertNotIn("DTSTART;VALUE=DATE:20261023", text)

    def test_the_apps_own_threshold_is_used_without_one(self):
        """Without a threshold of the reader's own, the app's advice rules."""
        text = self.text(chances=(50, 49))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_the_readers_own_threshold_is_used_when_it_is_sent(self):
        text = self.text("?city=London&threshold=40", chances=(50, 39))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_an_unreported_day_is_never_an_event(self):
        """A missing value is not a chance of anything."""
        text = self.text(chances=(80, None))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_an_unreadable_threshold_falls_back_to_the_apps_own(self):
        """A nonsense threshold is not the reader's own, so it is not used.

        The browser only ever sends a number, but the link can be edited
        or typed by hand, and a hand-typed threshold must not be taken as
        the reader's own answer.
        """
        text = self.readable("?city=London&threshold=soon")
        self.assertIn("Bring an umbrella.", text)
        self.assertNotIn("alert threshold", text)
        # The app's own threshold still decides which days go in.
        self.assertIn("DTSTART;VALUE=DATE:20261021", text)
        self.assertNotIn("DTSTART;VALUE=DATE:20261023", text)

    def test_a_threshold_of_zero_takes_every_reported_day(self):
        """Zero is a threshold a reader can set, and it means every day."""
        text = self.readable("?city=London&threshold=0",
                             chances=(100, 86, 40, 0, None))
        self.assertEqual(text.count("BEGIN:VEVENT"), 4)
        # The day the service did not report is still not in the file.
        self.assertNotIn("DTSTART;VALUE=DATE:20261025", text)

    def test_the_events_are_the_days_the_page_shows(self):
        """The calendar and the list can never disagree about the wet days.

        The same forecast produces both, so the dates in the file have to
        be the dates on the page.
        """
        chances = [100, 86, 40, 15]
        self.mock_get.return_value = FakeResponse(payload=self.payload(chances))
        page = self.client.get("/city/london").get_data(as_text=True)
        text = self.readable(chances=chances)

        # The app's own threshold is 50, so the first two days are the wet
        # ones, and the file holds exactly those two.
        starts = re.findall(r"DTSTART;VALUE=DATE:(\d{8})", text)
        self.assertEqual(starts, ["20261021", "20261022"])
        for start in starts:
            day = date(int(start[:4]), int(start[4:6]), int(start[6:]))
            self.assertIn(day.strftime("%d.%m.%Y"), page)

    def test_a_dry_week_produces_a_calendar_with_no_events(self):
        """The file is still a calendar; it simply has nothing in it."""
        text = self.text(chances=(5, 10))
        self.assertNotIn("BEGIN:VEVENT", text)
        self.assertIn("END:VCALENDAR", text)

    # -- what the events say ----------------------------------------------------

    def test_the_event_covers_the_whole_day(self):
        """The end of an all-day event is the start of the next day."""
        text = self.text(chances=(80,))
        self.assertIn("DTEND;VALUE=DATE:20261022", text)

    def test_the_summary_names_the_band_and_the_chance(self):
        """The band is the one the row in the list carries."""
        text = self.readable(chances=(80,))
        self.assertIn("SUMMARY:Rain likely - 80% chance of rain", text)

    def test_the_description_names_the_city_and_the_chance(self):
        text = self.readable(chances=(80,))
        self.assertIn("80% chance of rain in London on Wednesday 21.10.2026",
                      text)

    def test_the_apps_own_advice_brings_the_umbrella(self):
        text = self.readable(chances=(80,))
        self.assertIn("Bring an umbrella", text)

    def test_the_readers_own_threshold_is_named_in_the_description(self):
        text = self.readable("?city=London&threshold=40", chances=(80,))
        self.assertIn("At or above your 40% alert threshold.", text)

    def test_the_umbrella_is_not_mixed_into_the_readers_own_alert(self):
        """The umbrella is the app's advice; the limit is the reader's."""
        text = self.readable("?city=London&threshold=40", chances=(80,))
        self.assertNotIn("Bring an umbrella", text)

    def test_the_weather_data_is_credited(self):
        """Open-Meteo's licence asks for the credit wherever the data goes."""
        text = self.readable(chances=(80,))
        self.assertIn("Open-Meteo.com", text)

    def test_the_event_id_is_the_same_every_time(self):
        """Importing the file again updates the events instead of adding
        a second copy of every one of them."""
        first = self.text(chances=(80,))
        second = self.text(chances=(80,))
        uid = [line for line in first.split("\r\n") if line.startswith("UID:")]
        self.assertTrue(uid)
        self.assertEqual(uid, [line for line in second.split("\r\n")
                                if line.startswith("UID:")])

    def test_the_calendar_is_named_after_the_city(self):
        text = self.text(chances=(80,))
        self.assertIn("X-WR-CALNAME:Rain forecast - London", text)


class TestCalendarLink(AppTestCase):
    """The link on the page that starts the export."""

    def body_with_forecast(self, chances=(100, 86, 40)):
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + offset:02d}"
                         for offset in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_the_link_is_on_the_forecast_page(self):
        body = self.body_with_forecast()
        self.assertIn('id="calendar-export"', body)
        self.assertIn("Add rainy days to my calendar", body)

    def test_the_link_carries_the_city(self):
        body = self.body_with_forecast()
        self.assertIn("/calendar.ics?city=London", body)

    def test_the_link_sits_on_the_heading_row(self):
        """It is on the line the heading already takes: the card has no
        vertical room for another one."""
        body = self.body_with_forecast()
        head = body[body.index("result-head"):body.index("severity-legend")]
        self.assertIn('id="calendar-export"', head)

    def test_the_link_is_on_the_same_line_as_the_caption(self):
        """The link and "7-day rain chance" are one line, not two rows."""
        body = self.body_with_forecast()
        subline = body[body.index("result-subline"):]
        subline = subline[:subline.index("</div>")]
        self.assertIn("7-day rain chance", subline)
        self.assertIn('id="calendar-export"', subline)

    def test_the_link_is_hidden_when_nothing_would_be_exported(self):
        """A link that would download an empty calendar is not an offer."""
        body = self.body_with_forecast(chances=(5, 10))
        link = body[body.index('id="calendar-export"'):]
        link = link[:link.index(">")]
        self.assertIn("hidden", link)

    def test_the_link_is_not_hidden_when_a_day_would_be_exported(self):
        body = self.body_with_forecast(chances=(80, 10))
        link = body[body.index('id="calendar-export"'):]
        link = link[:link.index(">")]
        self.assertNotIn("hidden", link)

    def test_the_link_is_not_on_the_start_page(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('id="calendar-export"', body)

    def test_the_link_is_not_on_an_error_page(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertNotIn('id="calendar-export"', body)


class TestAttribution(AppTestCase):
    """Open-Meteo's licence (CC BY 4.0) requires a credit; OSM data needs one too."""

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
            # A link to somewhere else on the site is not a risk: it opens
            # in the same tab, and there is no window for it to reach. A
            # link out of the site is, so that is the one that has to be
            # opened safely.
            if 'target="_blank"' in opening or 'href="http' in opening:
                self.assertIn('rel="noopener noreferrer"', opening)


class TestInstallableApp(AppTestCase):
    """Tier 2 again: the app can be installed, and it opens offline.

    The manifest says what the installed app is called and which icons it
    has; the service worker caches the shell so the app opens without a
    network. The forecast itself is never cached - a stale rain chance is
    worse than none.
    """

    def get(self, path):
        """A GET whose response is closed again.

        The manifest and the worker are sent as files, and a test client
        that throws the response away leaves the file handle open.
        """
        response = self.client.get(path)
        self.addCleanup(response.close)
        return response

    def manifest(self):
        response = self.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        return json.loads(response.get_data(as_text=True))

    def shell_files(self):
        """The files the service worker puts in its cache."""
        script = self.get("/service-worker.js").get_data(as_text=True)
        start = script.index("const SHELL")
        block = script[start:script.index("];", start)]
        return re.findall(r"'([^']+)'", block)

    # -- the manifest ---------------------------------------------------------

    def test_the_manifest_is_served_at_the_root(self):
        response = self.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("manifest", response.headers["Content-Type"])

    def test_the_manifest_names_the_app(self):
        data = self.manifest()
        self.assertIn("Rain Alert", data["name"])
        self.assertEqual(data["short_name"], "Rain Alert")
        self.assertEqual(data["lang"], "en")
        self.assertTrue(data["description"])

    def test_the_manifest_opens_the_whole_site(self):
        """A manifest served from a subdirectory would default to that
        subdirectory as its scope, and the app would not be installed."""
        data = self.manifest()
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["id"], "/")

    def test_the_manifest_stands_on_its_own(self):
        """Standalone is what makes it an app rather than a web page."""
        data = self.manifest()
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(data["theme_color"])
        self.assertTrue(data["background_color"])

    def test_the_manifest_has_the_icons_a_browser_needs(self):
        """Chrome wants a 192px icon, a 512px one and a maskable one."""
        icons = self.manifest()["icons"]
        sizes = {(icon["sizes"], icon["purpose"]) for icon in icons}
        self.assertIn(("192x192", "any"), sizes)
        self.assertIn(("512x512", "any"), sizes)
        self.assertIn(("512x512", "maskable"), sizes)

    def test_every_icon_is_a_real_png(self):
        """An icon that is not there is an install prompt that fails."""
        for icon in self.manifest()["icons"]:
            response = self.get(icon["src"])
            self.assertEqual(response.status_code, 200, icon["src"])
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(
                response.get_data().startswith(b"\x89PNG\r\n\x1a\n"),
                icon["src"])

    def test_the_apple_icon_is_served(self):
        """iOS ignores the manifest and wants its own icon."""
        response = self.get("/static/icon-180.png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.get_data().startswith(b"\x89PNG\r\n\x1a\n"))

    # -- the service worker ---------------------------------------------------

    def test_the_worker_is_served_from_the_root(self):
        """A worker served from /static/ would only control /static/."""
        response = self.get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["Content-Type"])
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")

    def test_the_worker_is_not_cached(self):
        """A worker that is cached is a worker that never updates."""
        response = self.get("/service-worker.js")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_every_file_the_worker_caches_exists(self):
        """A typo in the list is a file that never reaches the cache, and an
        app that opens offline with a hole in it."""
        files = self.shell_files()
        self.assertTrue(files)
        for path in files:
            self.assertEqual(self.get(path).status_code, 200, path)

    def test_the_shell_has_the_files_the_page_needs(self):
        shell = self.shell_files()
        for path in ("/static/style.css", "/static/app.js",
                     "/static/favicon.svg", "/static/offline.html"):
            self.assertIn(path, shell)

    def test_the_forecast_page_is_never_cached(self):
        """The page holds the forecast, and a cached forecast is a lie."""
        self.assertNotIn("/", self.shell_files())

    def test_the_export_is_not_in_the_shell(self):
        """The file holds a forecast, so it is never cached with the shell."""
        self.assertNotIn("/calendar.ics", self.shell_files())

    def test_the_export_is_never_intercepted(self):
        """An offline page is not a calendar, and must not stand in for one.

        The worker answers a navigation with the offline page when there
        is no network, so the export has to be let through before that
        branch is reached.
        """
        script = self.get("/service-worker.js").get_data(as_text=True)
        self.assertIn("/calendar.ics", script)
        self.assertLess(script.index("/calendar.ics"),
                        script.index("request.mode === 'navigate'"))

    # -- the offline page -----------------------------------------------------

    def test_the_offline_page_is_served(self):
        response = self.get("/static/offline.html")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("You are offline", body)

    def test_the_offline_page_shows_no_forecast(self):
        """There is nothing to show, and a stale chance is worse than none."""
        body = self.get("/static/offline.html").get_data(as_text=True)
        self.assertNotIn("weather-list", body)
        self.assertNotIn("hourly-strip", body)

    def test_the_offline_page_offers_a_way_back(self):
        body = self.get("/static/offline.html").get_data(as_text=True)
        self.assertIn('class="offline-retry" href="/"', body)

    # -- the page itself ------------------------------------------------------

    def test_the_page_points_at_the_manifest(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)
        self.assertIn('name="theme-color"', body)
        self.assertIn('rel="apple-touch-icon"', body)

    def test_the_manifest_is_on_the_forecast_page_too(self):
        """The installed app opens on the start page, but the manifest has
        to be there on every page."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)

    def test_the_manifest_is_on_an_error_page_too(self):
        body = self.client.post("/", data={"city": ""}).get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)


class TestSearchEngineOptimisation(AppTestCase):
    """The parts of the site a search engine reads.

    A search engine finds a page by its address, reads the title and the
    description off it, and follows the canonical link when the same page
    answers to more than one address. Every one of those is decided in one
    place in ``app.py``, so they cannot drift apart, and the tests here
    are what holds them to it.
    """

    def body(self, path):
        return self.client.get(path).get_data(as_text=True)

    # -- the address of a page -------------------------------------------------

    def test_a_city_has_an_address_of_its_own(self):
        """The query string is the way in, not the address."""
        response = self.client.get("/?city=London")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/london")

    def test_the_redirect_keeps_the_unit(self):
        response = self.client.get("/?city=London&unit=fahrenheit")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"],
                         "/city/london?unit=fahrenheit")

    def test_an_address_that_is_not_the_canonical_one_is_redirected(self):
        """"/city/London" and "/city/london" are one page, not two."""
        response = self.client.get("/city/London")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/london")

    def test_the_page_claims_its_own_address(self):
        body = self.body("/city/london")
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/city/london">',
            body)

    def test_the_start_page_claims_the_start_page(self):
        body = self.body("/")
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/">', body)

    # -- a page that is not there says so --------------------------------------

    def test_an_unknown_city_is_a_404(self):
        """A page that says "not found" but answers 200 is a soft 404, and
        search engines treat it as one."""
        self.mock_geocode.return_value = None
        response = self.client.get("/city/nowhereville")
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", response.get_data(as_text=True))

    def test_an_upstream_that_is_down_is_a_503(self):
        """The page is fine, the moment is not."""
        self.mock_get.side_effect = requests.ConnectionError("down")
        response = self.client.get("/city/london")
        self.assertEqual(response.status_code, 503)

    def test_an_unknown_address_is_a_404_page(self):
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn("There is no page at this address.", body)
        self.assertIn('<meta name="robots" content="noindex, follow">', body)

    def test_a_page_with_an_error_is_not_to_be_indexed(self):
        self.mock_geocode.return_value = None
        body = self.body("/city/nowhereville")
        self.assertIn('<meta name="robots" content="noindex, follow">', body)

    # -- the files a crawler asks for ------------------------------------------

    def test_the_robots_file_points_at_the_sitemap(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Sitemap: https://rainalert.live/sitemap.xml", body)
        # The alert poll and the calendar export are not pages.
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Disallow: /calendar.ics", body)

    def test_the_sitemap_names_the_pages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("<loc>https://rainalert.live/</loc>", body)
        self.assertIn("<loc>https://rainalert.live/cities</loc>", body)
        self.assertIn("<loc>https://rainalert.live/city/london</loc>", body)

    def test_the_sitemap_names_every_curated_city(self):
        body = self.body("/sitemap.xml")
        for slug, _name in rainalert.CURATED_CITIES:
            self.assertIn(f"<loc>https://rainalert.live/city/{slug}</loc>",
                          body)

    def test_the_endpoints_that_are_not_pages_are_kept_out_of_the_results(self):
        for path in ("/api/alert?city=London", "/calendar.ics?city=London"):
            response = self.client.get(path)
            self.assertIn("noindex", response.headers.get("X-Robots-Tag", ""),
                          path)

    # -- what a search result shows -------------------------------------------

    def test_every_page_says_what_it_is(self):
        """A title, a description and a social card on every page."""
        for path in ("/", "/cities", "/city/london"):
            body = self.body(path)
            self.assertIn('<meta name="description" content="', body, path)
            self.assertIn('<link rel="canonical" href="https://rainalert.live',
                          body, path)
            self.assertIn('<meta property="og:title" content="', body, path)
            self.assertIn('<meta property="og:image" content="https://'
                          'rainalert.live/static/og-image.png">', body, path)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">',
                          body, path)

    def test_the_title_names_the_city(self):
        body = self.body("/city/london")
        title = re.search(r"<title>(.*?)</title>", body).group(1)
        self.assertIn("London", title)
        self.assertTrue(title.endswith("- Rain Alert"), title)

    def test_the_description_says_the_same_thing_as_the_page(self):
        body = self.body("/city/london")
        description = re.search(
            r'<meta name="description" content="([^"]*)"', body).group(1)
        self.assertIn("chance of rain in London", description)

    def test_the_page_describes_itself_in_machine_readable_form(self):
        """The structured data has to be JSON, and it has to be about this
        site."""
        body = self.body("/city/london")
        raw = re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            body, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["@context"], "https://schema.org")
        types = [node["@type"] for node in data["@graph"]]
        self.assertIn("WebSite", types)
        self.assertIn("WebApplication", types)
        # On a city's page the week itself is described, day by day.
        self.assertIn("ItemList", types)

    # -- the shape of the page -------------------------------------------------

    def test_the_headings_are_in_order(self):
        """A page that skips a level is harder to read, and a screen reader
        uses the levels to build a table of contents."""
        body = self.body("/city/london")
        levels = [int(level) for level in
                  re.findall(r"<h([1-6])[ >]", body)]
        self.assertTrue(levels)
        self.assertEqual(levels[0], 1)
        for before, after in zip(levels, levels[1:]):
            self.assertLessEqual(after, before + 1,
                                 f"h{before} is followed by h{after}")

    def test_the_days_are_a_list(self):
        """The week, in order, marked up as a list."""
        body = self.body("/city/london")
        self.assertIn('<ol class="weather-list">', body)
        self.assertEqual(body.count('<li class="weather-item'),
                         len(FORECAST_PAYLOAD["daily"]["time"]))


class TestApiDocumentation(unittest.TestCase):
    """The API reference has to describe the app that is actually there.

    ``API.md`` and ``openapi.yaml`` are written by hand, so they drift the
    moment a route, a parameter or a threshold changes. These tests are what
    stops them from drifting silently: a new route that nobody documented
    fails the suite, and so does a documented route that no longer exists.
    """

    # The routes the documentation talks about. The static route is left out
    # on purpose: it is Flask's own handler, and it is described in the
    # reference as a path rather than as a route of its own.
    DOCUMENTED_ROUTES = ("/", "/api/alert", "/calendar.ics",
                         "/manifest.json", "/service-worker.js")

    def read(self, name):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def app_routes(self):
        """The routes the app actually serves.

        They are written the way the documents write them, so that a
        Flask rule and a spec path can be compared: ``/city/<path:slug>``
        is ``/city/{slug}`` in both.
        """
        routes = set()
        for rule in rainalert.app.url_map.iter_rules():
            if rule.rule.startswith("/static/"):
                continue
            routes.add(re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule))
        return routes

    def spec_paths(self):
        """The paths the OpenAPI spec documents.

        The spec is read as text rather than parsed, because the runtime
        has five dependencies and a YAML parser is not one of them. The
        path keys are the only lines in the ``paths`` block that sit two
        spaces in and end in a colon.
        """
        text = self.read("openapi.yaml")
        start = text.index("\npaths:\n")
        end = text.index("\ncomponents:\n", start)
        block = text[start:end]
        return set(re.findall(r"^  (/\S*):$", block, re.MULTILINE))

    def test_every_route_is_in_the_reference(self):
        """A route nobody documented is a route nobody can use."""
        reference = self.read("API.md")
        for route in self.app_routes():
            self.assertIn(route, reference, route)

    def test_every_route_is_in_the_spec(self):
        """The spec is what a tool reads, so it has to cover the routes."""
        paths = self.spec_paths()
        for route in self.app_routes():
            self.assertIn(route, paths, route)

    def test_the_spec_documents_no_route_that_is_gone(self):
        """A route in the spec that the app does not serve is a lie."""
        routes = self.app_routes()
        for path in self.spec_paths():
            self.assertIn(path, routes, path)

    def test_the_spec_says_it_is_openapi(self):
        """A spec that is not OpenAPI cannot be loaded by a tool."""
        self.assertIn("openapi: 3.1.0", self.read("openapi.yaml"))

    def test_the_documented_defaults_are_the_real_ones(self):
        """The reference quotes the defaults, so they have to be the ones
        the app actually uses."""
        reference = self.read("API.md")
        self.assertIn(f"`UMBRELLA_THRESHOLD` | `{rainalert.UMBRELLA_THRESHOLD}`",
                      reference)
        self.assertIn(f"`NOTIFICATION_POLL_MINUTES` | "
                      f"`{rainalert.NOTIFICATION_POLL_MINUTES}`", reference)
        self.assertIn(f"`NOTIFICATION_LEAD_HOURS` | "
                      f"`{rainalert.NOTIFICATION_LEAD_HOURS}`", reference)
        self.assertIn(f"`SEVERITY_LOW_MAX` | `{rainalert.SEVERITY_LOW_MAX}`",
                      reference)
        self.assertIn(f"`SEVERITY_MODERATE_MAX` | "
                      f"`{rainalert.SEVERITY_MODERATE_MAX}`", reference)

    def test_the_documented_thresholds_are_the_real_ones(self):
        """The reference states the bands in words, and so does the app.

        The reference is read with its line breaks flattened, because the
        numbers are wrapped onto the next line in the Markdown and a test
        that depended on where the wrap fell would be a nuisance.
        """
        reference = " ".join(self.read("API.md").split())
        self.assertIn(f"default **{rainalert.UMBRELLA_THRESHOLD}**", reference)
        self.assertIn(f"default **{rainalert.NOTIFICATION_POLL_MINUTES}**",
                      reference)
        self.assertIn(f"default **{rainalert.NOTIFICATION_LEAD_HOURS}**",
                      reference)


class TestNightStreetDesign(AppTestCase):
    """The night street layout: what the markup has to carry.

    The design moved the answer to the top, the week to seven columns of
    figures, and the type to a self-hosted face. These are the things the
    page has to keep doing, whatever the styling looks like.
    """

    def forecast_page(self):
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_the_top_bar_carries_the_mark_and_the_name(self):
        body = self.forecast_page()
        self.assertIn('class="brand"', body)
        self.assertIn('class="brand-mark"', body)
        self.assertIn('class="brand-name"', body)
        self.assertLess(body.index('class="topbar"'),
                        body.index('class="result"'))

    def test_there_is_exactly_one_search_form(self):
        """The search sits in the top bar on a forecast page and under
        the name on the start page, but never both."""
        for body in (self.forecast_page(),
                     self.client.get("/").get_data(as_text=True)):
            self.assertEqual(body.count("<form"), 1, body.count("<form"))

    def test_the_search_is_in_the_top_bar_on_a_forecast_page(self):
        body = self.forecast_page()
        self.assertIn('class="search search-compact"', body)
        topbar = body[body.index('class="topbar"'):body.index('class="result"')]
        self.assertIn('class="search search-compact"', topbar)

    def test_the_start_page_search_is_under_the_name(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="search search-wide"', body)
        self.assertLess(body.index('class="intro"'),
                        body.index('class="search search-wide"'))

    def test_the_heading_is_the_city_name(self):
        """The answer is at the top of the page, so the city is the
        heading."""
        body = self.forecast_page()
        self.assertIn('<h1 class="city-name">London</h1>', body)

    def test_the_caption_says_what_the_page_is(self):
        body = self.forecast_page()
        self.assertIn("7-day rain chance", body)

    def test_the_week_is_a_list_of_days(self):
        """Seven columns of figures, but still a list in the markup."""
        body = self.forecast_page()
        self.assertIn('<ol class="weather-list">', body)
        self.assertEqual(body.count('<li class="weather-item'), 3)

    def test_the_value_row_carries_the_bare_numbers(self):
        """Twenty-four numbers have to fit across the panel, so the
        percent sign is left off them."""
        body = self.forecast_page()
        self.assertEqual(body.count('<span class="hour-value">'), 24)
        values = re.findall(r'<span class="hour-value">([^<]*)', body)
        self.assertEqual(len(values), 24)
        for value in values:
            self.assertTrue(value.isdigit() or value == "?", value)

    def test_the_value_row_has_no_percent_sign(self):
        body = self.forecast_page()
        row = body[body.index('class="hourly-values"'):]
        row = row[:row.index("</div>")]
        self.assertNotIn("%", row)

    def test_the_now_label_sits_in_the_value_row(self):
        """It labels the rule, so it belongs with the column it is over."""
        body = self.forecast_page()
        self.assertIn('<span class="now-label">now 09:00</span>', body)
        row = body[body.index('class="hourly-values"'):]
        row = row[:row.index("</div>")]
        self.assertIn('class="now-label"', row)

    def test_the_calendar_icon_is_drawn_not_borrowed(self):
        """A blue calendar in a night panel reads as a rain colour."""
        body = self.forecast_page()
        self.assertIn('class="calendar-icon"', body)
        self.assertNotIn("\U0001F4C5", body)

    def test_the_bell_is_drawn_not_borrowed(self):
        body = self.forecast_page()
        self.assertIn('class="notify-icon"', body)
        self.assertNotIn("\U0001F514", body)

    def test_the_umbrella_is_the_text_glyph(self):
        """The pictograph, not the colour emoji."""
        body = self.forecast_page()
        self.assertIn("☔&#xFE0E;", body)
        self.assertIn('class="umbrella"', body)

    def test_the_page_is_a_night(self):
        body = self.forecast_page()
        self.assertIn('<meta name="theme-color" content="#0d1216">', body)

    def test_the_type_is_self_hosted(self):
        """No third party is asked for a font."""
        body = self.forecast_page()
        self.assertIn("fonts/archivo-latin.woff2", body)
        self.assertNotIn("fonts.googleapis.com", body)
        self.assertNotIn("fonts.gstatic.com", body)

    def test_the_legend_still_names_the_bands(self):
        """The band name is in the legend, so the colour never carries
        the meaning on its own."""
        body = self.forecast_page()
        legend = body[body.index('class="severity-legend"'):]
        legend = legend[:legend.index("</div>")]
        for name in ("Rain unlikely", "Rain possible", "Rain likely"):
            self.assertIn(name, legend)

    def test_the_legend_still_heads_the_chance_column(self):
        body = self.forecast_page()
        legend = body[body.index('class="severity-legend"'):]
        legend = legend[:legend.index("</div>")]
        self.assertIn('<span class="column-head">Rain chance</span>', legend)

    def test_the_hourly_title_is_a_second_level_heading(self):
        """h1 is the city, so the strip's title is an h2."""
        body = self.forecast_page()
        self.assertIn('<h2 class="hourly-title">', body)
        self.assertLess(body.index('<h1 class="city-name"'),
                        body.index('<h2 class="hourly-title"'))


class TestDayPanel(AppTestCase):
    """The panel above the week: the detail of the day that is picked.

    The week is seven columns and a column can be picked, so the panel
    above it has to say what that day is about: the day, the band it is
    in, the chance, and how much rain falls in it and for how long. The
    chance in the panel is the chance in the column, so the two can never
    disagree.
    """

    def page_for(self, chances, amounts=None, hours=None):
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + i:02d}" for i in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            },
            "hourly": {
                "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
                "precipitation_probability": [0] * 24,
            },
            "current": {"time": "2026-10-21T09:00"},
            "utc_offset_seconds": 3600,
        }
        if amounts is not None:
            payload["daily"]["precipitation_sum"] = amounts
        if hours is not None:
            payload["daily"]["precipitation_hours"] = hours
        self.mock_get.return_value = FakeResponse(payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def panels(self, body):
        """The markup of every day panel, in the order they appear."""
        return re.findall(r'<div class="day-panel.*?</div>', body, re.S)

    def test_the_panel_sits_above_the_week(self):
        body = self.page_for([100, 86, 40])
        self.assertLess(body.index('class="day-detail"'),
                        body.index('<ol class="weather-list">'))

    def test_every_day_has_a_panel(self):
        body = self.page_for([100, 86, 40])
        self.assertEqual(len(self.panels(body)), 3)

    def test_todays_panel_is_the_one_that_shows(self):
        """The week starts on today, so today is the day that is picked
        until the reader picks another one."""
        body = self.page_for([100, 86, 40])
        panels = self.panels(body)
        self.assertIn("is-active", panels[0])
        self.assertNotIn("is-active", panels[1])
        self.assertNotIn("is-active", panels[2])

    def test_the_panel_names_the_day(self):
        body = self.page_for([100, 86, 40])
        panels = self.panels(body)
        self.assertIn("Today 21.10", panels[0])
        self.assertIn("Tomorrow 22.10", panels[1])
        self.assertIn("Friday 23.10", panels[2])

    def test_the_panel_carries_the_chance(self):
        body = self.page_for([100, 86, 40])
        panels = self.panels(body)
        self.assertIn("100% chance of rain", panels[0])
        self.assertIn("86% chance of rain", panels[1])

    def test_the_panel_names_the_band(self):
        """The band is named in words, so the colour never carries the
        meaning on its own."""
        body = self.page_for([100, 45, 10])
        panels = self.panels(body)
        self.assertIn("Rain likely", panels[0])
        self.assertIn("Rain possible", panels[1])
        self.assertIn("Rain unlikely", panels[2])

    def test_the_panel_carries_the_rain_figures(self):
        body = self.page_for([100, 86, 40], amounts=[7.3, 0.0, 0.0],
                              hours=[6.0, 0.0, 0.0])
        panel = self.panels(body)[0]
        self.assertIn("7.3 mm", panel)
        self.assertIn("6 h of rain", panel)

    def test_a_day_with_no_rain_carries_no_figures(self):
        """Nothing to say about a day the model expects no rain in."""
        body = self.page_for([100, 86, 40], amounts=[7.3, 0.0, 0.0],
                              hours=[6.0, 0.0, 0.0])
        panel = self.panels(body)[1]
        self.assertNotIn("mm", panel)
        self.assertNotIn("h of rain", panel)

    def test_a_day_the_service_did_not_report_says_so(self):
        """An unreported day is named as such, and carries no figures: it
        is never counted as a dry one."""
        body = self.page_for([None, 86, 40])
        panel = self.panels(body)[0]
        self.assertIn("Rain not reported", panel)
        self.assertNotIn("chance of rain", panel)
        self.assertNotIn("mm", panel)
        self.assertNotIn("h of rain", panel)

    def test_the_advice_is_the_apps_own(self):
        """The umbrella in the panel is the app's advice, at the same
        threshold as the umbrella in the column."""
        body = self.page_for([10, 50, 80])
        panels = self.panels(body)
        self.assertNotIn("Take an umbrella", panels[0])
        self.assertIn("Take an umbrella", panels[1])
        self.assertIn("Take an umbrella", panels[2])

    def test_the_start_page_has_no_panel(self):
        """There is no day to pick without a forecast."""
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('class="day-detail"', body)


class TestDayStrip(AppTestCase):
    """The graph follows the day that is picked.

    The strip is the hour-by-hour graph, and the reader picks a day out of
    the week, so the strip has to show that day and not always today. The
    server renders a strip for every day and the script decides which one
    shows, so the page still says something useful without a script.
    """

    def page_for(self, chances, hourly=None):
        """A forecast with an hour for every day of the week.

        ``hourly`` is the chance for each hour of each day, day by day. It
        defaults to a dry week, so a test can say what it wants.
        """
        days = [f"2026-10-{21 + i:02d}" for i in range(len(chances))]
        if hourly is None:
            hourly = [[0] * 24 for _ in days]
        payload = {
            "daily": {
                "time": days,
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(days),
                "temperature_2m_min": [8.0] * len(days),
            },
            "hourly": {
                "time": [f"{day}T{hour:02d}:00"
                         for day in days for hour in range(24)],
                "precipitation_probability": [value
                                              for day in hourly for value in day],
            },
            "current": {"time": "2026-10-21T09:00"},
            "utc_offset_seconds": 3600,
        }
        self.mock_get.return_value = FakeResponse(payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def strips(self, body):
        """The markup of every day's strip, in the order they appear."""
        parts = body.split('<div class="day-strip')[1:]
        strips = []
        for part in parts:
            # The last strip runs on into the rest of the page, so it is
            # cut off at the panels that follow it.
            end = part.find('<div class="day-panel')
            strips.append('<div class="day-strip'
                          + (part[:end] if end > 0 else part))
        return strips

    def test_every_day_has_a_strip(self):
        body = self.page_for([100, 86, 40, 15, 5, 60, 30])
        self.assertEqual(len(self.strips(body)), 7)

    def test_todays_strip_is_the_one_that_shows(self):
        """The week starts on today, so today's strip shows until the
        reader picks another day."""
        body = self.page_for([100, 86, 40, 15, 5, 60, 30])
        strips = self.strips(body)
        self.assertIn("is-active", strips[0])
        for strip in strips[1:]:
            self.assertNotIn("is-active", strip)

    def test_a_strip_carries_the_hours_of_its_own_day(self):
        """Each day is drawn with its own hours, not with today's."""
        hourly = [[(index + 1) * 10] * 24 for index in range(7)]
        body = self.page_for([100, 86, 40, 15, 5, 60, 30], hourly)
        strips = self.strips(body)
        self.assertIn("08:00, 30% chance of rain", strips[2])
        self.assertNotIn("08:00, 70% chance of rain", strips[2])
        self.assertIn("08:00, 70% chance of rain", strips[6])

    def test_the_strip_names_the_day_it_draws(self):
        """The title of the strip follows the day, so the graph is never
        about a day the reader did not pick."""
        body = self.page_for([100, 86, 40, 15, 5, 60, 30])
        titles = re.findall(r'data-title="([^"]*)"', body)
        self.assertEqual(titles[:3], ["Today, hour by hour",
                                      "Tomorrow, hour by hour",
                                      "Friday, hour by hour"])

    def test_the_page_names_todays_strip(self):
        """Without a script the strip that shows is today's, and the title
        says so."""
        body = self.page_for([100, 86, 40, 15, 5, 60, 30])
        self.assertIn('<h2 class="hourly-title">Today, hour by hour</h2>', body)

    def test_the_summary_names_the_day(self):
        """A dry day says which dry day it is."""
        body = self.page_for([100, 86, 40, 15, 5, 60, 30])
        summaries = re.findall(r'<p class="hourly-summary">(.*?)</p>', body)
        self.assertIn("No rain likely for the rest of today.", summaries[0])
        self.assertIn("No rain likely tomorrow.", summaries[1])
        self.assertIn("No rain likely on Friday.", summaries[2])

    def test_a_day_with_no_hours_says_so(self):
        """A day the service gave no hours for has no graph, and the page
        says that rather than drawing an empty one."""
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [100, 86],
                "temperature_2m_max": [14.0, 14.0],
                "temperature_2m_min": [8.0, 8.0],
            },
            "hourly": {
                "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
                "precipitation_probability": [0] * 24,
            },
            "current": {"time": "2026-10-21T09:00"},
            "utc_offset_seconds": 3600,
        }
        self.mock_get.return_value = FakeResponse(payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        strips = self.strips(body)
        self.assertIn("Hourly detail is not available for this day.", strips[1])
        self.assertNotIn("hourly-strip", strips[1])

    def test_the_alert_is_still_about_today(self):
        """Picking a day is browsing. The banner and the tab title are the
        app's own alert, and they name the first day worth mentioning, not
        the day the reader happens to be looking at."""
        hourly = [[0] * 24, [80] * 24]
        body = self.page_for([10, 80], hourly)
        self.assertIn("Rain likely tomorrow (80%)", body)
        self.assertIn("<title>Rain tomorrow in London - Rain Alert</title>",
                      body)
        # Today's own strip still says what today is about.
        self.assertIn("No rain likely for the rest of today.",
                      self.strips(body)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)