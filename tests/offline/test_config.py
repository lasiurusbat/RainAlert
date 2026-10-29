"""The settings read from the environment: the donation link, the build's
identity and the temperature scale.
"""

import importlib
import os
import unittest
from unittest import mock

from rainalert import config
from tests.fixtures import (AppTestCase, DONATION_HREF, DONATION_URL,
                            FakeResponse)


class TestCleanDonationUrl(unittest.TestCase):
    """The donation link goes into every page, so it is validated."""

    def test_accepts_an_https_link(self):
        self.assertEqual(config.clean_donation_url(DONATION_URL), DONATION_URL)

    def test_trims_surrounding_whitespace(self):
        self.assertEqual(
            config.clean_donation_url(f"  {DONATION_URL}\n"), DONATION_URL)

    def test_empty_and_missing_values_mean_no_link(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(config.clean_donation_url(value), "")

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
                self.assertEqual(config.clean_donation_url(value), "")


class TestDonationLink(AppTestCase):
    """The optional Buy Me a Coffee link."""

    def post(self, city="London"):
        return self.client.post("/", data={"city": city}).get_data(as_text=True)

    def test_no_link_by_default(self):
        with mock.patch.object(config, "DONATION_URL", ""):
            for body in (self.client.get("/").get_data(as_text=True), self.post()):
                self.assertNotIn("buymeacoffee", body)
                self.assertNotIn("Buy me a coffee", body)
                self.assertNotIn('class="donate"', body)

    def test_start_page_has_the_line_and_the_footer_link(self):
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
            body = self.client.get("/").get_data(as_text=True)
        self.assertEqual(body.count(DONATION_HREF), 2)
        self.assertIn('class="donate"', body)

    def test_forecast_page_has_the_line_under_the_button_and_the_footer_link(self):
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
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
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
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
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertIn("(donation, opens in a new tab)", body)

    def test_the_line_is_on_error_pages_too(self):
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
            empty = self.client.post("/", data={"city": ""}).get_data(as_text=True)
            self.mock_geocode.return_value = None
            missing = self.post("Nowhereville")
        for body in (empty, missing):
            self.assertIn('class="error"', body)
            self.assertIn('class="donate"', body)

    def test_the_line_is_shown_when_there_is_no_forecast(self):
        self.mock_get.return_value = FakeResponse({"daily": {}})
        with mock.patch.object(config, "DONATION_URL", DONATION_URL):
            body = self.post()
        self.assertIn("No forecast data available", body)
        self.assertIn('class="donate"', body)

    def test_an_unsafe_value_in_the_environment_is_ignored(self):
        self.assertEqual(config.clean_donation_url("javascript:alert(1)"), "")
        with mock.patch.object(config, "DONATION_URL", ""):
            self.assertNotIn("javascript:", self.post())


class TestTemperatureUnit(unittest.TestCase):
    """The scale the service converts to, and what a bad setting does.

    The setting is read at import, so the module is reloaded with the
    environment patched. The reload puts the module back the way it was
    afterwards, so the rest of the suite is not affected.
    """

    def reload_with(self, value):
        """The default scale with TEMPERATURE_UNIT set to ``value``."""
        try:
            with mock.patch.dict(os.environ, clear=False):
                if value is None:
                    os.environ.pop("TEMPERATURE_UNIT", None)
                else:
                    os.environ["TEMPERATURE_UNIT"] = value
                # A reload replaces the module's contents in place, so the
                # value has to be read before the module is put back.
                importlib.reload(config)
                return config.DEFAULT_TEMPERATURE_UNIT
        finally:
            # The environment is back to what it was, so the module is
            # reloaded once more to match it.
            importlib.reload(config)

    def test_celsius_is_the_default(self):
        self.assertEqual(self.reload_with(None), "celsius")

    def test_fahrenheit_can_be_asked_for(self):
        self.assertEqual(self.reload_with("fahrenheit"), "fahrenheit")

    def test_a_scale_that_does_not_exist_falls_back_to_celsius(self):
        """A typo in the environment must not break every page.

        The service is asked for a scale it does not know and would
        answer with an error, so an unrecognised scale falls back to the
        one the service uses itself.
        """
        for value in ("kelvin", "Celsius", "FAHRENHEIT", "c", " "):
            with self.subTest(value=value):
                self.assertEqual(self.reload_with(value), "celsius")

    def test_the_scales_the_app_offers_are_the_two_it_knows(self):
        self.assertEqual(config.TEMPERATURE_UNITS, ("celsius", "fahrenheit"))


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
        with mock.patch.object(config, "APP_VERSION", "0.8"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))

    def test_the_commit_is_in_the_footer_when_there_is_one(self):
        with mock.patch.object(config, "APP_VERSION", "0.8"), \
                mock.patch.object(config, "APP_COMMIT", "1a2b3c4"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8 · build 1a2b3c4", self.footer(body))

    def test_no_commit_means_no_build_note(self):
        with mock.patch.object(config, "APP_VERSION", "0.8"), \
                mock.patch.object(config, "APP_COMMIT", ""):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))
        # The word "build" is only in the markup's class name, so it is the
        # separator that marks the build note that has to be absent.
        self.assertNotIn("· build", self.footer(body))

    def test_a_development_build_says_so(self):
        with mock.patch.object(config, "APP_VERSION", "dev"), \
                mock.patch.object(config, "APP_COMMIT", ""):
            body = self.client.get("/").get_data(as_text=True)
        self.assertIn("Version dev", self.footer(body))

    def test_the_version_is_on_every_page(self):
        """The forecast page, the city index and the 404 all carry it."""
        with mock.patch.object(config, "APP_VERSION", "0.8"), \
                mock.patch.object(config, "APP_COMMIT", "1a2b3c4"):
            forecast = self.client.post(
                "/", data={"city": "London"}).get_data(as_text=True)
            cities = self.client.get("/cities").get_data(as_text=True)
            missing = self.client.get("/city/nowhereville").get_data(as_text=True)
        for body in (forecast, cities, missing):
            self.assertIn("Version 0.8 · build 1a2b3c4", self.footer(body))

    def test_the_version_is_below_the_credits(self):
        """It sits under the data credits, where the eye goes last."""
        with mock.patch.object(config, "APP_VERSION", "0.8"):
            body = self.client.get("/").get_data(as_text=True)
        self.assertLess(body.index("OpenStreetMap"), body.index("Version 0.8"))


class TestWeatherCacheSetting(unittest.TestCase):
    """How long the server keeps a forecast: ten minutes unless told."""

    def reload_with(self, value):
        try:
            with mock.patch.dict(os.environ, clear=False):
                if value is None:
                    os.environ.pop("WEATHER_CACHE_SECONDS", None)
                else:
                    os.environ["WEATHER_CACHE_SECONDS"] = value
                importlib.reload(config)
                return config.WEATHER_CACHE_SECONDS
        finally:
            importlib.reload(config)

    def test_ten_minutes_is_the_default(self):
        self.assertEqual(self.reload_with(None), 600)

    def test_it_can_be_set_or_turned_off(self):
        self.assertEqual(self.reload_with("120"), 120)
        self.assertEqual(self.reload_with("0"), 0)
