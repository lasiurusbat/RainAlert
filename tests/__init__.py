"""RainAlert's three test suites: offline, browser and live."""

import os

# The server keeps a forecast for ten minutes by default, and the suites
# fake one forecast after another for the same coordinates. They run with the
# cache off; the tests of the cache itself turn it on.
os.environ.setdefault("WEATHER_CACHE_SECONDS", "0")
