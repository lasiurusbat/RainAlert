"""The hand-written API reference against the routes the app serves.
"""

import os
import re
import unittest

from app import app
from rainalert import config
from tests.fixtures import REPO


class TestApiDocumentation(unittest.TestCase):
    """The API reference has to describe the app that is actually there.

    ``API.md`` and ``openapi.yaml`` are written by hand, so they drift the
    moment a route, a parameter or a threshold changes. These tests are what
    stops them from drifting silently: a new route that nobody documented
    fails the suite, and so does a documented route that no longer exists.
    """

    # The routes the documentation talks about. The static route is left out
    # on purpose: it is Flask's own handler, and it is described in the
    # reference as a path rather than as a route of its own.
    DOCUMENTED_ROUTES = ("/", "/api/alert", "/calendar.ics",
                         "/manifest.json", "/service-worker.js",
                         "/googlee75783b48c054b73.html", "/BingSiteAuth.xml")

    def read(self, name):
        path = os.path.join(REPO, name)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def app_routes(self):
        """The routes the app actually serves.

        They are written the way the documents write them, so that a
        Flask rule and a spec path can be compared: ``/city/<path:slug>``
        is ``/city/{slug}`` in both.
        """
        routes = set()
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith("/static/"):
                continue
            routes.add(re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule))
        return routes

    def spec_paths(self):
        """The paths the OpenAPI spec documents.

        The spec is read as text rather than parsed, because the runtime
        has five dependencies and a YAML parser is not one of them. The
        path keys are the only lines in the ``paths`` block that sit two
        spaces in and end in a colon.
        """
        text = self.read("openapi.yaml")
        start = text.index("\npaths:\n")
        end = text.index("\ncomponents:\n", start)
        block = text[start:end]
        return set(re.findall(r"^  (/\S*):$", block, re.MULTILINE))

    def test_every_route_is_in_the_reference(self):
        """A route nobody documented is a route nobody can use."""
        reference = self.read("API.md")
        for route in self.app_routes():
            self.assertIn(route, reference, route)

    def test_every_route_is_in_the_spec(self):
        """The spec is what a tool reads, so it has to cover the routes."""
        paths = self.spec_paths()
        for route in self.app_routes():
            self.assertIn(route, paths, route)

    def test_the_spec_documents_no_route_that_is_gone(self):
        """A route in the spec that the app does not serve is a lie."""
        routes = self.app_routes()
        for path in self.spec_paths():
            self.assertIn(path, routes, path)

    def test_the_spec_says_it_is_openapi(self):
        """A spec that is not OpenAPI cannot be loaded by a tool."""
        self.assertIn("openapi: 3.1.0", self.read("openapi.yaml"))

    def test_the_documented_defaults_are_the_real_ones(self):
        """The reference quotes the defaults, so they have to be the ones
        the app actually uses."""
        reference = self.read("API.md")
        self.assertIn(f"`UMBRELLA_THRESHOLD` | `{config.UMBRELLA_THRESHOLD}`",
                      reference)
        self.assertIn(f"`NOTIFICATION_POLL_MINUTES` | "
                      f"`{config.NOTIFICATION_POLL_MINUTES}`", reference)
        self.assertIn(f"`NOTIFICATION_LEAD_HOURS` | "
                      f"`{config.NOTIFICATION_LEAD_HOURS}`", reference)
        self.assertIn(f"`SEVERITY_LOW_MAX` | `{config.SEVERITY_LOW_MAX}`",
                      reference)
        self.assertIn(f"`SEVERITY_MODERATE_MAX` | "
                      f"`{config.SEVERITY_MODERATE_MAX}`", reference)

    def test_the_documented_thresholds_are_the_real_ones(self):
        """The reference states the bands in words, and so does the app.

        The reference is read with its line breaks flattened, because the
        numbers are wrapped onto the next line in the Markdown and a test
        that depended on where the wrap fell would be a nuisance.
        """
        reference = " ".join(self.read("API.md").split())
        self.assertIn(f"default **{config.UMBRELLA_THRESHOLD}**", reference)
        self.assertIn(f"default **{config.NOTIFICATION_POLL_MINUTES}**",
                      reference)
        self.assertIn(f"default **{config.NOTIFICATION_LEAD_HOURS}**",
                      reference)
