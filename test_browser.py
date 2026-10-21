"""Browser tests for the browser-side half of RainAlert.

The saved city and the personal alert threshold live in the browser's
localStorage, so the HTTP test client cannot see them. These tests drive
headless Chrome against the real app, with the upstream services mocked at
the HTTP boundary exactly as test_app.py does, so they need no network
either.

They need Chrome and the selenium package. Neither is in the container
image, so the whole suite skips when either is missing:

    python -m unittest test_browser
"""

import threading
import unittest
from unittest import mock

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    HAS_SELENIUM = True
except ImportError:  # pragma: no cover - the suite skips without selenium
    HAS_SELENIUM = False

from werkzeug.serving import make_server

import app as rainalert


# A week with a wet start, a dry middle and one day the service reports no
# value for at all. The unreported day is the interesting one: it must never
# be counted as dry, and never as above a threshold either.
FORECAST_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [100, 86, 40, 15, 5, 60, None],
        "temperature_2m_max": [11.1, 14.0, 16.7, 12.0, 10.0, 9.0, 8.0],
        "temperature_2m_min": [8.5, 8.6, 10.3, 7.0, 6.0, 5.0, 4.0],
    },
    "hourly": {
        "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
        "precipitation_probability": [0] * 24,
    },
    "current": {"time": "2026-10-21T09:00"},
    "utc_offset_seconds": 3600,
}


class FakeLocation:
    latitude = 51.5074
    longitude = -0.1278
    raw = {"display_name": "London, England, UK"}


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else FORECAST_PAYLOAD
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


@unittest.skipUnless(HAS_SELENIUM, "selenium is not installed")
class BrowserTestCase(unittest.TestCase):
    """The app on a local port, driven by a real browser."""

    @classmethod
    def setUpClass(cls):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        try:
            cls.driver = webdriver.Chrome(options=options)
        except Exception as exc:  # noqa: BLE001 - no browser, no test
            raise unittest.SkipTest(f"Chrome is not available: {exc}")

        # set_window_size sets the window, and Chrome's own chrome eats most
        # of it, so the viewport is set through the protocol instead.
        cls.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": 1366, "height": 768,
            "deviceScaleFactor": 1, "mobile": False,
        })

        cls.geocode_patcher = mock.patch.object(
            rainalert.geolocator, "geocode", return_value=FakeLocation())
        cls.get_patcher = mock.patch.object(
            rainalert.requests, "get", return_value=FakeResponse())
        cls.mock_geocode = cls.geocode_patcher.start()
        cls.mock_get = cls.get_patcher.start()

        cls.server = make_server("127.0.0.1", 0, rainalert.app, threaded=True)
        cls.port = cls.server.server_port
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.geocode_patcher.stop()
        cls.get_patcher.stop()
        cls.driver.quit()

    def setUp(self):
        rainalert.get_coordinates.cache_clear()
        # The mocks are class-wide, so a test that breaks the geocoder has
        # to put it back before the next one runs.
        self.mock_geocode.return_value = FakeLocation()
        self.mock_get.return_value = FakeResponse()
        self.driver.get(self.base + "/")
        self.driver.execute_script(
            "window.localStorage.clear(); window.sessionStorage.clear();")

    # -- helpers ---------------------------------------------------------------

    def wait_for(self, script, timeout=10):
        """Wait until a JavaScript expression is true."""
        WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.execute_script(script))

    def marked_chances(self):
        """The rain chance of every day that carries the threshold marker."""
        return self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item'),
                function (row) {
                    if (!row.querySelector('.alert-marker')) { return null; }
                    return parseInt(row.getAttribute('data-chance'), 10);
                }).filter(function (value) { return value !== null; });
        """)

    def set_threshold(self, value):
        """Type a threshold into the field, the way a reader would."""
        self.driver.execute_script("""
            var input = document.getElementById('alert-threshold');
            input.value = arguments[0];
            input.dispatchEvent(new Event('input', {bubbles: true}));
        """, str(value))

    def stored(self, key):
        return self.driver.execute_script(
            "return window.localStorage.getItem(arguments[0]);", key)

    # -- the preferences row ----------------------------------------------------

    def test_the_preferences_row_appears_once_the_script_has_run(self):
        display = self.driver.execute_script(
            "return getComputedStyle(document.querySelector('.prefs')).display;")
        self.assertEqual(display, "flex")

    def test_the_controls_are_reachable(self):
        self.assertTrue(self.driver.find_element(By.ID, "remember-city").is_displayed())
        self.assertTrue(self.driver.find_element(By.ID, "alert-threshold").is_displayed())

    # -- remembering a city -----------------------------------------------------

    def test_the_start_page_loads_the_remembered_city(self):
        """No retyping: the page checks the saved city on load."""
        self.driver.execute_script(
            "window.localStorage.setItem('rainalert.city', 'London');")
        self.driver.get(self.base + "/")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.assertIn("city=London", self.driver.current_url)
        self.assertIn("Forecast for London", self.driver.page_source)

    def test_the_remember_box_shows_that_a_city_is_saved(self):
        self.driver.execute_script(
            "window.localStorage.setItem('rainalert.city', 'London');")
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.getElementById('remember-city').checked;")
        self.assertIn("Remember London",
                      self.driver.find_element(By.ID, "remember-label").text)

    def test_a_search_that_worked_is_remembered(self):
        self.driver.find_element(By.NAME, "city").send_keys("London")
        self.driver.find_element(By.ID, "remember-city").click()
        self.driver.find_element(By.CSS_SELECTOR, "form button").click()
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.wait_for(
            "return window.localStorage.getItem('rainalert.city') === 'London';")

    def test_a_search_that_failed_is_not_remembered(self):
        """A city that does not exist is not worth remembering."""
        self.mock_geocode.return_value = None
        self.driver.find_element(By.NAME, "city").send_keys("Nowhereville")
        self.driver.find_element(By.ID, "remember-city").click()
        self.driver.find_element(By.CSS_SELECTOR, "form button").click()
        self.wait_for("return document.querySelector('.error') !== null;")
        self.assertIsNone(self.stored("rainalert.city"))

    def test_a_failed_search_keeps_the_city_that_was_saved(self):
        self.driver.execute_script(
            "window.localStorage.setItem('rainalert.city', 'London');")
        self.mock_geocode.return_value = None
        self.driver.find_element(By.NAME, "city").send_keys("Nowhereville")
        self.driver.find_element(By.ID, "remember-city").click()
        self.driver.find_element(By.CSS_SELECTOR, "form button").click()
        self.wait_for("return document.querySelector('.error') !== null;")
        self.assertEqual(self.stored("rainalert.city"), "London")

    def test_unticking_the_box_forgets_the_city(self):
        self.driver.execute_script(
            "window.localStorage.setItem('rainalert.city', 'London');")
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.getElementById('remember-city').checked;")
        self.driver.find_element(By.ID, "remember-city").click()
        self.assertIsNone(self.stored("rainalert.city"))

    def test_a_remembered_city_is_not_loaded_twice(self):
        """A page that already shows a forecast is left alone."""
        self.driver.execute_script(
            "window.localStorage.setItem('rainalert.city', 'London');")
        self.driver.get(self.base + "/?city=Paris")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.assertIn("city=Paris", self.driver.current_url)

    # -- the personal threshold -------------------------------------------------

    def test_the_threshold_marks_the_days_at_or_above_it(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(60)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        self.assertEqual(self.marked_chances(), [100, 86, 60])

    def test_a_day_below_the_threshold_is_not_marked(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(90)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        self.assertEqual(self.marked_chances(), [100])

    def test_an_unreported_day_is_never_marked(self):
        """A missing value is not a 0% chance, and not a wet one either."""
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(0)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        self.assertNotIn(None, self.marked_chances())
        self.assertEqual(len(self.marked_chances()), 6)

    def test_clearing_the_threshold_removes_the_marks(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(60)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        self.set_threshold("")
        self.wait_for("return document.querySelector('.alert-marker') === null;")
        self.assertIsNone(self.stored("rainalert.threshold"))

    def test_the_threshold_is_remembered(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(75)
        self.wait_for("return window.localStorage.getItem('rainalert.threshold');")
        self.driver.get(self.base + "/?city=London")
        self.wait_for(
            "return document.getElementById('alert-threshold').value === '75';")
        self.assertEqual(self.marked_chances(), [100, 86])

    def test_the_threshold_is_capped_at_a_hundred(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(150)
        self.wait_for(
            "return window.localStorage.getItem('rainalert.threshold') === '100';")
        # A hundred per cent is the top of the scale, so only the wettest
        # day clears it.
        self.assertEqual(self.marked_chances(), [100])

    def test_the_status_counts_the_days_above_the_threshold(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(60)
        self.wait_for(
            "return document.getElementById('alert-status').textContent !== '';")
        status = self.driver.find_element(By.ID, "alert-status").text
        self.assertIn("3 days above 60%", status)
        # The day the service did not report is counted as unknown, not dry.
        self.assertIn("1 day unknown", status)

    def test_the_marker_names_the_threshold_for_a_screen_reader(self):
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.set_threshold(60)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        spoken = self.driver.execute_script("""
            var marker = document.querySelector('.weather-item .alert-marker');
            var row = marker.closest('.weather-item');
            return row.querySelector('.alert-marker-text').textContent;
        """)
        self.assertEqual(spoken, "Above your 60% alert threshold.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
