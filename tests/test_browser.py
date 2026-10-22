"""Browser tests for the browser-side half of RainAlert.

The saved city and the personal alert threshold live in the browser's
localStorage, so the HTTP test client cannot see them. These tests drive
headless Chrome against the real app, with the upstream services mocked at
the HTTP boundary exactly as the offline suite does, so they need no network
either.

They need Chrome and the selenium package. Neither is in the container
image, so the whole suite skips when either is missing:

    python -m unittest tests.test_browser

A skipped suite is a suite that tested nothing, and it still reports
success. That is fine on a developer machine, where a missing Chrome is
normal, but it would be a hollow gate in CI, where the suite is the only
coverage of the browser half. So CI sets RAINALERT_REQUIRE_BROWSER=1,
which turns a missing browser into a failure instead of a skip.
"""

import os
import re
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    HAS_SELENIUM = True
except ImportError:  # pragma: no cover - the suite skips without selenium
    HAS_SELENIUM = False

# When the browser is required, a missing one is an error rather than a
# skip. See the module docstring.
REQUIRE_BROWSER = os.environ.get("RAINALERT_REQUIRE_BROWSER", "").lower() in {
    "1", "true", "yes",
}

import requests
from werkzeug.serving import WSGIRequestHandler, make_server

from app import app
from rainalert.upstream import geocoding
from tests.fixtures import FakeLocation, FakeResponse


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


# A week that only just reaches the app's own threshold, so that a reader's
# own higher threshold has nothing in it. It is the case where the export
# link is on the page and the reader's own limit takes it away again.
MILD_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [60, 40, 20, 15, 5, 0, None],
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


# A dry week: nothing reaches the app's own threshold of 50, so there is
# nothing to export. The server decides that, and a reader without a
# script is told so as well.
DRY_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [40, 30, 20, 15, 5, 0, None],
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


# A week with an hour for every day of it, so the graph can be checked
# against the day the reader picks. Each day is wet at a different
# strength, so one strip can be told from another.
WEEK_HOURLY_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [20, 30, 40, 50, 60, 70, 80],
        "temperature_2m_max": [11.1, 14.0, 16.7, 12.0, 10.0, 9.0, 8.0],
        "temperature_2m_min": [8.5, 8.6, 10.3, 7.0, 6.0, 5.0, 4.0],
    },
    "hourly": {
        "time": [f"2026-10-{21 + day:02d}T{hour:02d}:00"
                 for day in range(7) for hour in range(24)],
        "precipitation_probability": [
            0 if hour < 8 else (20 + day * 10 if hour < 14 else 0)
            for day in range(7) for hour in range(24)
        ],
    },
    "current": {"time": "2026-10-21T09:00"},
    "utc_offset_seconds": 3600,
}


# A week where every hour is at a hundred. Three digits in every column
# of the value row is the widest that row ever gets, so this is the case
# the size of the numbers has to fit.
FULL_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [100, 100, 40, 15, 5, 60, None],
        "temperature_2m_max": [11.1, 14.0, 16.7, 12.0, 10.0, 9.0, 8.0],
        "temperature_2m_min": [8.5, 8.6, 10.3, 7.0, 6.0, 5.0, 4.0],
    },
    "hourly": {
        "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
        "precipitation_probability": [100] * 24,
    },
    "current": {"time": "2026-10-21T09:00"},
    "utc_offset_seconds": 3600,
}


# A forecast with rain in the next hour: the hour after the current one
# (09:00) is at 80%, so there is something worth telling the reader about.
WET_PAYLOAD = {
    "daily": {
        "time": ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
                 "2026-10-25", "2026-10-26", "2026-10-27"],
        "precipitation_probability_max": [100, 86, 40, 15, 5, 60, None],
        "temperature_2m_max": [11.1, 14.0, 16.7, 12.0, 10.0, 9.0, 8.0],
        "temperature_2m_min": [8.5, 8.6, 10.3, 7.0, 6.0, 5.0, 4.0],
    },
    "hourly": {
        "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
        "precipitation_probability": [0] * 10 + [80] + [0] * 13,
    },
    "current": {"time": "2026-10-21T09:00"},
    "utc_offset_seconds": 3600,
}


#: Every connection the recording handler has taken, whichever server
#: object it belongs to.
RECORDED_CONNECTIONS = []


class RecordingHandler(WSGIRequestHandler):
    """A handler that keeps hold of its connection.

    The offline test has to make the browser's requests fail, and a
    browser holds its connection open. Closing the listening socket is not
    enough on its own: the thread serving that connection is still there,
    and it would answer the next request as if nothing had happened.
    """

    def setup(self):
        super().setup()
        RECORDED_CONNECTIONS.append(self.connection)


class BrowserServerMixin:
    """The app on a local port, driven by a real browser.

    Every test class gets a browser and a port of its own, and so an origin
    of its own. That matters for the service worker: a worker belongs to
    the origin it was registered for, so a test that takes the app offline
    cannot disturb the tests that need it online.
    """

    #: The request handler the server uses. The offline test needs one that
    #: keeps hold of its connections.
    request_handler = None

    @classmethod
    def setUpClass(cls):
        if not HAS_SELENIUM:
            # The decorator on the test classes lets them through when the
            # browser is required, so the missing driver has to fail loudly
            # here.
            if REQUIRE_BROWSER:
                raise RuntimeError(
                    "selenium is not installed, and the browser tests are "
                    "required")
            raise unittest.SkipTest("selenium is not installed")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        try:
            cls.driver = webdriver.Chrome(options=options)
        except Exception as exc:  # noqa: BLE001 - no browser, no test
            if REQUIRE_BROWSER:
                raise RuntimeError(
                    f"Chrome is not available and the browser tests are "
                    f"required: {exc}") from exc
            raise unittest.SkipTest(f"Chrome is not available: {exc}")

        # set_window_size sets the window, and Chrome's own chrome eats most
        # of it, so the viewport is set through the protocol instead.
        cls.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": 1366, "height": 768,
            "deviceScaleFactor": 1, "mobile": False,
        })

        cls.geocode_patcher = mock.patch.object(
            geocoding.geolocator, "geocode", return_value=FakeLocation())
        cls.get_patcher = mock.patch.object(
            requests, "get", return_value=FakeResponse(FORECAST_PAYLOAD))
        cls.mock_geocode = cls.geocode_patcher.start()
        cls.mock_get = cls.get_patcher.start()

        cls.server = make_server("127.0.0.1", 0, app, threaded=True,
                                 request_handler=cls.request_handler)
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
        geocoding.get_coordinates.cache_clear()
        # The mocks are class-wide, so a test that breaks the geocoder has
        # to put it back before the next one runs.
        self.mock_geocode.return_value = FakeLocation()
        self.mock_get.return_value = FakeResponse(FORECAST_PAYLOAD)
        self.driver.get(self.base + "/")
        self.driver.execute_script(
            "window.localStorage.clear(); window.sessionStorage.clear();")

    # -- helpers ---------------------------------------------------------------

    def wait_for(self, script, timeout=10):
        """Wait until a JavaScript expression is true."""
        WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.execute_script(script))

    def wait_for_async(self, script, timeout=15):
        """Wait until a promise in the page reports something true.

        The script has to call the callback it is given, with the value it
        wants the wait to look at.
        """
        WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.execute_async_script(script))

    def wait_for_the_worker(self):
        """Wait until the service worker is registered and in charge."""
        self.wait_for_async("""
            var done = arguments[arguments.length - 1];
            navigator.serviceWorker.getRegistration('/').then(function (reg) {
                done(!!reg);
            }, function () { done(false); });
        """)
        self.wait_for_async("""
            var done = arguments[arguments.length - 1];
            done(!!navigator.serviceWorker.controller);
        """)

    def cached_urls(self):
        """The URLs the service worker has in its cache."""
        return self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            caches.keys().then(function (names) {
                return Promise.all(names.map(function (name) {
                    return caches.open(name).then(function (cache) {
                        return cache.keys().then(function (keys) {
                            return keys.map(function (key) { return key.url; });
                        });
                    });
                }));
            }).then(function (groups) {
                done([].concat.apply([], groups));
            }, function () { done([]); });
        """)


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class BrowserTestCase(BrowserServerMixin, unittest.TestCase):
    """The browser half: the saved city, the threshold, the notifications."""

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

    def marked_dates(self):
        """The dates of the days that carry the threshold marker."""
        return self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item'),
                function (row) {
                    if (!row.querySelector('.alert-marker')) { return null; }
                    var text = row.querySelector('.date').textContent;
                    var match = /(\\d{2}\\.\\d{2}\\.\\d{4})/.exec(text);
                    return match ? match[1] : null;
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
        self.assertIn("city/london", self.driver.current_url)
        self.assertIn("7-day rain chance for London", self.driver.page_source)

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
        self.assertIn("city/paris", self.driver.current_url)

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

    # -- the calendar export --------------------------------------------------

    def export_link(self):
        return self.driver.find_element(By.ID, "calendar-export")

    def export_href(self):
        return self.export_link().get_attribute("href")

    def open_the_forecast(self, payload=None):
        """Load a forecast page and wait for the list to be there."""
        if payload is not None:
            self.mock_get.return_value = FakeResponse(payload=payload)
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")

    def ical_dates(self, dates):
        """``21.10.2026`` as an iCalendar date: ``20261021``."""
        return [day[6:10] + day[3:5] + day[0:2] for day in dates]

    def exported_dates(self):
        """The dates in the file the export link points at."""
        body = self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            var href = document.getElementById('calendar-export')
                .getAttribute('href');
            fetch(href).then(function (response) {
                return response.text();
            }).then(done, function () { done(''); });
        """)
        return re.findall(r"DTSTART;VALUE=DATE:(\d{8})", body)

    def test_the_export_link_is_on_the_forecast_page(self):
        self.open_the_forecast()
        self.assertTrue(self.export_link().is_displayed())
        self.assertIn("/calendar.ics?city=London", self.export_href())

    def test_the_export_link_carries_the_readers_own_threshold(self):
        """The reader's own limit is the one that goes into the file."""
        self.open_the_forecast()
        self.set_threshold(60)
        self.wait_for("return document.getElementById('calendar-export')"
                      ".getAttribute('href').indexOf('threshold=60') !== -1;")
        self.assertIn("threshold=60", self.export_href())

    def test_the_export_link_uses_the_apps_own_threshold_without_one(self):
        """Without a threshold of the reader's own, the app's advice rules."""
        self.open_the_forecast()
        self.assertNotIn("threshold", self.export_href())

    def test_the_export_link_goes_away_when_no_day_reaches_the_threshold(self):
        """A link that would download an empty calendar is not an offer."""
        self.open_the_forecast(MILD_PAYLOAD)
        # The app's own threshold is reached, so the link is there.
        self.assertTrue(self.export_link().is_displayed())
        self.set_threshold(70)
        self.wait_for("return document.getElementById('calendar-export').hidden;")
        self.assertFalse(self.export_link().is_displayed())

    def test_the_export_link_comes_back_when_the_threshold_is_lowered(self):
        self.open_the_forecast(MILD_PAYLOAD)
        self.set_threshold(70)
        self.wait_for("return document.getElementById('calendar-export').hidden;")
        self.set_threshold(50)
        self.wait_for(
            "return !document.getElementById('calendar-export').hidden;")
        self.assertTrue(self.export_link().is_displayed())

    def test_the_export_link_answers_with_a_calendar(self):
        """The link really does produce a file with the wet days in it."""
        self.open_the_forecast()
        body = self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            var href = document.getElementById('calendar-export')
                .getAttribute('href');
            fetch(href).then(function (response) {
                return response.text();
            }).then(done, function () { done(''); });
        """)
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("DTSTART;VALUE=DATE:20261021", body)
        self.assertIn("DTSTART;VALUE=DATE:20261022", body)

    def test_clicking_the_link_downloads_the_calendar(self):
        """The link really does download a file the reader can import."""
        directory = tempfile.mkdtemp()
        self.driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": directory,
        })
        self.open_the_forecast()
        self.driver.find_element(By.ID, "calendar-export").click()

        path = None
        deadline = time.time() + 15
        while time.time() < deadline and path is None:
            names = [name for name in os.listdir(directory)
                     if name.endswith(".ics")]
            if names:
                path = os.path.join(directory, names[0])
            else:
                time.sleep(0.2)
        self.assertIsNotNone(path, "the calendar file was not downloaded")
        # The file is named after the city, from the response's header.
        self.assertEqual(os.path.basename(path), "rain-alert-london.ics")

        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("DTSTART;VALUE=DATE:20261021", content)
        # The reader is left on the page, not on a file.
        self.assertIn("city/london", self.driver.current_url)
        self.assertIn("weather-list", self.driver.page_source)

    def test_the_file_holds_exactly_the_days_the_page_marks(self):
        """The calendar and the list can never disagree about the wet days.

        The reader's own threshold is the one that goes into the file, so
        the days in it have to be the days the ▲ marks on the page.
        """
        self.open_the_forecast()
        self.set_threshold(90)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        marked = self.marked_dates()
        self.assertEqual(len(marked), 1)
        self.assertEqual(self.exported_dates(), self.ical_dates(marked))

    def test_the_file_leaves_out_the_days_below_the_threshold(self):
        """A dry day is not in the file, and a missing one is not either."""
        self.open_the_forecast()
        self.set_threshold(60)
        self.wait_for("return document.querySelector('.alert-marker') !== null;")
        exported = self.exported_dates()
        # 100, 86 and 60 per cent are at or above the threshold; 40 is
        # not, and the day the service did not report never is.
        self.assertEqual(exported, ["20261021", "20261022", "20261026"])

    def test_the_link_is_there_without_javascript(self):
        """The export is a link, so it does not need a script to work."""
        self.driver.execute_cdp_cmd(
            "Emulation.setScriptExecutionDisabled", {"value": True})
        try:
            self.driver.get(self.base + "/?city=London")
            link = self.driver.find_element(By.ID, "calendar-export")
            self.assertTrue(link.is_displayed())
            self.assertIn("/calendar.ics?city=London",
                          link.get_attribute("href"))
        finally:
            self.driver.execute_cdp_cmd(
                "Emulation.setScriptExecutionDisabled", {"value": False})

    def test_the_link_is_hidden_without_javascript_when_there_is_nothing_to_export(self):
        """The server decides, so a reader without a script is told too."""
        self.mock_get.return_value = FakeResponse(payload=DRY_PAYLOAD)
        self.driver.execute_cdp_cmd(
            "Emulation.setScriptExecutionDisabled", {"value": True})
        try:
            self.driver.get(self.base + "/?city=London")
            self.assertFalse(
                self.driver.find_element(By.ID, "calendar-export").is_displayed())
        finally:
            self.driver.execute_cdp_cmd(
                "Emulation.setScriptExecutionDisabled", {"value": False})

    # -- notifications --------------------------------------------------------

    def install_notification_stub(self, permission="default", supported=True):
        """Replace the Notification API before the page's scripts run.

        Chrome's own notifications cannot be seen from a test and the
        permission prompt cannot be answered, so the API is stubbed: the
        stub records what would have been shown, and the poll timer runs
        fast enough for a test not to wait half an hour for it.
        """
        source = """
            (function () {
                window.__notifications = [];
                if (!%s) {
                    window.Notification = undefined;
                    return;
                }
                var stub = function (title, options) {
                    window.__notifications.push({
                        title: title,
                        body: options && options.body,
                        tag: options && options.tag
                    });
                    return {close: function () {}};
                };
                stub.permission = '%s';
                stub.requestPermission = function () {
                    stub.permission = 'granted';
                    return Promise.resolve('granted');
                };
                window.Notification = stub;
                var realSetInterval = window.setInterval;
                window.setInterval = function (fn, delay) {
                    return realSetInterval(fn, Math.min(delay, 200));
                };
            })();
        """ % ("true" if supported else "false", permission)
        result = self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source})
        return result["identifier"]

    def remove_stub(self, identifier):
        self.driver.execute_cdp_cmd(
            "Page.removeScriptToEvaluateOnNewDocument",
            {"identifier": identifier})

    def notifications_shown(self):
        return self.driver.execute_script("return window.__notifications;")

    def test_the_button_stays_away_when_the_browser_cannot_notify(self):
        """A browser without notifications gets no dead button."""
        identifier = self.install_notification_stub(supported=False)
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            self.assertFalse(
                self.driver.find_element(By.ID, "notify-toggle").is_displayed())
        finally:
            self.remove_stub(identifier)

    def test_the_button_appears_when_the_browser_can_notify(self):
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            button = self.driver.find_element(By.ID, "notify-toggle")
            self.assertTrue(button.is_displayed())
            self.assertIn("Notify me", button.text)
        finally:
            self.remove_stub(identifier)

    def test_a_blocked_browser_says_so(self):
        """A browser that will not ask again cannot be asked from here."""
        identifier = self.install_notification_stub(permission="denied")
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            button = self.driver.find_element(By.ID, "notify-toggle")
            self.assertIn("Notifications blocked", button.text)
            self.assertFalse(button.is_enabled())
        finally:
            self.remove_stub(identifier)

    def test_clicking_the_button_asks_the_browser_for_permission(self):
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            self.driver.find_element(By.ID, "notify-toggle").click()
            self.wait_for(
                "return document.getElementById('notify-toggle')"
                ".textContent.indexOf('Notifications on') !== -1;")
            self.assertEqual(self.stored("rainalert.notify.on"), "1")
        finally:
            self.remove_stub(identifier)

    def test_a_notification_is_shown_when_the_forecast_says_something(self):
        self.mock_get.return_value = FakeResponse(payload=WET_PAYLOAD)
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            self.driver.find_element(By.ID, "notify-toggle").click()
            self.wait_for("return window.__notifications.length > 0;")
            notification = self.notifications_shown()[0]
            self.assertEqual(notification["title"], "Rain likely from 10:00")
            self.assertIn("80% chance of rain in London at 10:00.",
                          notification["body"])
        finally:
            self.remove_stub(identifier)

    def test_the_same_news_is_not_shown_twice(self):
        """The poll runs every 200ms here, so several checks have happened."""
        self.mock_get.return_value = FakeResponse(payload=WET_PAYLOAD)
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            self.driver.find_element(By.ID, "notify-toggle").click()
            self.wait_for("return window.__notifications.length > 0;")
            time.sleep(1)
            self.assertEqual(len(self.notifications_shown()), 1)
        finally:
            self.remove_stub(identifier)

    def test_they_can_be_switched_off_again(self):
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            button = self.driver.find_element(By.ID, "notify-toggle")
            button.click()
            self.wait_for(
                "return document.getElementById('notify-toggle')"
                ".textContent.indexOf('Notifications on') !== -1;")
            button.click()
            self.wait_for(
                "return document.getElementById('notify-toggle')"
                ".textContent.indexOf('Notify me') !== -1;")
            self.assertIsNone(self.stored("rainalert.notify.on"))
        finally:
            self.remove_stub(identifier)

    def test_nothing_is_shown_without_a_forecast_to_look_at(self):
        """A dry day has nothing to say, so nothing is shown."""
        identifier = self.install_notification_stub()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.querySelector('.weather-list') !== null;")
            self.driver.find_element(By.ID, "notify-toggle").click()
            time.sleep(1)
            self.assertEqual(self.notifications_shown(), [])
        finally:
            self.remove_stub(identifier)


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class PwaBrowserTestCase(BrowserServerMixin, unittest.TestCase):
    """The installable app: the manifest, the icons and the worker.

    These tests have a browser and a port of their own, so the service
    worker they register belongs to their own origin and cannot disturb
    the other tests.
    """

    def manifest(self):
        return self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            fetch('/manifest.json').then(function (response) {
                return response.json().then(function (data) { done(data); });
            }, function () { done(null); });
        """)

    def test_the_page_points_at_the_manifest(self):
        href = self.driver.execute_script("""
            var link = document.querySelector('link[rel="manifest"]');
            return link ? link.getAttribute('href') : null;
        """)
        self.assertEqual(href, "/manifest.json")

    def test_the_manifest_names_the_app(self):
        data = self.manifest()
        self.assertIsNotNone(data)
        self.assertEqual(data["short_name"], "Rain Alert")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")

    def test_every_icon_is_served(self):
        """An icon that is not there is an install prompt that fails."""
        results = self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            fetch('/manifest.json').then(function (response) {
                return response.json();
            }).then(function (data) {
                return Promise.all(data.icons.map(function (icon) {
                    return fetch(icon.src).then(function (response) {
                        return {
                            src: icon.src,
                            status: response.status,
                            type: response.headers.get('Content-Type')
                        };
                    });
                }));
            }).then(done, function () { done(null); });
        """)
        self.assertTrue(results)
        for icon in results:
            self.assertEqual(icon["status"], 200, icon["src"])
            self.assertEqual(icon["type"], "image/png", icon["src"])

    def test_the_worker_registers(self):
        self.wait_for_the_worker()
        scope = self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            navigator.serviceWorker.getRegistration('/').then(function (reg) {
                done(reg ? reg.scope : null);
            }, function () { done(null); });
        """)
        self.assertEqual(scope, self.base + "/")

    def test_the_worker_takes_over_the_page(self):
        """The worker has to control the page, or it does nothing."""
        self.wait_for_the_worker()
        self.assertTrue(self.driver.execute_script(
            "return !!navigator.serviceWorker.controller;"))

    def test_the_shell_is_cached(self):
        """The shell is what makes the app open without a network."""
        self.wait_for_the_worker()
        self.wait_for_async("""
            var done = arguments[arguments.length - 1];
            caches.keys().then(function (names) {
                return Promise.all(names.map(function (name) {
                    return caches.open(name).then(function (cache) {
                        return cache.keys();
                    });
                }));
            }).then(function (groups) {
                var urls = [];
                groups.forEach(function (keys) {
                    keys.forEach(function (key) { urls.push(key.url); });
                });
                done(urls.length > 0);
            }, function () { done(false); });
        """)
        cached = self.cached_urls()
        for path in ("/static/style.css", "/static/app.js",
                     "/static/favicon.svg", "/static/offline.html",
                     "/static/icon-192.png", "/static/icon-512.png"):
            self.assertIn(self.base + path, cached)

    def test_the_forecast_page_is_not_cached(self):
        """The page holds the forecast, and a cached forecast is a lie."""
        self.wait_for_the_worker()
        self.wait_for_async("""
            var done = arguments[arguments.length - 1];
            caches.keys().then(function (names) {
                return Promise.all(names.map(function (name) {
                    return caches.open(name).then(function (cache) {
                        return cache.keys();
                    });
                }));
            }).then(function (groups) {
                var urls = [];
                groups.forEach(function (keys) {
                    keys.forEach(function (key) { urls.push(key.url); });
                });
                done(urls.length > 0);
            }, function () { done(false); });
        """)
        for url in self.cached_urls():
            # Neither the query string nor the city's own address may be
            # in the cache: both of them show the forecast.
            self.assertNotIn(url, self.base + "/city/london")
            self.assertFalse(url.endswith("/city/london"))
            self.assertFalse(url.endswith("/?city=London"))

    def test_the_page_still_works_with_the_worker_in_charge(self):
        """The worker must not get in the way of the app."""
        self.wait_for_the_worker()
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.assertIn("7-day rain chance for London", self.driver.page_source)

    def test_the_export_downloads_with_the_worker_in_charge(self):
        """The worker must not get in the way of the export either."""
        self.wait_for_the_worker()
        directory = tempfile.mkdtemp()
        self.driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": directory,
        })
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.driver.find_element(By.ID, "calendar-export").click()

        path = None
        deadline = time.time() + 15
        while time.time() < deadline and path is None:
            names = [name for name in os.listdir(directory)
                     if name.endswith(".ics")]
            if names:
                path = os.path.join(directory, names[0])
            else:
                time.sleep(0.2)
        self.assertIsNotNone(path, "the calendar file was not downloaded")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("BEGIN:VCALENDAR", content)


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class OfflineBrowserTestCase(BrowserServerMixin, unittest.TestCase):
    """The app with the server taken away.

    The service worker is the only thing that can answer a navigation when
    there is no server, so this is where the offline page is proved. It has
    a server of its own, because it takes that server away.
    """

    request_handler = RecordingHandler

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        RECORDED_CONNECTIONS.clear()

    @classmethod
    def take_the_server_away(cls):
        """Stop the server, and drop the connections it is holding.

        Three things have to go, in this order. The accept loop first, so
        that no new connection is taken on. Then the listening socket, so
        that a new connection is refused instead of being left hanging in
        the backlog. Then the connections the browser is holding open, or
        the thread serving one of them would answer the next request as if
        nothing had happened.

        It is a class method because the server is a class attribute:
        unittest builds a fresh test instance for every test, so a server
        kept on the instance would be forgotten by the next test.
        """
        cls.server.shutdown()
        cls.server.socket.close()
        for connection in list(RECORDED_CONNECTIONS):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        RECORDED_CONNECTIONS.clear()
        cls.server.server_close()

    @classmethod
    def bring_the_server_back(cls):
        cls.server = make_server(
            "127.0.0.1", cls.port, app, threaded=True,
            request_handler=cls.request_handler)
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    def test_the_offline_page_is_shown_when_the_server_is_gone(self):
        self.wait_for_the_worker()
        self.take_the_server_away()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.title === 'Offline - Rain Alert';")
            body = self.driver.execute_script(
                "return document.body.innerText;")
            self.assertIn("You are offline", body)
            # It is still Rain Alert, and not a browser error page.
            self.assertIn("Rain Alert", body)
            # The stylesheet came from the cache, so the page looks like
            # the app rather than like a wall of unstyled text: the panel
            # is the night's dark plate.
            self.assertEqual(
                self.driver.execute_script(
                    "return getComputedStyle("
                    "document.querySelector('.container')).backgroundColor;"),
                "rgb(13, 18, 22)")
        finally:
            self.bring_the_server_back()

    def test_the_offline_page_shows_no_forecast(self):
        """There is nothing to show, and a stale chance is worse than none."""
        self.wait_for_the_worker()
        self.take_the_server_away()
        try:
            self.driver.get(self.base + "/?city=London")
            self.wait_for("return document.title === 'Offline - Rain Alert';")
            self.assertIsNone(self.driver.execute_script(
                "return document.querySelector('.weather-list');"))
        finally:
            self.bring_the_server_back()

    def test_the_alert_poll_is_not_answered_from_a_cache(self):
        """A cached alert would be yesterday's rain."""
        self.wait_for_the_worker()
        self.take_the_server_away()
        try:
            result = self.driver.execute_async_script("""
                var done = arguments[arguments.length - 1];
                fetch('/api/alert?city=London').then(
                    function (response) { done('answered ' + response.status); },
                    function () { done('failed'); });
            """)
            self.assertEqual(result, "failed")
        finally:
            self.bring_the_server_back()

    def test_the_app_works_again_when_the_server_comes_back(self):
        """The offline page is a fallback, not a new home."""
        self.wait_for_the_worker()
        self.take_the_server_away()
        self.bring_the_server_back()
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.assertIn("7-day rain chance for London", self.driver.page_source)

    def test_the_export_is_not_answered_with_the_offline_page(self):
        """An offline page is a page, and it must not stand in for a file.

        The worker answers a navigation with the offline page when there
        is no network, so the export has to be let through: a reader must
        never end up with a saved file that pretends to be a calendar.
        """
        self.wait_for_the_worker()
        self.take_the_server_away()
        try:
            try:
                self.driver.get(self.base + "/calendar.ics?city=London")
                body = self.driver.execute_script(
                    "return document.body.innerText || '';")
            except WebDriverException:
                # The browser's own error page: no server, no file.
                body = ""
            self.assertNotIn("You are offline", body)
        finally:
            self.bring_the_server_back()


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class NightStreetLayoutTestCase(BrowserServerMixin, unittest.TestCase):
    """The night street layout, measured in a real browser.

    The design moved the answer to the top and the week to seven columns
    of figures, so the things that can go wrong are measured rather than
    assumed: the page has to fit its window, the columns have to be
    columns, and the numbers have to sit over their own bars.
    """

    def open_the_forecast(self, width=1366, height=768, payload=None):
        self.set_viewport(width, height)
        if payload is not None:
            self.mock_get.return_value = FakeResponse(payload=payload)
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        # The script turns each column into a button, so the page is only
        # finished when the buttons are there.
        self.wait_for("return document.querySelector('.day-pick') !== null;")
        self.wait_for("return document.fonts.status === 'loaded';")

    def set_viewport(self, width, height):
        """Set the viewport exactly, chrome and all."""
        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False,
        })

    def overflow(self):
        return self.driver.execute_script(
            "return document.documentElement.scrollHeight - "
            "document.documentElement.clientHeight;")

    def test_the_forecast_page_fits_a_standard_window(self):
        """The card is at its vertical limit, so the page has to fit a
        768px window with no scrollbar."""
        self.open_the_forecast()
        self.assertEqual(self.overflow(), 0)

    def test_the_page_does_not_scroll_sideways(self):
        self.open_the_forecast()
        sideways = self.driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;")
        self.assertEqual(sideways, 0)

    def test_the_narrow_page_does_not_scroll_sideways(self):
        self.open_the_forecast(width=400, height=780)
        sideways = self.driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;")
        self.assertEqual(sideways, 0)

    def test_the_week_is_seven_columns_on_one_row(self):
        """The week is a row of columns, not a stack of rows."""
        self.open_the_forecast()
        boxes = self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item'),
                function (row) {
                    var r = row.getBoundingClientRect();
                    return {top: Math.round(r.top),
                            left: Math.round(r.left),
                            width: Math.round(r.width)};
                });
        """)
        self.assertEqual(len(boxes), 7)
        self.assertEqual(len({row["top"] for row in boxes}), 1)
        self.assertEqual(len({row["left"] for row in boxes}), 7)

    def test_the_columns_are_the_same_width(self):
        self.open_the_forecast()
        widths = self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item'),
                function (row) {
                    return Math.round(row.getBoundingClientRect().width);
                });
        """)
        self.assertEqual(len(set(widths)), 1)

    def test_every_number_sits_over_its_own_bar(self):
        """The value row and the strip are the same row of cells."""
        self.open_the_forecast()
        offsets = self.driver.execute_script("""
            var values = document.querySelectorAll('.hour-value');
            var bars = document.querySelectorAll('.hour .hour-bar');
            var out = [];
            for (var i = 0; i < values.length && i < bars.length; i++) {
                var v = values[i].getBoundingClientRect();
                var b = bars[i].getBoundingClientRect();
                out.push(Math.round(v.left + v.width / 2 -
                                   (b.left + b.width / 2)));
            }
            return out;
        """)
        self.assertEqual(len(offsets), 24)
        for offset in offsets:
            self.assertLessEqual(abs(offset), 2, offset)

    def test_the_widest_numbers_still_fit_the_row(self):
        """Twenty-four hours of three digits have to fit the card, and the
        numbers of two neighbouring columns must not touch.

        The numbers of the row are the one thing in the chart that cannot
        be made smaller when it does not fit: twenty-four of them are
        written across the panel, so the size of the type is bounded by
        the width of a column.
        """
        for width in (1366, 560, 400):
            self.open_the_forecast(width=width, height=780,
                                   payload=FULL_PAYLOAD)
            report = self.driver.execute_script("""
                var strip = document.querySelector('.day-strip.is-active');
                var cells = Array.prototype.slice.call(
                    strip.querySelectorAll('.hour-value'));
                var texts = cells.map(function (cell) {
                    var node = Array.prototype.filter.call(
                        cell.childNodes, function (n) {
                            return n.nodeType === 3 && n.textContent.trim();
                        })[0];
                    if (!node) { return null; }
                    var range = document.createRange();
                    range.selectNodeContents(node);
                    var r = range.getBoundingClientRect();
                    return {left: r.left, right: r.right,
                            text: node.textContent.trim()};
                }).filter(Boolean);
                var gap = Infinity;
                for (var i = 1; i < texts.length; i++) {
                    gap = Math.min(gap, texts[i].left - texts[i - 1].right);
                }
                var card = document.querySelector('.hourly');
                var style = getComputedStyle(card);
                var box = card.getBoundingClientRect();
                return {
                    gap: gap,
                    count: texts.length,
                    widest: Math.max.apply(null, texts.map(function (t) {
                        return t.right - t.left;
                    })),
                    rowRight: strip.querySelector('.hourly-values')
                            .getBoundingClientRect().right,
                    cardRight: box.right - parseFloat(style.paddingRight) -
                               parseFloat(style.borderRightWidth)
                };
            """)
            self.assertEqual(report["count"], 24, report)
            self.assertGreaterEqual(report["gap"], 1, report)
            self.assertLessEqual(report["rowRight"], report["cardRight"] + 0.5,
                                 report)

    def test_the_panel_is_dark(self):
        """The page is a night panel over the photograph."""
        self.open_the_forecast()
        background = self.driver.execute_script(
            "return getComputedStyle(document.querySelector('.container'))"
            ".backgroundColor;")
        self.assertEqual(background, "rgb(13, 18, 22)")

    def test_the_type_is_the_self_hosted_face(self):
        """No third party is asked for a font, so the family that comes
        back has to be the one that was loaded."""
        self.open_the_forecast()
        family = self.driver.execute_script(
            "return getComputedStyle(document.querySelector('.city-name'))"
            ".fontFamily;")
        self.assertIn("Archivo", family)

    def test_the_umbrella_is_the_amber_text_glyph(self):
        """The pictograph, not a colour emoji."""
        self.open_the_forecast()
        colour = self.driver.execute_script("""
            var mark = document.querySelector('.umbrella');
            return mark ? getComputedStyle(mark).color : '';
        """)
        self.assertEqual(colour, "rgb(233, 169, 60)")

    def test_the_export_link_sits_on_the_caption_line(self):
        """The link and "7-day rain chance" are one line, not two rows.

        The two are set at slightly different sizes, so their boxes are not
        the same height. What has to be the same is the line they sit on,
        which is where the text stands on the page - so that is what is
        measured.
        """
        self.open_the_forecast()
        lines = self.driver.execute_script("""
            function baseline(el) {
                // A box with no height, standing on the text's baseline.
                var marker = document.createElement('span');
                marker.style.display = 'inline-block';
                marker.style.width = '0';
                marker.style.height = '0';
                marker.style.verticalAlign = 'baseline';
                el.appendChild(marker);
                var y = marker.getBoundingClientRect().top;
                marker.remove();
                return y;
            }
            return {
                caption: baseline(document.querySelector('.result-caption')),
                link: baseline(document.querySelector('.calendar-text')),
            };
        """)
        self.assertLessEqual(abs(lines["caption"] - lines["link"]), 1)

    def test_the_export_icon_does_not_climb_above_the_caption(self):
        """The icon is part of the caption's line, not of the city's name."""
        self.open_the_forecast()
        tops = self.driver.execute_script("""
            return {
                city: document.querySelector('.city-name')
                    .getBoundingClientRect().bottom,
                icon: document.querySelector('.calendar-icon')
                    .getBoundingClientRect().top,
                caption: document.querySelector('.result-caption')
                    .getBoundingClientRect().top,
            };
        """)
        self.assertGreaterEqual(tops["icon"], tops["caption"] - 1)
        self.assertGreater(tops["icon"], tops["city"])


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class DayPickerTestCase(BrowserServerMixin, unittest.TestCase):
    """Picking a day out of the week.

    The week is seven columns, and a column can be picked. The detail of
    the picked day is in the panel above the week, so the two have to
    agree, and the page has to stay the same size when the day changes.
    """

    def open_the_forecast(self, width=1366, height=768, payload=None):
        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False,
        })
        if payload is not None:
            self.mock_get.return_value = FakeResponse(payload=payload)
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.day-pick') !== null;")
        self.wait_for("return document.fonts.status === 'loaded';")

    def active_panel(self):
        return self.driver.execute_script(
            "var panel = document.querySelector('.day-panel.is-active');"
            "return panel ? panel.innerText.replace(/\\s+/g, ' ') : '';")

    def active_summary(self):
        """The sentence under the graph of the day that is showing."""
        return self.driver.execute_script(
            "var strip = document.querySelector('.day-strip.is-active');"
            "var line = strip && strip.querySelector('.hourly-summary');"
            "return line ? line.innerText.trim() : '';")

    def active_values(self):
        """The numbers written over the bars of the day that is showing."""
        return self.driver.execute_script(
            "var strip = document.querySelector('.day-strip.is-active');"
            "var row = strip && strip.querySelector('.hourly-values');"
            "return row ? row.innerText.replace(/\\s+/g, ' ') : '';")

    def click_day(self, index):
        self.driver.execute_script(
            "document.querySelectorAll('.weather-item .day-pick')"
            "[arguments[0]].click();", index)

    def test_every_column_is_a_button(self):
        """The whole column is the target, and it points at the panel it
        shows."""
        self.open_the_forecast()
        panels = self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item .day-pick'),
                function (button) {
                    var panel = document.getElementById(
                        button.getAttribute('aria-controls'));
                    return panel ? panel.id : '';
                });
        """)
        self.assertEqual(len(panels), 7)
        self.assertEqual(len(set(panels)), 7)

    def test_the_day_chosen_is_the_one_that_shows(self):
        self.open_the_forecast()
        before = self.active_panel()
        self.click_day(2)
        after = self.active_panel()
        self.assertNotEqual(before, after)
        self.assertIn("23.10", after)
        self.assertIn("40%", after)

    def test_only_one_day_is_marked_as_picked(self):
        self.open_the_forecast()
        self.click_day(4)
        marked = self.driver.execute_script(
            "return document.querySelectorAll('.weather-item.is-selected')"
            ".length;")
        self.assertEqual(marked, 1)

    def test_the_picked_day_is_the_current_one_for_a_screen_reader(self):
        self.open_the_forecast()
        self.click_day(3)
        current = self.driver.execute_script("""
            return Array.prototype.map.call(
                document.querySelectorAll('.weather-item .day-pick'),
                function (button) {
                    return button.getAttribute('aria-current');
                });
        """)
        self.assertEqual(current.count("true"), 1)
        self.assertEqual(current[3], "true")

    def test_the_arrow_keys_move_between_the_days(self):
        self.open_the_forecast()
        buttons = self.driver.find_elements(
            By.CSS_SELECTOR, ".weather-item .day-pick")
        buttons[0].send_keys(Keys.ARROW_RIGHT)
        self.assertIn("22.10", self.active_panel())
        buttons[1].send_keys(Keys.ARROW_RIGHT)
        self.assertIn("23.10", self.active_panel())

    def test_the_page_does_not_grow_when_the_day_changes(self):
        """The panels sit in one cell, so the week never moves."""
        self.open_the_forecast()
        before = self.driver.execute_script(
            "return document.querySelector('.weather-list')"
            ".getBoundingClientRect().top;")
        self.click_day(5)
        after = self.driver.execute_script(
            "return document.querySelector('.weather-list')"
            ".getBoundingClientRect().top;")
        self.assertEqual(round(before), round(after))

    def test_the_page_still_fits_a_standard_window(self):
        self.open_the_forecast()
        overflow = self.driver.execute_script(
            "return document.documentElement.scrollHeight - "
            "document.documentElement.clientHeight;")
        self.assertEqual(overflow, 0)

    def test_the_page_does_not_scroll_sideways(self):
        self.open_the_forecast(width=400, height=780)
        sideways = self.driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;")
        self.assertEqual(sideways, 0)

    def test_the_graph_shows_the_day_that_is_picked(self):
        """The strip is the graph of the day the reader picked, so it has
        to show that day's hours and not today's."""
        self.open_the_forecast(payload=WEEK_HOURLY_PAYLOAD)
        self.click_day(5)
        self.assertIn("up to 70%", self.active_summary())
        self.assertIn("70", self.active_values())
        self.assertNotIn("20", self.active_values())

    def test_the_title_of_the_graph_names_the_day(self):
        self.open_the_forecast(payload=WEEK_HOURLY_PAYLOAD)
        self.click_day(2)
        title = self.driver.execute_script(
            "return document.querySelector('.hourly-title').textContent;")
        self.assertEqual(title, "Friday, hour by hour")

    def test_only_one_graph_shows(self):
        self.open_the_forecast(payload=WEEK_HOURLY_PAYLOAD)
        self.click_day(3)
        showing = self.driver.execute_script(
            "return document.querySelectorAll('.day-strip.is-active').length;")
        self.assertEqual(showing, 1)

    def test_the_graph_does_not_move_when_the_day_changes(self):
        """The strips share one cell of one grid, so the graph stays where
        it is and the week below it never moves."""
        self.open_the_forecast(payload=WEEK_HOURLY_PAYLOAD)
        before = self.driver.execute_script(
            "return document.querySelector('.day-strip.is-active "
            ".hourly-values').getBoundingClientRect().top;")
        self.click_day(5)
        after = self.driver.execute_script(
            "return document.querySelector('.day-strip.is-active "
            ".hourly-values').getBoundingClientRect().top;")
        self.assertEqual(round(before), round(after))

    def test_the_page_still_fits_a_standard_window_with_a_full_week(self):
        """A week of graphs is the real page, and it still has to fit."""
        self.open_the_forecast(payload=WEEK_HOURLY_PAYLOAD)
        overflow = self.driver.execute_script(
            "return document.documentElement.scrollHeight - "
            "document.documentElement.clientHeight;")
        self.assertEqual(overflow, 0)

    def test_the_narrow_page_still_fits_a_full_week(self):
        self.open_the_forecast(width=400, height=780,
                               payload=WEEK_HOURLY_PAYLOAD)
        sideways = self.driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;")
        self.assertEqual(sideways, 0)


@unittest.skipUnless(
    HAS_SELENIUM or REQUIRE_BROWSER,
    "selenium is not installed")
class ReleaseNotesBrowserTestCase(BrowserServerMixin, unittest.TestCase):
    """The release notes link, followed in a real browser.

    The link sits in the footer, under the credits, and it is a plain
    link: it has to work without a script, and the page it opens has to
    look like the rest of the site.
    """

    def open_the_forecast(self, width=1366, height=768):
        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False,
        })
        self.driver.get(self.base + "/?city=London")
        self.wait_for("return document.querySelector('.weather-list') !== null;")
        self.wait_for("return document.fonts.status === 'loaded';")

    def test_the_link_is_in_the_footer(self):
        self.open_the_forecast()
        link = self.driver.execute_script(
            "var l = document.querySelector('.copyright .release-link');"
            "return l ? {text: l.innerText.trim(),"
            "            href: l.getAttribute('href'),"
            "            visible: l.getBoundingClientRect().height > 0}"
            "       : null;")
        self.assertIsNotNone(link)
        self.assertEqual(link["text"], "Release notes")
        self.assertEqual(link["href"], "/release-notes")
        self.assertTrue(link["visible"])

    def test_the_link_opens_the_notes(self):
        """Clicking it lands on the page, with the panel and the notes."""
        self.open_the_forecast()
        self.driver.find_element(By.CSS_SELECTOR, ".release-link").click()
        self.wait_for("return document.querySelector('.releases') !== null;")
        self.assertIn("/release-notes", self.driver.current_url)
        self.assertEqual(self.driver.title, "Release notes - Rain Alert")

    def test_the_notes_page_has_the_panel_over_the_photograph(self):
        """The same frame as every other page, not a bare document.

        The panel is the dark plate of the night street, and the page
        behind it is transparent, so the photograph shows through.
        """
        self.driver.get(self.base + "/release-notes")
        self.wait_for("return document.querySelector('.releases') !== null;")
        self.wait_for("return document.fonts.status === 'loaded';")
        panel = self.driver.execute_script(
            "var p = document.querySelector('.container');"
            "return p ? {background: getComputedStyle(p).backgroundColor,"
            "            radius: getComputedStyle(p).borderRadius,"
            "            body: getComputedStyle(document.body)"
            "                     .backgroundColor}"
            "       : null;")
        self.assertIsNotNone(panel)
        # The asphalt plate, not a white card and not nothing at all.
        self.assertEqual(panel["background"], "rgb(13, 18, 22)")
        self.assertNotEqual(panel["radius"], "0px")
        # The photograph is behind the page, so the page itself is clear.
        self.assertEqual(panel["body"], "rgba(0, 0, 0, 0)")

    def test_the_notes_page_does_not_scroll_sideways(self):
        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": 400, "height": 780,
            "deviceScaleFactor": 1, "mobile": False,
        })
        self.driver.get(self.base + "/release-notes")
        self.wait_for("return document.querySelector('.releases') !== null;")
        sideways = self.driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;")
        self.assertEqual(sideways, 0)

    def test_the_way_back_is_on_the_notes_page(self):
        """The reader is never left at the end of the notes with nowhere
        to go: there is a link back into the app, in the panel."""
        self.driver.get(self.base + "/release-notes")
        self.wait_for("return document.querySelector('.notes-back') !== null;")
        back = self.driver.execute_script(
            "var b = document.querySelector('.notes-back a');"
            "return b ? {text: b.innerText.trim(),"
            "            href: b.getAttribute('href'),"
            "            visible: b.getBoundingClientRect().height > 0}"
            "       : null;")
        self.assertIsNotNone(back)
        self.assertEqual(back["text"], "Back to Rain Alert")
        self.assertEqual(back["href"], "/")
        self.assertTrue(back["visible"])

    def test_the_way_back_leads_to_the_start_page(self):
        self.driver.get(self.base + "/release-notes")
        self.wait_for("return document.querySelector('.notes-back a') !== null;")
        self.driver.find_element(By.CSS_SELECTOR, ".notes-back a").click()
        self.wait_for("return document.querySelector('.page-title') !== null;")
        self.assertEqual(self.driver.current_url.rstrip("/"),
                         self.base.rstrip("/"))
        self.assertEqual(self.driver.title, "Rain Alert - 7-day rain chance for any city")


if __name__ == "__main__":
    unittest.main(verbosity=2)
