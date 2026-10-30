"""The curated list of cities, and the index page that links them.

The list is the front door of the crawlable part of the site, and the two
maps built from it are what turn a typed name into an address and an
address back into a name. A mistake in the list is a wrong page at a
right-looking address, so the list is checked here rather than trusted.
"""

import re
import unittest
from unittest import mock

from markupsafe import escape

from rainalert.data.cities import (CITY_ALIASES, CITY_NAMES, CITY_NOTES,
                                    CITY_SLUGS, CURATED_CITIES)
from rainalert.present.seo import alias_key
from rainalert.upstream import geocoding
from tests.fixtures import AppTestCase


class TestTheList(unittest.TestCase):
    """The list itself."""

    def test_it_is_not_empty(self):
        self.assertTrue(CURATED_CITIES)

    def test_every_entry_is_a_slug_and_a_name(self):
        for entry in CURATED_CITIES:
            with self.subTest(entry=entry):
                self.assertIsInstance(entry, tuple)
                self.assertEqual(len(entry), 2)
                slug, name = entry
                self.assertIsInstance(slug, str)
                self.assertIsInstance(name, str)

    def test_the_slugs_are_unique(self):
        """Two cities cannot have the same address."""
        slugs = [slug for slug, _ in CURATED_CITIES]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_the_names_are_unique(self):
        """Two cities cannot answer to the same name."""
        names = [name for _, name in CURATED_CITIES]
        self.assertEqual(len(names), len(set(names)))

    def test_the_names_are_unique_when_typed_differently(self):
        """The lookup is by the lowercased name, so that is the key."""
        lowered = [name.lower() for _, name in CURATED_CITIES]
        self.assertEqual(len(lowered), len(set(lowered)))

    def test_a_slug_is_dashed_and_lowercase(self):
        for slug, _ in CURATED_CITIES:
            with self.subTest(slug=slug):
                self.assertEqual(slug, slug.lower())
                self.assertNotIn(" ", slug)
                self.assertNotIn("_", slug)
                self.assertNotIn("--", slug)
                self.assertTrue(slug.startswith("-") is False)
                self.assertTrue(slug.endswith("-") is False)

    def test_a_name_is_not_empty(self):
        for _, name in CURATED_CITIES:
            with self.subTest(name=name):
                self.assertTrue(name.strip())
                self.assertEqual(name, name.strip())

    def test_the_list_is_sorted_by_its_slug(self):
        """So it reads in order and a new entry has an obvious place."""
        slugs = [slug for slug, _ in CURATED_CITIES]
        self.assertEqual(slugs, sorted(slugs))


class TestTheMaps(unittest.TestCase):
    """The two lookups built from the list."""

    def test_the_name_map_holds_every_city(self):
        self.assertEqual(len(CITY_NAMES), len(CURATED_CITIES))

    def test_the_slug_map_holds_every_city(self):
        self.assertEqual(len(CITY_SLUGS), len(CURATED_CITIES))

    def test_the_name_map_points_at_the_right_slug(self):
        for slug, name in CURATED_CITIES:
            with self.subTest(name=name):
                self.assertEqual(CITY_NAMES[name.lower()], slug)

    def test_the_slug_map_points_at_the_right_name(self):
        for slug, name in CURATED_CITIES:
            with self.subTest(slug=slug):
                self.assertEqual(CITY_SLUGS[slug], name)

    def test_the_maps_are_the_other_way_round(self):
        """A name and a slug must not swap into each other."""
        for slug, name in CURATED_CITIES:
            with self.subTest(name=name):
                self.assertEqual(CITY_SLUGS[CITY_NAMES[name.lower()]], name)


class TestTheNames(unittest.TestCase):
    """The names are the ones people type."""

    def test_they_are_written_the_way_they_are_spoken(self):
        """No accents, so the geocoder and the reader agree."""
        for _, name in CURATED_CITIES:
            with self.subTest(name=name):
                self.assertTrue(name.isascii(), name)

    def test_washington_keeps_its_own_slug(self):
        """The one city whose name does not slug to its own name."""
        self.assertEqual(CITY_NAMES["washington, d.c."], "washington-dc")
        self.assertEqual(CITY_SLUGS["washington-dc"], "Washington, D.C.")

    def test_a_multi_word_city_keeps_its_spaces(self):
        for slug, name in CURATED_CITIES:
            if " " in name:
                with self.subTest(name=name):
                    self.assertNotIn(" ", slug)
                    self.assertIn("-", slug)


class TestTheListIsUsable(unittest.TestCase):
    """Every city on the list is a city the app can actually look up."""

    def test_every_name_looks_like_a_place_and_not_an_instruction(self):
        """The names go into a URL and a geocoder query."""
        for _, name in CURATED_CITIES:
            with self.subTest(name=name):
                self.assertNotIn("/", name)
                self.assertNotIn("?", name)
                self.assertNotIn("#", name)
                self.assertNotIn("&", name)
                self.assertNotIn("<", name)


class TestTheIndexPage(AppTestCase):
    """The page that links every city on the list.

    It is the front door of the crawlable part of the site, so every link
    on it has to be the address the city actually answers on.
    """

    def body(self):
        return self.client.get("/cities").get_data(as_text=True)

    def test_the_page_answers(self):
        self.assertEqual(self.client.get("/cities").status_code, 200)

    def test_the_page_says_what_it_is(self):
        body = self.body()
        self.assertIn("Rain forecasts by city", body)
        self.assertIn("7-day rain chance", body)

    def test_every_city_on_the_list_is_linked(self):
        """A city on the list with no link on the index is unreachable."""
        body = self.body()
        for slug, name in CURATED_CITIES:
            with self.subTest(slug=slug):
                self.assertIn(f'href="/city/{slug}"', body)
                self.assertIn(f">{name}</a>", body)

    def test_no_other_city_is_linked(self):
        """The index lists the curated cities, and nothing else."""
        body = self.body()
        listed = body.count('<li><a href="/city/')
        self.assertEqual(listed, len(CURATED_CITIES))

    def test_every_link_resolves(self):
        """Each link is the address the city answers on, not a near miss.

        A link to a slug the route would redirect is a wasted hop, and a
        link to one it would refuse is a broken page.
        """
        for slug, _name in CURATED_CITIES:
            with self.subTest(slug=slug):
                response = self.client.get(f"/city/{slug}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.request.path, f"/city/{slug}")

    def test_the_index_offers_the_search_for_any_other_city(self):
        """The list is short on purpose, so there has to be a way in."""
        body = self.body()
        self.assertIn("search for any other city", body)
        self.assertIn('href="/"', body)

    def test_the_index_is_in_the_sitemap(self):
        """A page a crawler cannot find is a page it will not visit."""
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<loc>https://rainalert.live/cities</loc>", sitemap)

    def test_the_index_claims_its_own_address(self):
        body = self.body()
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/cities">',
            body)


class TestTheNotes(unittest.TestCase):
    """Every city on the list says something about its own weather."""

    def test_every_curated_city_has_a_note(self):
        for slug, name in CURATED_CITIES:
            with self.subTest(city=name):
                self.assertTrue(CITY_NOTES.get(slug, "").strip())

    def test_no_note_is_for_a_city_off_the_list(self):
        slugs = {slug for slug, _ in CURATED_CITIES}
        self.assertEqual(set(CITY_NOTES), slugs)

    def test_no_note_carries_a_figure(self):
        """A note is words about the usual weather; a number in it would be
        a claim the page cannot back up for every week."""
        for slug, note in CITY_NOTES.items():
            with self.subTest(city=slug):
                self.assertFalse(re.search(r"\d", note))


class TestTheNoteOnThePage(AppTestCase):
    """The note is on a city's own page, under its forecast, and nowhere else."""

    def test_a_city_page_carries_its_note(self):
        body = self.client.get("/city/london").get_data(as_text=True)
        note = escape(CITY_NOTES["london"])
        self.assertIn(f'<p class="city-note">{note}</p>', body)

    def test_the_start_page_carries_no_note(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("city-note", body)

    def test_a_missing_city_carries_no_note(self):
        with mock.patch.object(geocoding.geolocator, "geocode", return_value=None):
            response = self.client.get("/city/nowhereville")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("city-note", response.get_data(as_text=True))


class TestAliases(unittest.TestCase):
    """A second name for a listed city is that city, not a new page."""

    def test_every_alias_points_at_a_listed_city(self):
        for alias, slug in CITY_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(slug, CITY_SLUGS)

    def test_an_alias_is_not_also_a_listed_name(self):
        for alias in CITY_ALIASES:
            with self.subTest(alias=alias):
                self.assertNotIn(alias, CITY_NAMES)

    def test_every_alias_is_written_the_way_it_is_looked_up(self):
        for alias in CITY_ALIASES:
            with self.subTest(alias=alias):
                self.assertEqual(alias_key(alias), alias)

    def test_no_alias_is_the_address_of_a_listed_city(self):
        """An alias that is also a listed slug would be a page twice."""
        for alias in CITY_ALIASES:
            with self.subTest(alias=alias):
                self.assertNotIn(alias.replace(" ", "-"), CITY_SLUGS)

    def test_an_accent_or_a_capital_makes_no_difference(self):
        self.assertEqual(alias_key("București"), "bucuresti")
        self.assertEqual(alias_key("Frankfurt am Main"), "frankfurt am main")
        self.assertEqual(alias_key("Washington, D.C."), "washington d c")


class TestAliasesOnThePages(AppTestCase):
    def test_the_longer_address_goes_to_the_listed_one(self):
        response = self.client.get("/city/frankfurt-am-main")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/frankfurt")

    def test_a_search_for_the_longer_name_goes_to_the_listed_address(self):
        response = self.client.get("/?city=Frankfurt am Main")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/frankfurt")

    def test_every_alias_goes_to_its_listed_city(self):
        for alias, slug in CITY_ALIASES.items():
            with self.subTest(alias=alias):
                response = self.client.get("/city/" + alias.replace(" ", "-"))
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response.headers["Location"], f"/city/{slug}")

    def test_every_alias_searched_for_goes_to_its_listed_city(self):
        for alias, slug in CITY_ALIASES.items():
            with self.subTest(alias=alias):
                response = self.client.get("/", query_string={"city": alias})
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response.headers["Location"], f"/city/{slug}")

    def test_an_accented_name_finds_its_alias(self):
        response = self.client.get("/", query_string={"city": "București"})
        self.assertEqual(response.headers["Location"], "/city/bucharest")

    def test_a_posted_search_shows_the_note_at_the_listed_address(self):
        body = self.client.post(
            "/", data={"city": "Frankfurt am Main"}).get_data(as_text=True)
        self.assertIn('<link rel="canonical" href="https://rainalert.live/city/frankfurt">', body)
        self.assertIn(escape(CITY_NOTES["frankfurt"]), body)

    def test_the_alias_has_no_page_in_the_sitemap(self):
        body = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertNotIn("frankfurt-am-main", body)
