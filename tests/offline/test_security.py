"""The security headers: every response carries them, and the policy
allows exactly what the pages load.
"""

import re

from rainalert.web import security
from tests.fixtures import AppTestCase

ROUTES = ("/", "/cities", "/release-notes", "/city/london", "/robots.txt",
          "/sitemap.xml", "/manifest.json", "/service-worker.js",
          "/api/alert?city=London", "/nowhere")


class TestSecurityHeaders(AppTestCase):

    def get(self, path, **kwargs):
        response = self.client.get(path, **kwargs)
        self.addCleanup(response.close)
        return response

    def test_every_route_carries_the_headers(self):
        for path in ROUTES:
            response = self.get(path)
            for name, value in security.HEADERS.items():
                with self.subTest(path=path, header=name):
                    self.assertEqual(response.headers.get(name), value)

    def test_an_error_page_carries_them_too(self):
        response = self.get("/nowhere")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_the_policy_allows_no_inline_code_and_no_third_party(self):
        policy = security.CONTENT_SECURITY_POLICY
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertIsNone(re.search(r"https?:", policy))
        self.assertIn("default-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_the_pages_load_only_what_the_policy_allows(self):
        """No inline script or style, and no address outside the site."""
        for path in ("/", "/city/london", "/cities", "/release-notes", "/nowhere"):
            html = self.get(path).get_data(as_text=True)
            with self.subTest(path=path):
                self.assertNotRegex(html, r"\sstyle=")
                self.assertNotRegex(html, r"<style")
                self.assertNotRegex(html, r"\son[a-z]+=")
                for script in re.findall(r"<script\b[^>]*>", html):
                    self.assertTrue("src=" in script or "ld+json" in script,
                                    script)
                for tag in re.findall(r"<(?:script|link|img)\b[^>]*>", html):
                    if 'rel="canonical"' in tag:
                        continue  # names the page, loads nothing
                    self.assertNotRegex(tag, r'(?:src|href)="https?://')

    def test_hsts_is_sent_over_https_only(self):
        self.assertNotIn("Strict-Transport-Security", self.get("/").headers)
        proxied = self.get("/", headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(proxied.headers["Strict-Transport-Security"],
                         "max-age=31536000")
        direct = self.get("/", base_url="https://rainalert.live")
        self.assertIn("Strict-Transport-Security", direct.headers)
