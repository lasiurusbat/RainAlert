"""The Open-Meteo client: what it asks for, and what it does with the
answer.

The service is a third party, so the client checks the answer before it
uses it. An answer that is not a forecast is a broken answer and is
reported as one; a missing hourly block is a missing feature, not a broken
forecast, and degrades to a page without a strip.
"""

import json
import unittest
from unittest import mock

import requests

from rainalert.errors import FAILURES, WeatherUnavailable
from rainalert.upstream import open_meteo
from tests.fixtures import FORECAST_PAYLOAD, FakeResponse


class RecordingResponse:
    """A response that remembers how it was asked for."""

    #: Stands for "the response carried no JSON at all".
    NO_JSON = object()

    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = FORECAST_PAYLOAD if payload is None else payload
        self.status_code = status_code
        self.text = text or ""
        self.params = None
        self.timeout = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if self._payload is self.NO_JSON:
            raise ValueError("no JSON here")
        return self._payload


class TestForecastRequest(unittest.TestCase):
    """The one request per page load."""

    def setUp(self):
        self.response = RecordingResponse()
        self.get = mock.patch.object(requests, "get",
                                     return_value=self.response).start()
        self.addCleanup(mock.patch.stopall)

    def test_the_request_carries_every_field_the_page_needs(self):
        """The daily fields, the hourly chance and the current hour all come
        in one call, so a page load costs one request and not three."""
        open_meteo.fetch_payload(51.5, -0.12)
        params = self.get.call_args.kwargs["params"]
        self.assertIn("precipitation_probability_max", params["daily"])
        self.assertIn("temperature_2m_max", params["daily"])
        self.assertIn("temperature_2m_min", params["daily"])
        self.assertIn("precipitation_sum", params["daily"])
        self.assertIn("precipitation_hours", params["daily"])
        self.assertEqual(params["hourly"], "precipitation_probability")
        self.assertEqual(params["current"], "precipitation_probability")
        self.assertEqual(params["timezone"], "auto")

    def test_the_request_carries_the_coordinates(self):
        open_meteo.fetch_payload(51.5, -0.12)
        params = self.get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], 51.5)
        self.assertEqual(params["longitude"], -0.12)

    def test_the_request_asks_for_the_citys_own_time(self):
        """The forecast is dated in the city's local time, so the service is
        asked for it rather than the app converting it."""
        open_meteo.fetch_payload(51.5, -0.12)
        self.assertEqual(self.get.call_args.kwargs["params"]["timezone"],
                         "auto")

    def test_the_request_always_has_a_timeout(self):
        """requests.get has no default timeout, and a hung request would
        hang the page."""
        open_meteo.fetch_payload(51.5, -0.12)
        self.assertIsNotNone(self.get.call_args.kwargs.get("timeout"))

    def test_the_request_asks_for_the_scale_the_reader_wants(self):
        open_meteo.fetch_payload(51.5, -0.12, unit="fahrenheit")
        self.assertEqual(self.get.call_args.kwargs["params"]
                         ["temperature_unit"], "fahrenheit")


class TestForecastFailures(unittest.TestCase):
    """Every way the service can let the app down."""

    def _fetch(self, response=None, side_effect=None):
        get = mock.patch.object(
            requests, "get",
            side_effect=side_effect,
            return_value=response or RecordingResponse())
        with get:
            return open_meteo.fetch_payload(51.5, -0.12)

    def test_a_timeout_is_a_failure(self):
        with self.assertRaises(WeatherUnavailable):
            self._fetch(side_effect=requests.Timeout())

    def test_an_http_error_is_a_failure(self):
        with self.assertRaises(WeatherUnavailable):
            self._fetch(response=RecordingResponse(status_code=500))

    def test_a_broken_connection_is_a_failure(self):
        with self.assertRaises(WeatherUnavailable):
            self._fetch(side_effect=requests.ConnectionError("down"))

    def test_an_answer_that_is_not_json_is_a_failure(self):
        """A proxy's error page is not a forecast, and it is not JSON
        either."""
        response = RecordingResponse(payload=RecordingResponse.NO_JSON)
        with self.assertRaises(WeatherUnavailable):
            self._fetch(response=response)

    def test_an_answer_that_is_not_a_forecast_is_a_failure(self):
        """An error page served as JSON is a broken answer, and it is
        reported as one, so the reader is told to come back in a moment
        rather than shown an empty week."""
        for payload in ([1, 2, 3], "error", {"daily": "not an object"}):
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherUnavailable):
                    self._fetch(response=RecordingResponse(payload=payload))

    def test_a_transport_failure_is_reported_as_our_own_failure(self):
        """The reader is told the service is unavailable, not what the
        transport said. The internal text is logged, never rendered."""
        try:
            self._fetch(side_effect=requests.ConnectionError("secret host"))
        except WeatherUnavailable:
            pass
        else:
            self.fail("a transport failure must be a WeatherUnavailable")
        # What the page shows comes from the failure table, not from here.
        self.assertIn("The weather service is unavailable right now.",
                      FAILURES[WeatherUnavailable].page_message)


class TestForecastShape(unittest.TestCase):
    """What the client accepts as a forecast."""

    def test_a_forecast_is_a_forecast(self):
        self.assertTrue(open_meteo._is_a_forecast(FORECAST_PAYLOAD))

    def test_an_answer_with_no_daily_block_is_still_a_forecast(self):
        """The service answered and had no forecast to give. The page says
        so and stays up, so it is not a broken answer."""
        self.assertTrue(open_meteo._is_a_forecast({}))

    def test_an_answer_that_is_not_an_object_is_not_a_forecast(self):
        for payload in ([1, 2, 3], "error", 42, None):
            with self.subTest(payload=payload):
                self.assertFalse(open_meteo._is_a_forecast(payload))

    def test_a_daily_block_that_is_not_an_object_is_not_a_forecast(self):
        self.assertFalse(open_meteo._is_a_forecast({"daily": "not an object"}))

    def test_a_daily_field_that_is_not_an_array_is_not_a_forecast(self):
        """A field that is there but is the wrong shape is a broken answer
        in the same way."""
        for field in open_meteo.DAILY_ARRAYS:
            with self.subTest(field=field):
                payload = {"daily": {field: "not an array"}}
                self.assertFalse(open_meteo._is_a_forecast(payload))

    def test_a_daily_field_that_is_missing_is_not_a_broken_answer(self):
        """A field the service did not send is a field with no value in it,
        and the page says the day was not reported."""
        for field in open_meteo.DAILY_ARRAYS:
            with self.subTest(field=field):
                payload = {"daily": {key: [] for key in open_meteo.DAILY_ARRAYS
                                     if key != field}}
                self.assertTrue(open_meteo._is_a_forecast(payload))


class TestBrokenHourlyBlock(unittest.TestCase):
    """A broken hourly block is a missing feature, not a broken forecast.

    The week is the primary result. The hours are an addition to it, so a
    strip that cannot be read takes the strip away and leaves the week.
    """

    def _forecast(self, payload):
        with mock.patch.object(requests, "get",
                               return_value=RecordingResponse(payload)):
            return open_meteo.load_forecast(51.5, -0.12)

    def test_a_broken_hourly_block_leaves_the_week(self):
        for hourly in ("not an object", {"time": 5},
                       {"time": ["2026-10-21T00:00"],
                        "precipitation_probability": {"not": "a list"}}):
            with self.subTest(hourly=hourly):
                payload = {
                    "daily": {
                        "time": ["2026-10-21", "2026-10-22"],
                        "precipitation_probability_max": [80, 20],
                    },
                    "hourly": hourly,
                }
                forecast = self._forecast(payload)
                self.assertEqual(len(forecast.days), 2)
                self.assertEqual(forecast.today, ())

    def test_a_broken_hourly_block_is_logged(self):
        """The strip goes away quietly, but the log says why."""
        payload = {"daily": {"time": ["2026-10-21"]}, "hourly": "junk"}
        with self.assertLogs("rainalert.upstream.open_meteo",
                             level="WARNING") as logged:
            self._forecast(payload)
        self.assertIn("Hourly forecast could not be parsed", logged.output[0])


class TestLoadForecast(unittest.TestCase):
    """The client and the parser together."""

    def test_the_days_and_the_hours_come_back_together(self):
        with mock.patch.object(requests, "get",
                               return_value=RecordingResponse()):
            forecast = open_meteo.load_forecast(51.5, -0.12)
        self.assertEqual(len(forecast.days), 3)
        self.assertEqual(len(forecast.today), 24)


class TestForecastCache(unittest.TestCase):
    """The server keeps a forecast for a while, because the service answers
    HTTP 429 once an IP address asks for too much."""

    def setUp(self):
        open_meteo.clear_cache()
        patcher = mock.patch.object(open_meteo.config,
                                    "WEATHER_CACHE_SECONDS", 600)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(open_meteo.clear_cache)

    def fetch(self, get, lat=51.5, lon=-0.12, unit=None):
        with mock.patch.object(requests, "get", get):
            return open_meteo.fetch_payload(lat, lon, unit)

    def test_a_second_request_for_the_same_place_costs_no_call(self):
        get = mock.Mock(return_value=FakeResponse())
        self.fetch(get)
        self.fetch(get)
        self.assertEqual(get.call_count, 1)

    def test_another_place_or_another_scale_is_its_own_forecast(self):
        get = mock.Mock(return_value=FakeResponse())
        self.fetch(get)
        self.fetch(get, lat=48.85, lon=2.35)
        self.fetch(get, unit="fahrenheit")
        self.assertEqual(get.call_count, 3)

    def test_a_forecast_goes_stale(self):
        get = mock.Mock(return_value=FakeResponse())
        clock = mock.Mock()
        with mock.patch.object(open_meteo, "time", clock):
            clock.monotonic.return_value = 0
            self.fetch(get)   # stored at 0
            clock.monotonic.return_value = 599
            self.fetch(get)   # 599 seconds old: still fresh
            clock.monotonic.return_value = 601
            self.fetch(get)   # 601 seconds old: fetched again
        self.assertEqual(get.call_count, 2)

    def test_a_failure_is_not_kept(self):
        """A retry has to ask again, or one 429 would last ten minutes."""
        limited = mock.Mock(return_value=FakeResponse(status_code=429))
        with self.assertRaises(WeatherUnavailable):
            self.fetch(limited)
        recovered = mock.Mock(return_value=FakeResponse())
        self.fetch(recovered)
        self.assertEqual(recovered.call_count, 1)

    def test_a_broken_answer_is_not_kept(self):
        broken = mock.Mock(return_value=FakeResponse(payload=["junk"]))
        with self.assertRaises(WeatherUnavailable):
            self.fetch(broken)
        good = mock.Mock(return_value=FakeResponse())
        self.fetch(good)
        self.assertEqual(good.call_count, 1)

    def test_zero_turns_the_cache_off(self):
        get = mock.Mock(return_value=FakeResponse())
        with mock.patch.object(open_meteo.config, "WEATHER_CACHE_SECONDS", 0):
            self.fetch(get)
            self.fetch(get)
        self.assertEqual(get.call_count, 2)

    def test_a_caller_cannot_change_the_stored_copy(self):
        # A copy of the fixture, so clearing it here cannot reach the tests
        # that share it.
        payload = json.loads(json.dumps(FORECAST_PAYLOAD))
        get = mock.Mock(return_value=FakeResponse(payload=payload))
        first = self.fetch(get)
        first["daily"]["time"].clear()
        again = self.fetch(get)
        self.assertTrue(again["daily"]["time"])

    def test_the_oldest_forecast_goes_when_the_cache_is_full(self):
        get = mock.Mock(return_value=FakeResponse())
        with mock.patch.object(open_meteo, "MAX_CACHED_FORECASTS", 2):
            self.fetch(get, lat=1, lon=1)
            self.fetch(get, lat=2, lon=2)
            self.fetch(get, lat=3, lon=3)   # evicts (1, 1)
            self.fetch(get, lat=1, lon=1)   # fetched again
        self.assertEqual(get.call_count, 4)


class TestRefusalIsLogged(unittest.TestCase):
    """A 429 says which limit was hit; the log has to carry that."""

    def refuse(self, response):
        with mock.patch.object(requests, "get", return_value=response):
            with self.assertRaises(WeatherUnavailable) as caught:
                open_meteo.fetch_payload(51.5, -0.12)
        return str(caught.exception)

    def test_the_services_reason_is_in_the_message(self):
        reason = "Hourly API request limit exceeded. Please try again in the next hour."
        text = self.refuse(FakeResponse(
            payload={"error": True, "reason": reason}, status_code=429))
        self.assertIn("HTTP 429", text)
        self.assertIn(reason, text)

    def test_the_wait_it_asks_for_is_in_the_message(self):
        response = FakeResponse(status_code=429)
        response.headers = {"Retry-After": "3600"}
        self.assertIn("retry after 3600", self.refuse(response))

    def test_an_answer_with_no_json_still_reports_the_status(self):
        response = FakeResponse(status_code=502)
        response.json = mock.Mock(side_effect=ValueError("no json"))
        self.assertEqual(self.refuse(response),
                         "the forecast service returned HTTP 502")

    def test_a_long_reason_is_cut_short(self):
        text = self.refuse(FakeResponse(
            payload={"reason": "x" * 5000}, status_code=429))
        self.assertLess(len(text), 300)
