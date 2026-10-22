"""Parsing the forecast service's answer into days and hours.
"""

import unittest
from unittest import mock

import requests

from app import app
from rainalert.domain import parse, rain
from rainalert.present import forecast_view, labels
from rainalert.upstream import geocoding
from tests.fixtures import FakeLocation, FakeResponse, hourly_payload


class TestHourlyParsing(unittest.TestCase):
    """The hourly parsing itself, without the HTTP layer."""

    def test_a_day_of_hours_is_parsed(self):
        payload = hourly_payload([0, 10, 20] * 8)
        hours = forecast_view.parse_today_hours(payload)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[0]["hour_label"], "00")
        self.assertEqual(hours[23]["hour_label"], "23")

    def test_hours_before_now_are_marked_past(self):
        payload = hourly_payload([0] * 24, now="2026-10-21T09:00")
        hours = forecast_view.parse_today_hours(payload)
        self.assertTrue(hours[8]["past"])
        self.assertFalse(hours[9]["past"])

    def test_the_current_hour_is_marked_now(self):
        payload = hourly_payload([0] * 24, now="2026-10-21T09:00")
        hours = forecast_view.parse_today_hours(payload)
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
        hours = forecast_view.parse_today_hours(payload)
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
        hours = forecast_view.parse_today_hours(payload)
        self.assertEqual(len(hours), 24)
        self.assertTrue(all(hour["day"] == "2026-10-22" for hour in hours))
        self.assertTrue(any(hour["now"] for hour in hours))

    def test_a_day_with_23_hours_is_kept_whole(self):
        """A clock-change day is not truncated to 24 entries."""
        payload = hourly_payload([5] * 23, day="2026-10-21")
        hours = forecast_view.parse_today_hours(payload)
        self.assertEqual(len(hours), 23)

    def test_a_page_parses_the_hours_once(self):
        """The hours are grouped once per request, and today is picked
        out of the groups rather than parsed a second time."""
        geocoding.get_coordinates.cache_clear()
        with mock.patch.object(geocoding.geolocator, "geocode",
                               return_value=FakeLocation()), \
                mock.patch.object(requests, "get",
                                  return_value=FakeResponse()), \
                mock.patch.object(parse, "_parse_hourly_days",
                                  wraps=parse._parse_hourly_days) as grouped:
            response = app.test_client().get("/city/london")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(grouped.call_count, 1)

    def test_an_empty_hourly_block_gives_no_hours(self):
        self.assertEqual(forecast_view.parse_today_hours({}), [])
        self.assertEqual(forecast_view.parse_today_hours({"hourly": {}}), [])

    def test_the_height_is_bucketed_into_steps(self):
        self.assertEqual(labels.hour_height_step(0), 0)
        self.assertEqual(labels.hour_height_step(2), 0)
        self.assertEqual(labels.hour_height_step(3), 5)
        self.assertEqual(labels.hour_height_step(100), 100)
        self.assertEqual(labels.hour_height_step(130), 100)
        self.assertEqual(labels.hour_height_step(None), 0)

    def test_the_local_now_falls_back_to_the_utc_offset(self):
        """Without a current block the offset still says what time it is."""
        payload = hourly_payload([0] * 24)
        del payload["current"]
        self.assertIsNotNone(parse.local_now(payload))

    def test_the_local_now_is_none_without_any_time_information(self):
        self.assertIsNone(parse.local_now({}))

    def test_an_unparseable_timestamp_is_rejected(self):
        self.assertIsNone(parse.parse_hour_timestamp("not-a-time"))
        self.assertIsNone(parse.parse_hour_timestamp(None))
        self.assertIsNotNone(parse.parse_hour_timestamp("2026-10-21T15:00"))


class TestForecastParsing(unittest.TestCase):
    def test_format_date(self):
        self.assertEqual(
            labels.format_date("2026-10-21"), "Wednesday 21.10.2026")
        self.assertEqual(
            labels.format_date("2026-10-22"), "Thursday 22.10.2026")
        self.assertEqual(
            labels.format_date("2026-11-01"), "Sunday 01.11.2026")

    def test_format_date_pads_day_and_month(self):
        self.assertEqual(
            labels.format_date("2026-01-05"), "Monday 05.01.2026")

    def test_format_date_leaves_unparseable_values_alone(self):
        self.assertEqual(labels.format_date("not-a-date"), "not-a-date")
        self.assertEqual(labels.format_date(None), "None")

    def test_format_rain_chance(self):
        """The row shows the number alone; the wording is in the header."""
        self.assertEqual(labels.format_rain_chance(100), "100%")
        self.assertEqual(labels.format_rain_chance(86.4), "86%")
        self.assertEqual(labels.format_rain_chance(0), "0%")
        self.assertEqual(labels.format_rain_chance(None), "unknown")

    def test_describe_rain_chance(self):
        """The full phrase is what a screen reader and a tooltip need."""
        self.assertEqual(
            labels.describe_rain_chance(100), "100% chance of rain")
        self.assertEqual(
            labels.describe_rain_chance(86.4), "86% chance of rain")
        self.assertEqual(
            labels.describe_rain_chance(0), "0% chance of rain")
        self.assertEqual(
            labels.describe_rain_chance(None), "chance of rain unknown"
        )

    def test_format_temperature(self):
        self.assertEqual(labels.format_temperature(11.1, 8.4), "11° / 8°")
        self.assertEqual(labels.format_temperature(14.0, None), "14°")
        self.assertEqual(labels.format_temperature(None, None), "")

    def test_half_rounds_up(self):
        """Temperatures ending in .5 must round up, not to even."""
        self.assertEqual(labels.format_temperature(8.5, 9.5), "9° / 10°")
        self.assertEqual(rain.round_half_up(8.5), 9)
        self.assertEqual(rain.round_half_up(9.5), 10)
        # Negative halves round away from zero, so -0.5C reads as -1C.
        self.assertEqual(rain.round_half_up(-0.5), -1)
