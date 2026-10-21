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
    }
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


if __name__ == "__main__":
    unittest.main(verbosity=2)