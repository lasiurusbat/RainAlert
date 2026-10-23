"""The forecast page, the city index and the release notes.
"""

import re
from datetime import date
from unittest import mock

from markupsafe import escape

from rainalert import config
from rainalert.data import releases
from rainalert.present.labels import format_numeric_date
from tests.fixtures import (AppTestCase, FakeLocation, FakeResponse,
                            hourly_payload)


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
        for release in releases.RELEASES:
            self.assertIn(release["version"], body)
            self.assertIn(release["name"], body)

    def test_the_releases_are_newest_first(self):
        versions = [release["version"] for release in releases.RELEASES]
        self.assertEqual(versions, sorted(versions, reverse=True))

    def test_every_release_has_a_real_date(self):
        for release in releases.RELEASES:
            date.fromisoformat(release["date"])

    def test_the_dates_never_run_backwards(self):
        """Newest first, so no entry is dated before the one under it."""
        dates = [release["date"] for release in releases.RELEASES]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_the_page_carries_every_date(self):
        """The machine-readable date and the words the site always uses."""
        body = self.client.get("/release-notes").get_data(as_text=True)
        for release in releases.RELEASES:
            self.assertIn(f'<time class="release-date" '
                          f'datetime="{release["date"]}">'
                          f'{format_numeric_date(release["date"])}</time>', body)

    def test_the_page_carries_every_feature(self):
        """A feature is a title and a paragraph, and both are on the page.

        The text is escaped on the way out, so an apostrophe in a feature
        arrives as an entity. The page is compared the way a browser sees
        it, which is the way it has to be right.
        """
        body = self.client.get("/release-notes").get_data(as_text=True)
        for release in releases.RELEASES:
            for feature in release["features"]:
                self.assertIn(escape(feature["title"]), body)
                self.assertIn(escape(feature["text"]), body)

    def test_every_release_says_something(self):
        """A release with no features is a heading and nothing else."""
        for release in releases.RELEASES:
            self.assertTrue(release["features"], release["version"])
            for feature in release["features"]:
                self.assertTrue(feature["title"].strip(), release["version"])
                self.assertTrue(feature["text"].strip(), release["version"])

    def test_the_page_says_which_build_is_answering(self):
        """The notes and the footer agree about the running build."""
        with mock.patch.object(config, "APP_VERSION", "0.8"):
            body = self.client.get("/release-notes").get_data(as_text=True)
        self.assertIn("Version 0.8", self.footer(body))
        self.assertIn('<span class="notes-version">0.8</span>', body)

    # -- the way back -----------------------------------------------------------

    def test_there_is_a_way_back_into_the_app(self):
        """The reader is never left at the end of the notes with nowhere
        to go."""
        body = self.client.get("/release-notes").get_data(as_text=True)
        self.assertIn('class="notes-back"', body)
        self.assertIn('<a href="/">Back to Rain Alert</a>', body)

    def test_the_way_back_is_inside_the_panel(self):
        """Still in the box, so the page does not end in a stray link
        floating on the photograph."""
        body = self.client.get("/release-notes").get_data(as_text=True)
        back = body.index('class="notes-back"')
        panel = body.index('class="container container-wide"')
        self.assertLess(panel, back)
        self.assertLess(back, body.index("</footer>"))

    def test_the_way_back_leads_to_the_start_page(self):
        response = self.client.get("/release-notes").get_data(as_text=True)
        self.assertIn('href="/"', response)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_the_way_back_is_not_on_any_other_page(self):
        """It belongs to the notes: the other pages have a footer link."""
        for body in self.pages():
            self.assertNotIn('class="notes-back"', body)

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

    # -- the install offer ------------------------------------------------------

    def test_every_footer_carries_the_install_link_and_it_is_hidden(self):
        """The script reveals it, so a reader without one never gets a
        button that cannot work."""
        for body in self.pages() + [
                self.client.get("/release-notes").get_data(as_text=True)]:
            footer = self.footer(body)
            self.assertIn('id="install-offer" hidden>', footer)
            self.assertIn('id="install-app">Install app</button>', footer)

    def test_the_install_link_follows_the_release_notes_on_one_line(self):
        for body in self.pages():
            footer = self.footer(body)
            self.assertLess(footer.index("Release notes"),
                            footer.index("Install app"))
            self.assertLess(footer.index("Version "),
                            footer.index("Install app"))

    def test_the_install_hint_is_hidden_and_outside_the_footer(self):
        for body in self.pages():
            end = body.index("</footer>")
            hint = body.index('id="install-hint"')
            self.assertGreater(hint, end)
            self.assertIn('id="install-hint" role="status" hidden>', body)

    def test_the_install_markup_has_no_inline_style(self):
        for body in self.pages():
            start = body.index('id="install-offer"')
            end = body.index('id="install-hint-close"')
            self.assertNotIn("style=", body[start:end])


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


class TestAttribution(AppTestCase):
    """Open-Meteo's licence (CC BY 4.0) requires a credit; OSM data needs one too."""

    def assert_credits(self, body):
        self.assertIn('href="https://open-meteo.com/"', body)
        self.assertIn("Open-Meteo.com", body)
        self.assertIn('href="https://creativecommons.org/licenses/by/4.0/"', body)
        self.assertIn('href="https://www.openstreetmap.org/copyright"', body)
        self.assertIn("OpenStreetMap", body)

    def test_credits_are_on_the_start_page(self):
        with mock.patch.object(config, "DONATION_URL", ""):
            self.assert_credits(self.client.get("/").get_data(as_text=True))

    def test_credits_are_on_the_forecast_page(self):
        with mock.patch.object(config, "DONATION_URL", ""):
            body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assert_credits(body)

    def test_credits_are_on_error_pages(self):
        with mock.patch.object(config, "DONATION_URL", ""):
            body = self.client.post("/", data={"city": ""}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assert_credits(body)

    def test_credits_are_in_the_footer_and_open_safely(self):
        with mock.patch.object(config, "DONATION_URL", ""):
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
