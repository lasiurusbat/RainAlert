"""The site's own files: the install manifest, the service worker, the
crawl rules and the page metadata.
"""

import json
import re
from datetime import date

import requests

from rainalert.data import cities, releases
from tests.fixtures import AppTestCase, FORECAST_PAYLOAD


class TestInstallableApp(AppTestCase):
    """Tier 2 again: the app can be installed, and it opens offline.

    The manifest says what the installed app is called and which icons it
    has; the service worker caches the shell so the app opens without a
    network. The forecast itself is never cached - a stale rain chance is
    worse than none.
    """

    def get(self, path):
        """A GET whose response is closed again.

        The manifest and the worker are sent as files, and a test client
        that throws the response away leaves the file handle open.
        """
        response = self.client.get(path)
        self.addCleanup(response.close)
        return response

    def manifest(self):
        response = self.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        return json.loads(response.get_data(as_text=True))

    def shell_files(self):
        """The files the service worker puts in its cache."""
        script = self.get("/service-worker.js").get_data(as_text=True)
        start = script.index("const SHELL")
        block = script[start:script.index("];", start)]
        return re.findall(r"'([^']+)'", block)

    # -- the manifest ---------------------------------------------------------

    def test_the_manifest_is_served_at_the_root(self):
        response = self.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("manifest", response.headers["Content-Type"])

    def test_the_manifest_names_the_app(self):
        data = self.manifest()
        self.assertIn("Rain Alert", data["name"])
        self.assertEqual(data["short_name"], "Rain Alert")
        self.assertEqual(data["lang"], "en")
        self.assertTrue(data["description"])

    def test_the_manifest_opens_the_whole_site(self):
        """A manifest served from a subdirectory would default to that
        subdirectory as its scope, and the app would not be installed."""
        data = self.manifest()
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["id"], "/")

    def test_the_manifest_stands_on_its_own(self):
        """Standalone is what makes it an app rather than a web page."""
        data = self.manifest()
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(data["theme_color"])
        self.assertTrue(data["background_color"])

    def test_the_manifest_has_the_icons_a_browser_needs(self):
        """Chrome wants a 192px icon, a 512px one and a maskable one."""
        icons = self.manifest()["icons"]
        sizes = {(icon["sizes"], icon["purpose"]) for icon in icons}
        self.assertIn(("192x192", "any"), sizes)
        self.assertIn(("512x512", "any"), sizes)
        self.assertIn(("512x512", "maskable"), sizes)

    def test_every_icon_is_a_real_png(self):
        """An icon that is not there is an install prompt that fails."""
        for icon in self.manifest()["icons"]:
            response = self.get(icon["src"])
            self.assertEqual(response.status_code, 200, icon["src"])
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(
                response.get_data().startswith(b"\x89PNG\r\n\x1a\n"),
                icon["src"])

    def test_the_apple_icon_is_served(self):
        """iOS ignores the manifest and wants its own icon."""
        response = self.get("/static/icon-180.png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.get_data().startswith(b"\x89PNG\r\n\x1a\n"))

    # -- the service worker ---------------------------------------------------

    def test_the_worker_is_served_from_the_root(self):
        """A worker served from /static/ would only control /static/."""
        response = self.get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["Content-Type"])
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")

    def test_the_worker_is_not_cached(self):
        """A worker that is cached is a worker that never updates."""
        response = self.get("/service-worker.js")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_every_file_the_worker_caches_exists(self):
        """A typo in the list is a file that never reaches the cache, and an
        app that opens offline with a hole in it."""
        files = self.shell_files()
        self.assertTrue(files)
        for path in files:
            self.assertEqual(self.get(path).status_code, 200, path)

    def test_the_shell_has_the_files_the_page_needs(self):
        shell = self.shell_files()
        for path in ("/static/style.css", "/static/app.js",
                     "/static/favicon.svg", "/static/offline.html"):
            self.assertIn(path, shell)

    def test_the_forecast_page_is_never_cached(self):
        """The page holds the forecast, and a cached forecast is a lie."""
        self.assertNotIn("/", self.shell_files())

    def test_the_export_is_not_in_the_shell(self):
        """The file holds a forecast, so it is never cached with the shell."""
        self.assertNotIn("/calendar.ics", self.shell_files())

    def test_the_export_is_never_intercepted(self):
        """An offline page is not a calendar, and must not stand in for one.

        The worker answers a navigation with the offline page when there
        is no network, so the export has to be let through before that
        branch is reached.
        """
        script = self.get("/service-worker.js").get_data(as_text=True)
        self.assertIn("/calendar.ics", script)
        self.assertLess(script.index("/calendar.ics"),
                        script.index("request.mode === 'navigate'"))

    # -- the offline page -----------------------------------------------------

    def test_the_offline_page_is_served(self):
        response = self.get("/static/offline.html")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("You are offline", body)

    def test_the_offline_page_shows_no_forecast(self):
        """There is nothing to show, and a stale chance is worse than none."""
        body = self.get("/static/offline.html").get_data(as_text=True)
        self.assertNotIn("weather-list", body)
        self.assertNotIn("hourly-strip", body)

    def test_the_offline_page_offers_a_way_back(self):
        body = self.get("/static/offline.html").get_data(as_text=True)
        self.assertIn('class="offline-retry" href="/"', body)

    # -- the page itself ------------------------------------------------------

    def test_the_page_points_at_the_manifest(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)
        self.assertIn('name="theme-color"', body)
        self.assertIn('rel="apple-touch-icon"', body)

    def test_the_manifest_is_on_the_forecast_page_too(self):
        """The installed app opens on the start page, but the manifest has
        to be there on every page."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)

    def test_the_manifest_is_on_an_error_page_too(self):
        body = self.client.post("/", data={"city": ""}).get_data(as_text=True)
        self.assertIn('rel="manifest" href="/manifest.json"', body)


class TestBingVerification(AppTestCase):
    """Bing Webmaster Tools confirms ownership by fetching a file at the root."""

    def test_the_verification_file_answers_at_the_root(self):
        response = self.client.get("/BingSiteAuth.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response.headers["Content-Type"])
        self.assertIn("<user>3748406E898E213455944433376F7F2C</user>",
                      response.get_data(as_text=True))


class TestGoogleVerification(AppTestCase):
    """Google Search Console confirms ownership by fetching a file at the root."""

    def test_the_verification_file_answers_at_the_root(self):
        response = self.client.get("/googlee75783b48c054b73.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["Content-Type"])
        self.assertEqual(
            response.get_data(as_text=True).strip(),
            "google-site-verification: googlee75783b48c054b73.html")


class TestSearchEngineOptimisation(AppTestCase):
    """The parts of the site a search engine reads.

    A search engine finds a page by its address, reads the title and the
    description off it, and follows the canonical link when the same page
    answers to more than one address. Every one of those is decided in one
    place in ``app.py``, so they cannot drift apart, and the tests here
    are what holds them to it.
    """

    def body(self, path):
        return self.client.get(path).get_data(as_text=True)

    # -- the address of a page -------------------------------------------------

    def test_a_city_has_an_address_of_its_own(self):
        """The query string is the way in, not the address."""
        response = self.client.get("/?city=London")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/london")

    def test_the_redirect_keeps_the_unit(self):
        response = self.client.get("/?city=London&unit=fahrenheit")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"],
                         "/city/london?unit=fahrenheit")

    def test_an_address_that_is_not_the_canonical_one_is_redirected(self):
        """"/city/London" and "/city/london" are one page, not two."""
        response = self.client.get("/city/London")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/city/london")

    def test_the_page_claims_its_own_address(self):
        body = self.body("/city/london")
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/city/london">',
            body)

    def test_the_start_page_claims_the_start_page(self):
        body = self.body("/")
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/">', body)

    # -- a page that is not there says so --------------------------------------

    def test_an_unknown_city_is_a_404(self):
        """A page that says "not found" but answers 200 is a soft 404, and
        search engines treat it as one."""
        self.mock_geocode.return_value = None
        response = self.client.get("/city/nowhereville")
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", response.get_data(as_text=True))

    def test_an_unknown_city_does_not_promise_a_forecast(self):
        """The title and the description of a missing page must not name a
        forecast for a city that is not there.

        The title is what a reader sees in the tab and what a shared link
        carries, so a 404 that reads like a working page is a lie the site
        tells twice: once in the tab and once in the social card.
        """
        self.mock_geocode.return_value = None
        body = self.body("/city/nowhereville")
        self.assertIn("<title>Page not found - Rain Alert</title>", body)
        self.assertNotIn("7-day rain chance for Nowhereville", body)
        self.assertNotIn("The 7-day rain chance for Nowhereville", body)

    def test_an_unknown_city_claims_no_address_of_its_own(self):
        """The page for a city that is not there is the site's 404 page as
        well, and it points at the site the way that page does."""
        self.mock_geocode.return_value = None
        body = self.body("/city/nowhereville")
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/">', body)

    def test_a_city_that_is_only_broken_keeps_its_own_page(self):
        """A 503 is not a missing page: the city is there, and the address
        and the title stay its own, because the page will come back."""
        self.mock_get.side_effect = requests.ConnectionError("down")
        body = self.body("/city/london")
        self.assertIn("<title>7-day rain chance for London - Rain Alert</title>",
                      body)
        self.assertIn(
            '<link rel="canonical" href="https://rainalert.live/city/london">',
            body)

    def test_an_upstream_that_is_down_is_a_503(self):
        """The page is fine, the moment is not."""
        self.mock_get.side_effect = requests.ConnectionError("down")
        response = self.client.get("/city/london")
        self.assertEqual(response.status_code, 503)

    def test_an_unknown_address_is_a_404_page(self):
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn("There is no page at this address.", body)
        self.assertIn('<meta name="robots" content="noindex, follow">', body)

    def test_an_address_with_nothing_in_it_is_a_404(self):
        """A slug made only of punctuation stands for no city.

        There is no name behind it, and a city with no address of its own
        has no page either: the address has to exist before the page does.
        A slug of nothing but punctuation used to be turned into an empty
        address and a redirect to nowhere.
        """
        for slug in ("---", "!!!", "..", "-"):
            with self.subTest(slug=slug):
                response = self.client.get(f"/city/{slug}")
                self.assertEqual(response.status_code, 404)
                self.assertIn("There is no page at this address.",
                              response.get_data(as_text=True))

    def test_an_address_of_nothing_in_it_is_a_404(self):
        """The same, with the slug left out altogether."""
        response = self.client.get("/city/")
        self.assertEqual(response.status_code, 404)

    def test_a_page_with_an_error_is_not_to_be_indexed(self):
        self.mock_geocode.return_value = None
        body = self.body("/city/nowhereville")
        self.assertIn('<meta name="robots" content="noindex, follow">', body)

    # -- the files a crawler asks for ------------------------------------------

    def test_the_robots_file_points_at_the_sitemap(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Sitemap: https://rainalert.live/sitemap.xml", body)
        # The alert poll and the calendar export are not pages.
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Disallow: /calendar.ics", body)

    def test_the_robots_file_slows_the_crawl_and_shuts_out_semrush(self):
        """Every city page is an upstream call the service rate-limits."""
        body = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("User-agent: SemrushBot\nDisallow: /\n", body)
        self.assertIn("User-agent: *\nCrawl-delay: 10\nAllow: /", body)

    def test_the_sitemap_names_the_pages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("<loc>https://rainalert.live/</loc>", body)
        self.assertIn("<loc>https://rainalert.live/cities</loc>", body)
        self.assertIn("<loc>https://rainalert.live/city/london</loc>", body)

    def test_the_sitemap_names_every_curated_city(self):
        body = self.body("/sitemap.xml")
        for slug, _name in cities.CURATED_CITIES:
            self.assertIn(f"<loc>https://rainalert.live/city/{slug}</loc>",
                          body)

    def test_the_static_pages_are_dated_by_the_last_release(self):
        """They change only when a release ships, so they carry its date,
        not the date of the request that fetched the sitemap."""
        body = self.body("/sitemap.xml")
        released = releases.RELEASES[0]["date"]
        for path in ("/", "/cities", "/release-notes"):
            block = re.search(
                rf"<loc>https://rainalert\.live{re.escape(path)}</loc>\s*"
                r"<lastmod>([^<]+)</lastmod>", body)
            self.assertIsNotNone(block, path)
            self.assertEqual(block.group(1), released, path)

    def test_a_city_is_dated_today(self):
        """A city's forecast changes every day, so its date is today's."""
        body = self.body("/sitemap.xml")
        today = date.today().isoformat()
        block = re.search(r"<loc>https://rainalert\.live/city/london</loc>\s*"
                          r"<lastmod>([^<]+)</lastmod>", body)
        self.assertEqual(block.group(1), today)

    def test_a_missing_address_shares_the_same_social_card(self):
        """The site's own 404 page carries the card like every other page, so a
        shared link to a missing address does not show a bare title."""
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn('<meta property="og:image:width"', body)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', body)

    def test_the_endpoints_that_are_not_pages_are_kept_out_of_the_results(self):
        for path in ("/api/alert?city=London", "/calendar.ics?city=London"):
            response = self.client.get(path)
            self.assertIn("noindex", response.headers.get("X-Robots-Tag", ""),
                          path)

    # -- what a search result shows -------------------------------------------

    def test_every_page_says_what_it_is(self):
        """A title, a description and a social card on every page."""
        for path in ("/", "/cities", "/city/london"):
            body = self.body(path)
            self.assertIn('<meta name="description" content="', body, path)
            self.assertIn('<link rel="canonical" href="https://rainalert.live',
                          body, path)
            self.assertIn('<meta property="og:title" content="', body, path)
            self.assertIn('<meta property="og:image" content="https://'
                          'rainalert.live/static/og-image.png">', body, path)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">',
                          body, path)

    def test_the_title_names_the_city(self):
        body = self.body("/city/london")
        title = re.search(r"<title>(.*?)</title>", body).group(1)
        self.assertIn("London", title)
        self.assertTrue(title.endswith("- Rain Alert"), title)

    def test_the_description_says_the_same_thing_as_the_page(self):
        body = self.body("/city/london")
        description = re.search(
            r'<meta name="description" content="([^"]*)"', body).group(1)
        self.assertIn("chance of rain in London", description)

    def test_the_page_describes_itself_in_machine_readable_form(self):
        """The structured data has to be JSON, and it has to be about this
        site."""
        body = self.body("/city/london")
        raw = re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            body, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["@context"], "https://schema.org")
        types = [node["@type"] for node in data["@graph"]]
        self.assertIn("WebSite", types)
        self.assertIn("WebApplication", types)
        # On a city's page the week itself is described, day by day.
        self.assertIn("ItemList", types)

    # -- the shape of the page -------------------------------------------------

    def test_the_headings_are_in_order(self):
        """A page that skips a level is harder to read, and a screen reader
        uses the levels to build a table of contents."""
        body = self.body("/city/london")
        levels = [int(level) for level in
                  re.findall(r"<h([1-6])[ >]", body)]
        self.assertTrue(levels)
        self.assertEqual(levels[0], 1)
        for before, after in zip(levels, levels[1:]):
            self.assertLessEqual(after, before + 1,
                                 f"h{before} is followed by h{after}")

    def test_the_days_are_a_list(self):
        """The week, in order, marked up as a list."""
        body = self.body("/city/london")
        self.assertIn('<ol class="weather-list">', body)
        self.assertEqual(body.count('<li class="weather-item'),
                         len(FORECAST_PAYLOAD["daily"]["time"]))
