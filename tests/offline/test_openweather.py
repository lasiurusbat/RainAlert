"""The second source of forecasts: OpenWeather One Call 4.0, used only when
Open-Meteo refuses a request.

Everything is mocked at the HTTP boundary. A forecast is two calls - the days
and the hours - and the answer is translated into Open-Meteo's shape, so most
of these tests check the translation and that the rest of the app reads the
result like any other forecast.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import requests

from rainalert import config
from rainalert.domain.parse import parse_forecast
from rainalert.errors import WeatherUnavailable
from rainalert.upstream import open_meteo, openweather
from tests.fixtures import AppTestCase, FakeResponse

KEY = "secret-key-123"
OFFSET = 3600  # Paris, after the clocks went back

# 29.10.2026, 15:30 in Paris.
NOW = datetime(2026, 10, 29, 14, 30, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    """``datetime`` with a clock that says what ``NOW`` says."""

    NOW = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.NOW if tz is None else cls.NOW.astimezone(tz)


def stamp(day, hour, minute=0, offset=OFFSET):
    """The Unix time of a local wall-clock moment, ``day`` counting from 1 Oct."""
    local = datetime(2026, 10, 1, hour, minute, tzinfo=timezone.utc)
    local += timedelta(days=day - 1)
    return int((local - timedelta(seconds=offset)).timestamp())


def days_body(count=10):
    """The daily timeline, from 29.10.2026."""
    data = []
    for index in range(count):
        data.append({
            "dt": stamp(29 + index, 12),
            "temp": {"min": 8.4 + index, "max": 14.0 + index, "day": 12.0},
            "pop": 0.8 if index == 0 else 0.2,
        })
    data[0]["rain"] = 3.2
    data[1]["snow"] = 1.1
    return {"lat": 48.85, "lon": 2.35, "timezone": "Europe/Paris",
            "timezone_offset": OFFSET, "data": data}


def hours_body(start=15, count=20):
    """The hourly timeline: ``count`` hours from ``start`` o'clock today."""
    data = [{"dt": stamp(29, start) + 3600 * step,
             "pop": 0.5 if step == 0 else 0.1}
            for step in range(count)]
    return {"lat": 48.85, "lon": 2.35, "timezone": "Europe/Paris",
            "timezone_offset": OFFSET, "data": data}


def route(open_meteo_answer, days_answer=None, hours_answer=None):
    """A ``requests.get`` that answers each endpoint its own way."""
    answers = {
        open_meteo.FORECAST_URL: open_meteo_answer,
        openweather.DAILY_URL: days_answer,
        openweather.HOURLY_URL: hours_answer,
    }

    def get(url, **kwargs):
        if url not in answers or answers[url] is None:
            raise AssertionError(f"unexpected request to {url}")
        return answers[url]
    return mock.Mock(side_effect=get)


def both(days=None, hours=None):
    """A ``requests.get`` for OpenWeather's two endpoints."""
    return route(None,
                 FakeResponse(payload=days if days is not None else days_body()),
                 FakeResponse(payload=hours if hours is not None else hours_body()))


class KeyedTestCase(unittest.TestCase):
    """A test with the key set, a fresh day's allowance and a frozen clock."""

    def setUp(self):
        openweather.reset_budget()
        FrozenDatetime.NOW = NOW
        for target, name, value in (
                (config, "OPENWEATHER_API_KEY", KEY),
                (config, "OPENWEATHER_DAILY_LIMIT", 900),
                (openweather, "datetime", FrozenDatetime)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(openweather.reset_budget)


class TestTranslation(KeyedTestCase):
    def translate(self, days=None, hours=None):
        with mock.patch.object(requests, "get", both(days, hours)):
            return openweather.fallback(48.85, 2.35)

    def test_the_days_are_the_locations_own_dates(self):
        dates = self.translate()["daily"]["time"]
        self.assertEqual(dates[:3], ["2026-10-29", "2026-10-30", "2026-10-31"])
        # Ten come back, the week is seven.
        self.assertEqual(len(dates), 7)

    def test_a_chance_is_a_whole_percent(self):
        chances = self.translate()["daily"]["precipitation_probability_max"]
        self.assertEqual(chances[:2], [80, 20])

    def test_a_missing_chance_stays_unknown(self):
        body = days_body()
        del body["data"][1]["pop"]
        chances = self.translate(days=body)["daily"]["precipitation_probability_max"]
        self.assertIsNone(chances[1])

    def test_the_temperatures_come_across(self):
        daily = self.translate()["daily"]
        self.assertEqual(daily["temperature_2m_max"][0], 14.0)
        self.assertEqual(daily["temperature_2m_min"][0], 8.4)

    def test_rain_and_snow_are_water_and_a_silent_day_is_unknown(self):
        amounts = self.translate()["daily"]["precipitation_sum"]
        # Rain on the first day, snow on the second, nothing said on the
        # third: that is not the same as dry.
        self.assertEqual(amounts[:3], [3.2, 1.1, None])

    def test_the_documented_rate_shape_leaves_the_amount_unknown(self):
        # The docs give rain and snow as {"1h": mm/h}, a rate and not a
        # day's total, so no millimetres are invented from it.
        body = days_body()
        body["data"][0]["rain"] = {"1h": 0.5}
        body["data"][1]["snow"] = {"1h": 0.2}
        payload = openweather._translate(body, None)
        self.assertEqual(payload["daily"]["precipitation_sum"][:2], [None, None])

    def test_how_long_the_rain_lasts_is_not_invented(self):
        daily = self.translate()["daily"]
        self.assertEqual(set(daily["precipitation_hours"]), {None})

    def test_the_hours_are_whole_days_with_the_gaps_unknown(self):
        hourly = self.translate()["hourly"]
        times, chances = hourly["time"], hourly["precipitation_probability"]
        # Today and the morning of tomorrow, each filled out to 24 hours.
        self.assertEqual(len(times), 48)
        self.assertEqual(times[0], "2026-10-29T00:00")
        self.assertEqual(chances[:15], [None] * 15)       # gone already
        self.assertEqual(times[15], "2026-10-29T15:00")
        self.assertEqual(chances[15], 50)
        self.assertEqual(chances[16], 10)
        self.assertEqual(times[24], "2026-10-30T00:00")
        self.assertEqual(chances[24 + 10], 10)             # 10:00 tomorrow
        self.assertEqual(chances[24 + 11], None)           # not reported

    def test_the_current_time_comes_from_the_clock_and_the_offset(self):
        payload = self.translate()
        self.assertEqual(payload["current"]["time"], "2026-10-29T15:30")
        self.assertEqual(payload["utc_offset_seconds"], OFFSET)

    def test_the_rest_of_the_app_reads_it_like_any_forecast(self):
        forecast = parse_forecast(self.translate())
        self.assertEqual(len(forecast.days), 7)
        self.assertEqual(forecast.days[0].chance, 80)
        self.assertEqual(len(forecast.today), 24)
        now = [hour for hour in forecast.today if hour.now]
        self.assertEqual([hour.moment.hour for hour in now], [15])
        self.assertIsNone(forecast.today[0].chance)

    def test_a_day_past_the_hours_has_none(self):
        """The hours stop after a day or so; the page says so."""
        forecast = parse_forecast(self.translate())
        self.assertTrue(forecast.days[1].hours)
        self.assertEqual(forecast.days[6].hours, ())

    def test_the_answer_is_a_forecast_by_the_validators_own_rule(self):
        self.assertTrue(open_meteo._is_a_forecast(self.translate()))


class TestTheRequests(KeyedTestCase):
    def ask(self, unit=None):
        get = both()
        with mock.patch.object(requests, "get", get):
            openweather.fallback(48.85, 2.35, unit)
        return get

    def test_the_days_and_the_hours_are_asked_for(self):
        get = self.ask()
        urls = [call.args[0] for call in get.call_args_list]
        self.assertEqual(urls, [openweather.DAILY_URL, openweather.HOURLY_URL])
        self.assertIn("/data/4.0/onecall/timeline/1day", openweather.DAILY_URL)
        self.assertIn("/data/4.0/onecall/timeline/1h", openweather.HOURLY_URL)

    def test_the_key_the_place_and_the_scale_are_sent_with_each(self):
        for call in self.ask("fahrenheit").call_args_list:
            params = call.kwargs["params"]
            self.assertEqual(params["appid"], KEY)
            self.assertEqual((params["lat"], params["lon"]), (48.85, 2.35))
            self.assertEqual(params["units"], "imperial")
            self.assertEqual(call.kwargs["timeout"], config.WEATHER_TIMEOUT)

    def test_celsius_is_metric(self):
        for call in self.ask("celsius").call_args_list:
            self.assertEqual(call.kwargs["params"]["units"], "metric")

    def test_no_key_means_no_fallback_and_no_call(self):
        with mock.patch.object(config, "OPENWEATHER_API_KEY", ""), \
                mock.patch.object(requests, "get") as get:
            self.assertIsNone(openweather.fallback(48.85, 2.35))
        get.assert_not_called()


class TestFailures(KeyedTestCase):
    def fail(self, get):
        with self.assertLogs("rainalert.upstream.openweather", "WARNING") as logs:
            with mock.patch.object(requests, "get", get):
                result = openweather.fallback(48.85, 2.35)
        self.assertIsNone(result)
        return "\n".join(logs.output)

    def test_a_refused_week_is_none_and_the_hours_are_not_asked(self):
        get = route(None, FakeResponse(status_code=401), FakeResponse())
        text = self.fail(get)
        self.assertIn("HTTP 401", text)
        self.assertEqual(get.call_count, 1)

    def test_a_timeout_is_none(self):
        get = mock.Mock(side_effect=requests.Timeout("x"))
        self.assertIn("timed out", self.fail(get))

    def test_a_broken_week_is_none(self):
        for payload in (["junk"], {"data": "junk", "timezone_offset": 0},
                        {"data": [], "timezone_offset": 0},
                        {"timezone_offset": "x", "data": [{}]},
                        {"timezone_offset": 0, "data": [{"dt": 1}]}):
            with self.subTest(payload=payload):
                self.fail(route(None, FakeResponse(payload=payload),
                                FakeResponse(payload=hours_body())))

    def test_the_key_never_reaches_the_log(self):
        """A request error's text is the URL, and the URL has the key."""
        error = requests.ConnectionError(f"max retries: ...?appid={KEY}&lat=1")
        text = self.fail(mock.Mock(side_effect=error))
        self.assertNotIn(KEY, text)
        self.assertIn("ConnectionError", text)


class TestTheHoursAreAnAddition(KeyedTestCase):
    """The hours are an addition to the week, as they are for Open-Meteo."""

    def week_without_hours(self, hours_answer):
        get = route(None, FakeResponse(payload=days_body()), hours_answer)
        with self.assertLogs("rainalert.upstream.openweather", "WARNING") as logs:
            with mock.patch.object(requests, "get", get):
                payload = openweather.fallback(48.85, 2.35)
        return payload, "\n".join(logs.output)

    def test_refused_hours_leave_the_week(self):
        payload, text = self.week_without_hours(FakeResponse(status_code=500))
        self.assertEqual(len(payload["daily"]["time"]), 7)
        self.assertNotIn("hourly", payload)
        self.assertIn("HTTP 500", text)

    def test_unreadable_hours_leave_the_week(self):
        payload, _ = self.week_without_hours(
            FakeResponse(payload={"timezone_offset": 0, "data": "junk"}))
        self.assertEqual(len(payload["daily"]["time"]), 7)
        self.assertNotIn("hourly", payload)

    def test_the_rest_of_the_app_reads_a_week_without_hours(self):
        payload, _ = self.week_without_hours(FakeResponse(status_code=500))
        forecast = parse_forecast(payload)
        self.assertEqual(len(forecast.days), 7)
        self.assertEqual(forecast.today, ())


class TestTheDailyAllowance(KeyedTestCase):
    def forecasts(self, limit, count):
        """How many of ``count`` forecasts come back at ``limit``."""
        with mock.patch.object(config, "OPENWEATHER_DAILY_LIMIT", limit), \
                mock.patch.object(requests, "get", both()), \
                self.assertLogs("rainalert.upstream.openweather", "WARNING"):
            # assertLogs needs one record; a spent allowance supplies it, and
            # a call past the end of the list makes sure there is one.
            results = [openweather.fallback(48.85, 2.35) for _ in range(count)]
            openweather.fallback(48.85, 2.35)
        return sum(1 for result in results if result is not None)

    def test_each_forecast_costs_its_two_calls(self):
        self.assertEqual(self.forecasts(limit=4, count=3), 2)

    def test_a_forecast_that_does_not_fit_is_not_half_made(self):
        """With one call left, the days alone are not asked for."""
        self.assertEqual(self.forecasts(limit=3, count=3), 1)

    def test_a_new_day_starts_the_count_again(self):
        get = both()
        with mock.patch.object(config, "OPENWEATHER_DAILY_LIMIT", 2), \
                mock.patch.object(requests, "get", get):
            self.assertIsNotNone(openweather.fallback(48.85, 2.35))
            with self.assertLogs("rainalert.upstream.openweather", "WARNING"):
                self.assertIsNone(openweather.fallback(48.85, 2.35))
            FrozenDatetime.NOW = NOW + timedelta(days=1)
            self.assertIsNotNone(openweather.fallback(48.85, 2.35))
        self.assertEqual(get.call_count, 4)


class TestTheFallbackInTheFetchPath(KeyedTestCase):
    def setUp(self):
        super().setUp()
        open_meteo.clear_cache()
        self.addCleanup(open_meteo.clear_cache)

    def answers(self, open_meteo_answer):
        return route(open_meteo_answer, FakeResponse(payload=days_body()),
                     FakeResponse(payload=hours_body()))

    def test_a_refusal_is_answered_by_the_second_source(self):
        get = self.answers(FakeResponse(status_code=429))
        with mock.patch.object(requests, "get", get), \
                self.assertLogs("rainalert.upstream.open_meteo", "WARNING") as logs:
            payload = open_meteo.fetch_payload(48.85, 2.35)
        self.assertEqual(payload["daily"]["time"][0], "2026-10-29")
        self.assertIn("HTTP 429", logs.output[0])
        self.assertIn("OpenWeather", logs.output[0])

    def test_open_meteo_is_asked_first_and_alone_when_it_answers(self):
        get = self.answers(FakeResponse())
        with mock.patch.object(requests, "get", get):
            open_meteo.fetch_payload(48.85, 2.35)
        self.assertEqual(get.call_count, 1)

    def test_without_a_key_the_refusal_stands(self):
        get = self.answers(FakeResponse(status_code=429))
        with mock.patch.object(config, "OPENWEATHER_API_KEY", ""), \
                mock.patch.object(requests, "get", get):
            with self.assertRaises(WeatherUnavailable) as caught:
                open_meteo.fetch_payload(48.85, 2.35)
        self.assertIn("HTTP 429", str(caught.exception))
        self.assertEqual(get.call_count, 1)

    def test_when_both_refuse_the_first_refusal_is_the_one_reported(self):
        get = route(FakeResponse(status_code=429), FakeResponse(status_code=401))
        with mock.patch.object(requests, "get", get), \
                self.assertLogs("rainalert.upstream.openweather", "WARNING"):
            with self.assertRaises(WeatherUnavailable) as caught:
                open_meteo.fetch_payload(48.85, 2.35)
        self.assertIn("HTTP 429", str(caught.exception))

    def test_the_second_sources_answer_is_kept_like_any_other(self):
        """The allowance is small, so a repeat must not spend it again."""
        get = self.answers(FakeResponse(status_code=429))
        with mock.patch.object(config, "WEATHER_CACHE_SECONDS", 600), \
                mock.patch.object(requests, "get", get), \
                self.assertLogs("rainalert.upstream.open_meteo", "WARNING"):
            open_meteo.fetch_payload(48.85, 2.35)
            open_meteo.fetch_payload(48.85, 2.35)
        self.assertEqual(get.call_count, 3)  # one refusal, two for the week


class TestThePage(AppTestCase):
    def setUp(self):
        super().setUp()
        open_meteo.clear_cache()
        openweather.reset_budget()
        FrozenDatetime.NOW = NOW
        self.addCleanup(openweather.reset_budget)
        for target, name, value in (
                (config, "OPENWEATHER_API_KEY", KEY),
                (openweather, "datetime", FrozenDatetime)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def page(self, hours=None, path="/city/london"):
        self.mock_get.side_effect = route(
            FakeResponse(status_code=429),
            FakeResponse(payload=days_body()),
            hours if hours is not None else FakeResponse(payload=hours_body())
        ).side_effect
        with self.assertLogs("rainalert", "WARNING"):
            return self.client.get(path)

    def test_a_refused_forecast_still_makes_a_page(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Thursday 29.10.2026", body)
        self.assertIn("Hourly detail is not available for this day.", body)

    def test_a_week_with_no_hours_still_makes_a_page(self):
        response = self.page(hours=FakeResponse(status_code=500))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Thursday 29.10.2026", response.get_data(as_text=True))

    def test_the_footer_credits_the_second_source_when_there_is_one(self):
        body = self.page().get_data(as_text=True)
        self.assertIn("Open-Meteo.com", body)
        self.assertIn("https://openweathermap.org/", body)

    def test_the_footer_does_not_credit_a_source_that_is_not_set_up(self):
        self.mock_get.side_effect = None
        self.mock_get.return_value = FakeResponse()
        with mock.patch.object(config, "OPENWEATHER_API_KEY", ""):
            body = self.client.get("/city/london").get_data(as_text=True)
        self.assertIn("Open-Meteo.com", body)
        self.assertNotIn("openweathermap.org", body)

    def test_the_key_is_never_on_the_page(self):
        self.assertNotIn(KEY, self.page().get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
