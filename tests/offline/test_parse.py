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


class TestNothingInTheAnswerCanBreakTheParser(unittest.TestCase):
    """A strange answer gives a page with fewer numbers on it.

    The service is a third party, so the answer is not what the app asked
    for. The parser reads what it can and says nothing about the rest: it
    never raises, because a broken answer is the service's problem and
    not the reader's.
    """

    def test_an_answer_that_is_not_an_object_gives_no_days(self):
        for payload in ([1, 2, 3], "junk", 42, None):
            with self.subTest(payload=payload):
                forecast = parse.parse_forecast(payload)
                self.assertEqual(forecast.days, ())

    def test_a_daily_block_that_is_not_an_object_gives_no_days(self):
        forecast = parse.parse_forecast({"daily": "junk"})
        self.assertEqual(forecast.days, ())

    def test_a_daily_field_that_is_not_an_array_is_read_as_no_values(self):
        """A field the service sent in the wrong shape is an empty one.

        The week is as long as the chance list, so an unreadable one leaves
        no days at all - the same as a short list, and the page says there
        is no forecast data rather than showing a wrong week.
        """
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": {"not": "a list"},
            }
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(forecast.days, ())

    def test_a_day_whose_chance_is_missing_is_still_a_day(self):
        """A missing value inside a list is an unknown day, not a lost one.

        The week is as long as the chance list, so a day with a ``None``
        in it stands and is banded as unknown - never as dry.
        """
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [None, 20],
            }
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.days), 2)
        self.assertIsNone(forecast.days[0].chance)
        self.assertEqual(forecast.days[1].chance, 20)

    def test_a_current_block_that_cannot_be_read_is_no_current_block(self):
        """The strip still draws, it just carries no now-marker."""
        payload = hourly_payload([0] * 24)
        payload["current"] = "junk"
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.today), 24)
        self.assertFalse(any(hour.now for hour in forecast.today))

    def test_a_local_now_that_is_not_an_object_is_nothing(self):
        for payload in ([1, 2, 3], "junk", None):
            with self.subTest(payload=payload):
                self.assertIsNone(parse.local_now(payload))

    def test_a_current_block_without_a_time_falls_back_to_the_offset(self):
        payload = hourly_payload([0] * 24)
        payload["current"] = {}
        self.assertIsNotNone(parse.local_now(payload))

    def test_an_offset_that_cannot_be_read_gives_no_now(self):
        payload = hourly_payload([0] * 24)
        del payload["current"]
        payload["utc_offset_seconds"] = "not a number"
        self.assertIsNone(parse.local_now(payload))


class TestABrokenHourlyBlock(unittest.TestCase):
    """The hours are an addition to the week, not part of it.

    A strip that cannot be read takes the strip away and leaves the week.
    Without a handler the failure is raised, so a caller that cannot
    handle it has to say so.
    """

    BROKEN = (
        "not an object",
        {"time": 5},
        {"time": ["2026-10-21T00:00"], "precipitation_probability": {"a": 1}},
    )

    def _payload(self, hourly):
        return {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [80, 20],
            },
            "hourly": hourly,
        }

    def test_the_week_survives_a_broken_strip(self):
        for hourly in self.BROKEN:
            with self.subTest(hourly=hourly):
                forecast = parse.parse_forecast(
                    self._payload(hourly), on_hourly_error=lambda exc: None)
                self.assertEqual(len(forecast.days), 2)
                self.assertEqual(forecast.today, ())

    def test_the_handler_is_told_about_it(self):
        for hourly in self.BROKEN:
            with self.subTest(hourly=hourly):
                seen = []
                parse.parse_forecast(self._payload(hourly),
                                     on_hourly_error=seen.append)
                self.assertEqual(len(seen), 1)

    def test_without_a_handler_the_failure_is_raised(self):
        for hourly in self.BROKEN:
            with self.subTest(hourly=hourly):
                with self.assertRaises((TypeError, ValueError, KeyError,
                                        AttributeError)):
                    parse.parse_forecast(self._payload(hourly))

    def test_a_strip_with_no_times_is_no_strip(self):
        """An empty hourly block is a missing feature, not a failure."""
        forecast = parse.parse_forecast(self._payload({"time": []}),
                                        on_hourly_error=lambda exc: None)
        self.assertEqual(len(forecast.days), 2)
        self.assertEqual(forecast.today, ())

    def test_a_strip_with_no_daily_list_falls_back_to_its_own_first_day(self):
        """The hours line up with the daily list, but there is no list."""
        payload = {
            "hourly": {
                "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
                "precipitation_probability": [5] * 24,
            },
            "current": {"time": "2026-10-21T09:00"},
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.today), 24)
        self.assertEqual(forecast.today[0].moment.date().isoformat(),
                         "2026-10-21")

    def test_a_strip_that_starts_on_another_day_still_draws(self):
        """The hourly array does not start on the first day of the daily
        list, so the strip falls back to the first day of the array."""
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [80, 20],
            },
            "hourly": {
                "time": [f"2026-10-22T{hour:02d}:00" for hour in range(24)],
                "precipitation_probability": [5] * 24,
            },
            "current": {"time": "2026-10-21T09:00"},
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.days), 2)
        self.assertEqual(len(forecast.days[0].hours), 24)

    def test_a_strip_with_no_readable_time_is_no_strip(self):
        payload = {
            "daily": {"time": ["2026-10-21"],
                      "precipitation_probability_max": [80]},
            "hourly": {"time": ["not-a-time", "also-not"],
                       "precipitation_probability": [5, 6]},
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.days), 1)
        self.assertEqual(forecast.days[0].hours, ())

    def test_an_hourly_array_with_nothing_in_it_is_no_strip(self):
        """There is no day to draw and no hour to draw it with."""
        payload = {
            "daily": {"time": [], "precipitation_probability_max": []},
            "hourly": {"time": [], "precipitation_probability": []},
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(forecast.days, ())
        self.assertEqual(forecast.today, ())


class TestDaysAndHours(unittest.TestCase):
    """The forecast as the app understands it."""

    def test_a_day_carries_its_own_numbers(self):
        payload = {
            "daily": {
                "time": ["2026-10-21"],
                "precipitation_probability_max": [80],
                "temperature_2m_max": [12.0],
                "temperature_2m_min": [8.0],
                "precipitation_sum": [4.2],
                "precipitation_hours": [3.0],
            }
        }
        day = parse.parse_forecast(payload).days[0]
        self.assertEqual(day.iso_date, "2026-10-21")
        self.assertEqual(day.chance, 80)
        self.assertEqual(day.high, 12.0)
        self.assertEqual(day.low, 8.0)
        self.assertEqual(day.amount, 4.2)
        self.assertEqual(day.rain_hours, 3.0)

    def test_a_day_with_no_numbers_of_its_own_still_stands(self):
        """A day the service reported no figures for is still a day."""
        payload = {
            "daily": {
                "time": ["2026-10-21"],
                "precipitation_probability_max": [None],
            }
        }
        day = parse.parse_forecast(payload).days[0]
        self.assertIsNone(day.chance)
        self.assertIsNone(day.high)
        self.assertIsNone(day.low)
        self.assertIsNone(day.amount)
        self.assertIsNone(day.rain_hours)

    def test_the_daily_list_is_the_primary_result(self):
        """The days come back even when there are no hours at all."""
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [80, 20],
            }
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.days), 2)
        self.assertEqual(forecast.today, ())

    def test_a_day_with_more_hours_than_the_list_is_kept_whole(self):
        """A clock-change day has 23 or 25 hours, and is not truncated.

        A day that falls back repeats one of its hours, so the same local
        hour appears twice in the array. The strip keeps both.
        """
        times = [f"2026-10-21T{hour:02d}:00" for hour in range(24)]
        times.append("2026-10-21T02:00")
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22"],
                "precipitation_probability_max": [80, 20],
            },
            "hourly": {
                "time": times,
                "precipitation_probability": [5] * 25,
            },
            "current": {"time": "2026-10-21T09:00"},
        }
        forecast = parse.parse_forecast(payload)
        self.assertEqual(len(forecast.days[0].hours), 25)


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
