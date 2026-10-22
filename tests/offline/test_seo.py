"""The page's address and its metadata.

Everything a search engine reads about a page is decided here, so these
tests are about the rules rather than about the markup: a slug is safe and
stable, a name is not title-cased, a title names the alert, and the
canonical link is absolute.
"""

import unittest
from unittest import mock

from rainalert import config
from rainalert.data.cities import CITY_NAMES, CITY_SLUGS
from rainalert.present import seo


class TestCitySlug(unittest.TestCase):
    """A slug is safe in an address bar and in a file name."""

    def test_a_name_becomes_a_dashed_slug(self):
        self.assertEqual(seo.city_slug("Sao Paulo"), "sao-paulo")
        self.assertEqual(seo.city_slug("New York"), "new-york")

    def test_the_accents_are_folded_away(self):
        """A slug cannot carry an accent, so the name is looked up instead."""
        self.assertEqual(seo.city_slug("Zürich"), "zurich")
        self.assertEqual(seo.city_slug("Málaga"), "malaga")

    def test_the_punctuation_becomes_a_dash(self):
        self.assertEqual(seo.city_slug("Washington, D.C."), "washington-d-c")

    def test_a_name_with_nothing_in_it_has_no_slug(self):
        for value in ("", "   ", "!!!", None):
            with self.subTest(value=value):
                self.assertEqual(seo.city_slug(value), "")

    def test_the_same_name_always_gives_the_same_slug(self):
        self.assertEqual(seo.city_slug("Paris"), seo.city_slug("Paris"))
        self.assertEqual(seo.city_slug("Paris"), seo.city_slug("PARIS"))


class TestCityFromSlug(unittest.TestCase):
    """The city a slug stands for."""

    def test_a_curated_city_keeps_the_name_the_list_gives_it(self):
        """A slug cannot carry a name's punctuation, so the list wins."""
        self.assertEqual(seo.city_from_slug("washington-dc"), "Washington, D.C.")
        self.assertEqual(seo.city_from_slug("sao-paulo"), "Sao Paulo")

    def test_a_curated_city_is_found_by_its_own_slug(self):
        for slug, name in CITY_SLUGS.items():
            with self.subTest(slug=slug):
                self.assertEqual(seo.city_from_slug(slug), name)

    def test_a_city_that_is_not_curated_comes_from_the_slug(self):
        self.assertEqual(seo.city_from_slug("nowhereville"), "Nowhereville")
        self.assertEqual(seo.city_from_slug("st-johns"), "St johns")

    def test_only_the_first_letter_is_capitalised(self):
        """"St John's" is a name, not a sentence."""
        self.assertEqual(seo.city_from_slug("st johns"), "St johns")
        self.assertEqual(seo.city_from_slug("new york"), "New york")

    def test_a_slug_with_nothing_in_it_has_no_city(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(seo.city_from_slug(value), "")

    def test_a_slug_of_nothing_but_punctuation_has_no_city(self):
        """There is no name behind it, so there is no city.

        A city with no address of its own has no page either: the address
        has to exist before the page does. A name of only spaces would
        otherwise be truthy, and an address built from it would be empty.
        """
        for value in ("---", "!!!", "..", "-", "...", " "):
            with self.subTest(value=value):
                self.assertEqual(seo.city_from_slug(value), "")

    def test_a_slug_with_punctuation_in_it_still_has_a_city(self):
        """Only a slug with nothing in it at all is a lost one."""
        self.assertEqual(seo.city_from_slug("st-johns"), "St johns")
        self.assertEqual(seo.city_from_slug("a-b-c"), "A b c")

    def test_a_slug_is_answered_the_same_way_every_time(self):
        self.assertEqual(seo.city_from_slug("london"), "London")
        self.assertEqual(seo.city_from_slug("LONDON"), "London")
        self.assertEqual(seo.city_from_slug("  London  "), "London")


class TestCityPath(unittest.TestCase):
    """The address of a city's page."""

    def test_a_curated_city_keeps_the_slug_the_list_gives_it(self):
        """So the index, the sitemap and the page agree on the address."""
        self.assertEqual(seo.city_path("Washington, D.C."), "/city/washington-dc")
        self.assertEqual(seo.city_path("Sao Paulo"), "/city/sao-paulo")

    def test_a_city_that_is_not_curated_gets_a_slug_of_its_own(self):
        self.assertEqual(seo.city_path("Nowhereville"), "/city/nowhereville")

    def test_a_name_with_nothing_in_it_has_no_address(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(seo.city_path(value), "")

    def test_a_name_of_nothing_but_punctuation_has_no_address(self):
        """An address has to be something a browser can be sent to."""
        for value in ("---", "!!!", "..", "-"):
            with self.subTest(value=value):
                self.assertEqual(seo.city_path(value), "")

    def test_the_same_name_always_gives_the_same_address(self):
        self.assertEqual(seo.city_path("London"), seo.city_path("london"))

    def test_every_curated_city_has_an_address(self):
        for slug, name in CITY_SLUGS.items():
            with self.subTest(name=name):
                self.assertEqual(seo.city_path(name), f"/city/{slug}")


class TestShortCityName(unittest.TestCase):
    """The city's own name, without the state and the country."""

    def test_a_curated_city_keeps_the_name_the_list_gives_it(self):
        self.assertEqual(seo.short_city_name("Sao Paulo"), "Sao Paulo")

    def test_a_curated_city_is_found_whatever_the_case(self):
        self.assertEqual(seo.short_city_name("sao paulo"), "sao paulo")

    def test_the_geocoder_answers_with_a_full_address(self):
        """Only the first part of it is the city."""
        self.assertEqual(
            seo.short_city_name("Nowhereville",
                                "Nowhereville, Greater London, England, UK"),
            "Nowhereville")

    def test_the_city_is_used_when_the_geocoder_says_nothing_useful(self):
        self.assertEqual(seo.short_city_name("Nowhereville"), "Nowhereville")
        self.assertEqual(seo.short_city_name("Nowhereville", ""),
                         "Nowhereville")
        self.assertEqual(seo.short_city_name("Nowhereville", ", ,"),
                         "Nowhereville")

    def test_a_name_with_nothing_in_it_stays_nothing(self):
        self.assertEqual(seo.short_city_name(""), "")
        self.assertEqual(seo.short_city_name(None), "")


class TestPageTitle(unittest.TestCase):
    """The title is the alert, and the app's name is a suffix."""

    def test_the_start_page_leads_with_the_name(self):
        self.assertEqual(seo.page_title(None),
                         "Rain Alert - 7-day rain chance for any city")

    def test_a_city_without_an_alert_names_the_city(self):
        self.assertEqual(seo.page_title("London"),
                         "7-day rain chance for London - Rain Alert")

    def test_an_alert_names_the_day_and_the_city(self):
        alert = {"when": "tomorrow", "severity": "high"}
        self.assertEqual(seo.page_title("London", alert),
                         "Rain tomorrow in London - Rain Alert")

    def test_an_alert_without_a_city_still_names_the_day(self):
        alert = {"when": "tomorrow", "severity": "high"}
        self.assertEqual(seo.page_title(None, alert),
                         "Rain tomorrow - Rain Alert")

    def test_on_a_city_page_the_name_is_the_suffix(self):
        """So a reader with a row of tabs open can tell them apart."""
        for alert in (None, {"when": "today", "severity": "low"}):
            with self.subTest(alert=alert):
                self.assertTrue(seo.page_title("London", alert).endswith(
                    " - Rain Alert"))

    def test_a_page_that_is_missing_says_so(self):
        """A city nobody knows has no page, and the title must not promise
        a forecast for it.

        The title is what a reader sees in the tab and what a shared link
        carries, so a missing page that reads like a working one is a lie
        the site tells twice.
        """
        self.assertEqual(seo.page_title("Nowhereville", found=False),
                         "Page not found - Rain Alert")

    def test_a_missing_page_says_the_same_as_the_sites_own_404(self):
        self.assertEqual(seo.page_title("Nowhereville", found=False),
                         seo.NOT_FOUND_TITLE)


class TestPageDescription(unittest.TestCase):
    """The description is the sentence a search result shows."""

    def test_the_start_page_describes_the_site(self):
        self.assertIn("any city", seo.page_description())

    def test_a_city_without_a_forecast_names_the_city(self):
        description = seo.page_description("London")
        self.assertIn("London", description)
        self.assertIn("7-day", description)

    def test_a_city_with_a_forecast_carries_the_headline(self):
        headline = {"text": "Rain likely tomorrow (80%).", "severity": "high",
                    "umbrella": True}
        description = seo.page_description("London", [1, 2, 3], headline)
        self.assertIn("London", description)
        self.assertIn("Rain likely tomorrow (80%).", description)

    def test_the_description_is_a_sentence(self):
        self.assertTrue(seo.page_description().endswith("."))

    def test_a_missing_page_describes_the_site_and_not_the_city(self):
        """There is no forecast to describe, so the description must not
        promise one for a city that is not there."""
        description = seo.page_description("Nowhereville", found=False)
        self.assertNotIn("Nowhereville", description)
        self.assertEqual(description, seo.NOT_FOUND_DESCRIPTION)

    def test_a_missing_page_ignores_a_forecast_it_cannot_have(self):
        """The city is not there, so there is no week to describe either."""
        headline = {"text": "Rain likely tomorrow (80%).", "severity": "high",
                    "umbrella": True}
        description = seo.page_description("Nowhereville", [1, 2, 3], headline,
                                           found=False)
        self.assertNotIn("Nowhereville", description)
        self.assertNotIn("Rain likely tomorrow", description)


class TestCanonicalUrl(unittest.TestCase):
    """The canonical link is absolute."""

    def test_it_is_the_site_address_plus_the_path(self):
        self.assertEqual(seo.canonical_url("/city/london"),
                         f"{config.SITE_URL}/city/london")

    def test_the_start_page_is_the_root(self):
        self.assertEqual(seo.canonical_url("/"), f"{config.SITE_URL}/")


class TestStructuredData(unittest.TestCase):
    """The page in a machine-readable form."""

    def test_the_site_and_the_app_are_always_described(self):
        graph = seo.structured_data()["@graph"]
        types = [entry.get("@type") for entry in graph]
        self.assertIn("Organization", types)
        self.assertIn("WebSite", types)
        self.assertIn("WebApplication", types)

    def test_a_city_without_a_forecast_is_not_in_the_data(self):
        graph = seo.structured_data("London")["@graph"]
        self.assertNotIn("ItemList", [entry.get("@type") for entry in graph])

    def test_a_city_with_a_forecast_lists_the_week(self):
        forecast = [
            {"date": "Wednesday 21.10.2026", "rain_sr_label": "80% chance of rain",
             "severity_label": "Rain likely", "temp_label": "12° / 9°"},
            {"date": "Thursday 22.10.2026", "rain_sr_label": "10% chance of rain",
             "severity_label": "Rain unlikely", "temp_label": "14° / 8°"},
        ]
        graph = seo.structured_data("London", forecast)["@graph"]
        listing = next(entry for entry in graph
                       if entry.get("@type") == "ItemList")
        self.assertEqual(listing["numberOfItems"], 2)
        self.assertEqual(len(listing["itemListElement"]), 2)
        self.assertEqual(listing["itemListElement"][0]["position"], 1)
        self.assertIn("London", listing["name"])

    def test_the_context_is_the_schema_one(self):
        self.assertEqual(seo.structured_data()["@context"], "https://schema.org")


class TestPageMeta(unittest.TestCase):
    """Everything a page's head carries, decided in one place."""

    def test_it_carries_the_title_the_description_and_the_address(self):
        meta = seo.page_meta("A title", "A description.", "/city/london")
        self.assertEqual(meta["page_title"], "A title")
        self.assertEqual(meta["page_description"], "A description.")
        self.assertEqual(meta["canonical_url"],
                         f"{config.SITE_URL}/city/london")

    def test_it_carries_the_social_card(self):
        meta = seo.page_meta("A title", "A description.", "/")
        self.assertEqual(meta["og_image_url"], config.OG_IMAGE)
        self.assertEqual(meta["og_image_width"], config.OG_IMAGE_WIDTH)
        self.assertEqual(meta["og_image_height"], config.OG_IMAGE_HEIGHT)

    def test_it_carries_the_structured_data(self):
        meta = seo.page_meta("A title", "A description.", "/")
        self.assertIn("@graph", meta["structured_data"])

    def test_no_page_can_forget_a_part_of_its_head(self):
        """The head is built here, so every page gets the same set."""
        meta = seo.page_meta("A title", "A description.", "/")
        for key in ("page_title", "page_description", "canonical_url",
                    "og_image_url", "og_image_width", "og_image_height",
                    "structured_data"):
            with self.subTest(key=key):
                self.assertIn(key, meta)


class TestTheSiteUrl(unittest.TestCase):
    """The address the site is actually served from."""

    def test_the_default_is_the_domain(self):
        with mock.patch.object(config, "SITE_URL", "https://rainalert.live"):
            self.assertEqual(seo.canonical_url("/"),
                             "https://rainalert.live/")

    def test_it_is_read_at_the_moment_it_is_needed(self):
        """A test that patches the setting is seen here."""
        with mock.patch.object(config, "SITE_URL", "https://example.test"):
            self.assertEqual(seo.canonical_url("/city/london"),
                             "https://example.test/city/london")


class TestTheCityMaps(unittest.TestCase):
    """The two maps in the curated list agree with the list itself."""

    def test_the_name_map_points_at_the_right_slug(self):
        for name, slug in CITY_NAMES.items():
            with self.subTest(name=name):
                self.assertEqual(slug, seo.city_path(name).removeprefix("/city/"))

    def test_the_slug_map_points_at_the_right_name(self):
        for slug, name in CITY_SLUGS.items():
            with self.subTest(slug=slug):
                self.assertEqual(seo.city_from_slug(slug), name)
