"""The upstream clients.
"""

from tests.fixtures import AppTestCase


class TestCaching(AppTestCase):
    def test_repeated_lookups_hit_the_geocoder_once(self):
        for _ in range(3):
            self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_geocode.call_count, 1)

    def test_different_cities_are_cached_separately(self):
        self.client.post("/", data={"city": "London"})
        self.client.post("/", data={"city": "Paris"})
        self.assertEqual(self.mock_geocode.call_count, 2)

    def test_failures_are_not_cached(self):
        self.mock_geocode.side_effect = RuntimeError("boom")
        self.client.post("/", data={"city": "London"})
        self.client.post("/", data={"city": "London"})
        self.assertEqual(self.mock_geocode.call_count, 2)
