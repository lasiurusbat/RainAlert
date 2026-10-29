"""Everything RainAlert reads from its environment.

Every setting is read once, at import, from the environment (and from a
``.env`` file when there is one). Code that uses a setting reads it as
``config.NAME`` at the moment it needs it, never as a name copied out of
this module, so that a test can patch the value here and be seen
everywhere.
"""

import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration -----------------------------------------------------------
# Nominatim's usage policy asks callers to identify themselves, so the user
# agent is configurable. The timeouts matter too: geopy defaults to a 1 second
# read timeout, which is short enough to fail on a healthy but slow service.
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "RainAlert_App_v1_2026")
GEOCODER_TIMEOUT = int(os.getenv("GEOCODER_TIMEOUT", "10"))
WEATHER_TIMEOUT = int(os.getenv("WEATHER_TIMEOUT", "10"))
# How long the server keeps a forecast it fetched, in seconds. Open-Meteo's
# free tier limits requests per IP address, and on a shared host that limit is
# shared with every other app there, so a page view, a crawler and the
# notification poll for a city that was just fetched should cost nothing. 0
# turns it off.
WEATHER_CACHE_SECONDS = int(os.getenv("WEATHER_CACHE_SECONDS", "600"))
# The second source of forecasts, used only when Open-Meteo refuses a request.
# Empty means there is none. OpenWeather bills calls past its free thousand a
# day, so the calls stop at OPENWEATHER_DAILY_LIMIT, kept under that.
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
OPENWEATHER_DAILY_LIMIT = int(os.getenv("OPENWEATHER_DAILY_LIMIT", "900"))

# Rain severity bands, used to colour-code each day of the forecast. A day
# under SEVERITY_LOW_MAX is unlikely to be wet, a day up to
# SEVERITY_MODERATE_MAX is a real possibility, and anything above is likely.
SEVERITY_LOW_MAX = int(os.getenv("SEVERITY_LOW_MAX", "30"))
SEVERITY_MODERATE_MAX = int(os.getenv("SEVERITY_MODERATE_MAX", "60"))

# The chance at which carrying an umbrella starts to be worth it. It sits
# below the top band on purpose: a 55% day is not a certainty, but it is
# enough to change what you wear.
UMBRELLA_THRESHOLD = int(os.getenv("UMBRELLA_THRESHOLD", "50"))

# The temperature scale. The forecast service converts the values itself
# when the unit is asked for, so the app never does the arithmetic and the
# numbers are the service's own. The default is the one the service uses.
TEMPERATURE_UNITS = ("celsius", "fahrenheit")
DEFAULT_TEMPERATURE_UNIT = os.getenv("TEMPERATURE_UNIT", "celsius")
if DEFAULT_TEMPERATURE_UNIT not in TEMPERATURE_UNITS:
    DEFAULT_TEMPERATURE_UNIT = "celsius"

# --- The site's own address --------------------------------------------------
# The public address of the site. The canonical links, the Open Graph tags
# and the sitemap all need an absolute URL, and the app cannot know its own
# address when it sits behind a proxy, so it is configuration.
SITE_URL = os.getenv("SITE_URL", "https://rainalert.live").rstrip("/")

# The name of the app, for the structured data and the social cards.
APP_NAME = "Rain Alert"

# Which build this is. The footer carries both, so that a reader — and the
# person looking after the site — can see which version is answering. A
# release build is given the number of the release and the commit it was
# built from; a development run says "dev" and names no commit, because a
# working tree is not a commit.
APP_VERSION = os.getenv("APP_VERSION", "dev").strip() or "dev"
APP_COMMIT = os.getenv("APP_COMMIT", "").strip()

# The image a social card shows. It is 1200 by 630 pixels, which is the
# size the card formats ask for.
OG_IMAGE = f"{SITE_URL}/static/og-image.png"
OG_IMAGE_WIDTH = "1200"
OG_IMAGE_HEIGHT = "630"

# --- Notifications -----------------------------------------------------------
# Tier 2 on the browser side: a notification while the tab is open. The page
# polls the /api/alert endpoint every NOTIFICATION_POLL_MINUTES and shows a
# notification when the forecast says rain is about to start.
#
# The rule that decides what is worth interrupting the reader for lives here,
# not in the browser, so it is one piece of code with offline tests behind it
# rather than a string in a script.

# How often the browser checks the forecast, in minutes.
NOTIFICATION_POLL_MINUTES = int(os.getenv("NOTIFICATION_POLL_MINUTES", "30"))

# How far ahead a rain warning is worth sending. The poll is every half
# hour, so a two-hour lead means the reader hears about the rain between
# half an hour and two hours before it starts.
NOTIFICATION_LEAD_HOURS = int(os.getenv("NOTIFICATION_LEAD_HOURS", "2"))


def clean_donation_url(value):
    """Return ``value`` if it is a usable https link, otherwise ``""``.

    The donation link is rendered into every page, so it is checked rather
    than trusted: only absolute ``https://`` URLs are accepted. A value such
    as ``javascript:...``, a plain ``http://`` link, a relative path, or
    something containing whitespace, quotes, angle brackets or control
    characters is ignored, and the link is left out. (Jinja escapes the value
    on output as well; this keeps obviously broken input out entirely.)
    """
    url = (value or "").strip()
    if not url or any(
        character.isspace() or character in "\"'<>\\" or ord(character) < 32
        for character in url
    ):
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return url


# Optional link to a donation page (for example Buy Me a Coffee). It is empty
# by default, and while it is empty no donation text appears anywhere, so a
# fresh checkout looks exactly as it always did. Only voluntary, one-off
# donations are compatible with Open-Meteo's free, non-commercial terms, so
# the page behind this link must not sell memberships, extras or subscriptions.
DONATION_URL = clean_donation_url(os.getenv("DONATION_URL"))
