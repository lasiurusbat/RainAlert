"""The rain rules: the bands, the umbrella and the alert threshold.
"""

import unittest
from unittest import mock

from rainalert import config
from rainalert.domain import rain
from tests.fixtures import AppTestCase, FakeResponse


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
        self.assertEqual(rain.severity_band(0), "low")
        self.assertEqual(rain.severity_band(29), "low")
        self.assertEqual(rain.severity_band(30), "moderate")
        self.assertEqual(rain.severity_band(60), "moderate")
        self.assertEqual(rain.severity_band(61), "high")
        self.assertEqual(rain.severity_band(100), "high")

    def test_missing_chance_gets_the_unknown_band(self):
        self.assertEqual(rain.severity_band(None), "unknown")
        self.assertEqual(rain.severity_band("not a number"), "unknown")

    def test_bands_are_configurable(self):
        with mock.patch.object(config, "SEVERITY_LOW_MAX", 10):
            with mock.patch.object(config, "SEVERITY_MODERATE_MAX", 40):
                self.assertEqual(rain.severity_band(5), "low")
                self.assertEqual(rain.severity_band(20), "moderate")
                self.assertEqual(rain.severity_band(80), "high")

    def test_umbrella_threshold(self):
        self.assertFalse(rain.needs_umbrella(49))
        self.assertTrue(rain.needs_umbrella(50))
        self.assertTrue(rain.needs_umbrella(100))
        self.assertFalse(rain.needs_umbrella(None))

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


class TestAlertThreshold(unittest.TestCase):
    """Which rain chance is worth a notification."""

    def test_without_one_the_apps_own_threshold_is_used(self):
        threshold, personal = rain.alert_threshold(None)
        self.assertEqual(threshold, config.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_an_empty_threshold_is_the_apps_own(self):
        threshold, personal = rain.alert_threshold("  ")
        self.assertEqual(threshold, config.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_the_readers_own_threshold_is_used_when_there_is_one(self):
        threshold, personal = rain.alert_threshold(40)
        self.assertEqual(threshold, 40)
        self.assertTrue(personal)

    def test_a_threshold_of_zero_is_not_taken_for_missing(self):
        """Zero is a limit like any other, not an absent one."""
        threshold, personal = rain.alert_threshold(0)
        self.assertEqual(threshold, 0)
        self.assertTrue(personal)

    def test_a_nonsense_threshold_falls_back_to_the_apps_own(self):
        threshold, personal = rain.alert_threshold("wet")
        self.assertEqual(threshold, config.UMBRELLA_THRESHOLD)
        self.assertFalse(personal)

    def test_a_threshold_is_capped_at_a_hundred(self):
        threshold, _ = rain.alert_threshold(150)
        self.assertEqual(threshold, 100)
