"""Save what every route answers, with both upstreams mocked.

    python tools/snapshot.py <out-dir>

Each response is written to one file - status, the headers that matter and
the body - so that two runs can be compared with ``diff -r``. It is the
check for a refactor that must not change what the site serves: save a
snapshot before, save one after, and the two directories must be identical.

The two values that change on their own are masked: the sitemap's
``lastmod`` (today's date) and the calendar's ``DTSTAMP`` (the time the file
was built).
"""

import os
import re
import sys
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import requests  # noqa: E402
from geopy.exc import GeocoderServiceError  # noqa: E402

import app as rainalert  # noqa: E402
from rainalert.upstream import geocoding  # noqa: E402

DAYS = ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
        "2026-10-25", "2026-10-26", "2026-10-27"]

# A week with something in every band, an unreported day, rain in the
# hours ahead and a day with no hourly data at all.
DAILY_CHANCES = [70, 20, 45, None, 100, 0, 55]
HOURLY_CHANCES = {
    "2026-10-21": [0, 0, 5, 10, 10, 20, 30, 40, 55, 65, 80, 90,
                   60, 40, 20, None, 10, 5, 0, 0, 35, 50, 50, 10],
    "2026-10-22": [10] * 24,
    "2026-10-23": [0, 0, 0, 0, 0, 0, 10, 20, 30, 45, 45, 30,
                   20, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "2026-10-25": [100] * 12 + [70] * 12,
    "2026-10-26": [0] * 24,
    "2026-10-27": [20] * 6 + [55] * 6 + [30] * 12,
}

PAYLOAD = {
    "daily": {
        "time": DAYS,
        "precipitation_probability_max": DAILY_CHANCES,
        "temperature_2m_max": [11.5, 14.0, 16.7, None, 9.5, 12.0, 13.25],
        "temperature_2m_min": [8.5, 8.6, 10.3, None, 4.5, 6.0, 7.75],
        "precipitation_sum": [3.2, 0.0, 0.4, None, 21.75, 0.0, 1.0],
        "precipitation_hours": [5.0, 0.0, 1.0, None, 18.0, 0.0, 2.5],
    },
    "hourly": {
        "time": [f"{day}T{hour:02d}:00"
                 for day in DAYS if day in HOURLY_CHANCES
                 for hour in range(24)],
        "precipitation_probability": [chance
                                      for day in DAYS if day in HOURLY_CHANCES
                                      for chance in HOURLY_CHANCES[day]],
    },
    "current": {"time": "2026-10-21T09:15"},
    "utc_offset_seconds": 3600,
}

KEPT_HEADERS = ("Content-Type", "Location", "Cache-Control", "X-Robots-Tag",
                "Content-Disposition", "Service-Worker-Allowed")


class FakeLocation:
    latitude = 51.5074
    longitude = -0.1278
    raw = {"display_name": "London, Greater London, England, United Kingdom"}


class FakeResponse:
    def __init__(self, payload=PAYLOAD, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


# The geocoder answering with an error rather than a place.
GEOCODER_DOWN = GeocoderServiceError("HTTP Error 503")

# name, method, path, form, geocode result (or error), forecast response
REQUESTS = [
    ("start", "GET", "/", None, FakeLocation(), FakeResponse()),
    ("start-post-empty", "POST", "/", {"city": ""}, FakeLocation(), FakeResponse()),
    ("start-post-london", "POST", "/", {"city": "London"}, FakeLocation(), FakeResponse()),
    ("start-post-fahrenheit", "POST", "/", {"city": "London", "unit": "fahrenheit"},
     FakeLocation(), FakeResponse()),
    ("start-get-redirect", "GET", "/?city=London&unit=fahrenheit", None,
     FakeLocation(), FakeResponse()),
    ("start-post-not-found", "POST", "/", {"city": "Atlantis"}, None, FakeResponse()),
    ("start-post-geocoder-down", "POST", "/", {"city": "London"},
     GEOCODER_DOWN, FakeResponse()),
    ("start-post-weather-down", "POST", "/", {"city": "London"},
     FakeLocation(), FakeResponse(status_code=500)),
    ("city-london", "GET", "/city/london", None, FakeLocation(), FakeResponse()),
    ("city-london-fahrenheit", "GET", "/city/london?unit=fahrenheit", None,
     FakeLocation(), FakeResponse()),
    ("city-sao-paulo", "GET", "/city/sao-paulo", None, FakeLocation(), FakeResponse()),
    ("city-uncurated", "GET", "/city/st-john-s", None, FakeLocation(), FakeResponse()),
    ("city-redirect", "GET", "/city/London", None, FakeLocation(), FakeResponse()),
    ("city-not-found", "GET", "/city/atlantis", None, None, FakeResponse()),
    ("city-geocoder-down", "GET", "/city/london", None,
     GEOCODER_DOWN, FakeResponse()),
    ("city-weather-down", "GET", "/city/london", None,
     FakeLocation(), FakeResponse(status_code=500)),
    ("cities", "GET", "/cities", None, FakeLocation(), FakeResponse()),
    ("release-notes", "GET", "/release-notes", None, FakeLocation(), FakeResponse()),
    ("missing", "GET", "/no-such-page", None, FakeLocation(), FakeResponse()),
    ("robots", "GET", "/robots.txt", None, FakeLocation(), FakeResponse()),
    ("sitemap", "GET", "/sitemap.xml", None, FakeLocation(), FakeResponse()),
    ("manifest", "GET", "/manifest.json", None, FakeLocation(), FakeResponse()),
    ("service-worker", "GET", "/service-worker.js", None, FakeLocation(), FakeResponse()),
    ("alert", "GET", "/api/alert?city=London", None, FakeLocation(), FakeResponse()),
    ("alert-threshold", "GET", "/api/alert?city=London&threshold=95", None,
     FakeLocation(), FakeResponse()),
    ("alert-no-city", "GET", "/api/alert", None, FakeLocation(), FakeResponse()),
    ("alert-not-found", "GET", "/api/alert?city=Atlantis", None, None, FakeResponse()),
    ("alert-geocoder-down", "GET", "/api/alert?city=London", None,
     GEOCODER_DOWN, FakeResponse()),
    ("alert-weather-down", "GET", "/api/alert?city=London", None,
     FakeLocation(), FakeResponse(status_code=500)),
    ("calendar", "GET", "/calendar.ics?city=London", None, FakeLocation(), FakeResponse()),
    ("calendar-threshold", "GET", "/calendar.ics?city=S%C3%A3o%20Paulo&threshold=40",
     None, FakeLocation(), FakeResponse()),
    ("calendar-no-city", "GET", "/calendar.ics", None, FakeLocation(), FakeResponse()),
    ("calendar-not-found", "GET", "/calendar.ics?city=Atlantis", None, None, FakeResponse()),
    ("calendar-geocoder-down", "GET", "/calendar.ics?city=London", None,
     GEOCODER_DOWN, FakeResponse()),
    ("calendar-weather-down", "GET", "/calendar.ics?city=London", None,
     FakeLocation(), FakeResponse(status_code=500)),
]


def mask(text):
    text = re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>MASKED</lastmod>", text)
    return re.sub(r"DTSTAMP:\d{8}T\d{6}Z", "DTSTAMP:MASKED", text)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    client = rainalert.app.test_client()
    for name, method, path, form, location, forecast in REQUESTS:
        geocoding.get_coordinates.cache_clear()
        answer = ({"side_effect": location} if isinstance(location, Exception)
                  else {"return_value": location})
        with mock.patch.object(geocoding.geolocator, "geocode", **answer), \
                mock.patch.object(requests, "get",
                                  return_value=forecast):
            response = client.open(path, method=method, data=form)
        lines = [f"{method} {path} {form or ''}".rstrip(),
                 f"status: {response.status_code}"]
        for header in KEPT_HEADERS:
            if header in response.headers:
                lines.append(f"{header}: {response.headers[header]}")
        body = mask(response.get_data(as_text=True))
        with open(os.path.join(out, f"{name}.txt"), "w", encoding="utf-8",
                  newline="") as handle:
            handle.write("\n".join(lines) + "\n\n" + body)
    print(f"{len(REQUESTS)} responses written to {out}")


if __name__ == "__main__":
    main()
