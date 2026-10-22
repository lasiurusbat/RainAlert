"""The page's address and its metadata.

A search engine finds the site by its pages, and it needs three things from
each of them: a title that says what the page is about, a description that
says the same thing in a sentence, and an address that is the page's own.
They are decided here, in one place, so that the title a reader sees in the
tab and the title a search engine shows in its results can never drift
apart.
"""

import re
import unicodedata

from rainalert import config
from rainalert.data.cities import CITY_NAMES, CITY_SLUGS


# The title says "Rain tomorrow" and not the day's date: a tab title is
# read at a glance, and "tomorrow" is the thing a reader is asking about.
TAB_TITLE_PREFIX = "Rain"

TAB_TITLE_SUFFIX = "Rain Alert"


def city_slug(value):
    """A URL-safe slug for a city name: "Sao Paulo" -> "sao-paulo".

    The accents are folded away and everything else that is not a letter or
    a digit becomes a dash, so the slug is safe in an address bar and in a
    file name. The name it stands for is looked up separately, because a
    slug cannot carry the punctuation a real name has.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def city_from_slug(slug):
    """The city a slug stands for.

    The curated list wins, because a slug cannot carry a city's accents or
    its punctuation and the geocoder needs the name. Anything else falls
    back to the slug with its dashes turned back into spaces, which is the
    name for every city whose name is made of letters and spaces.

    Only the first letter of that fallback name is capitalised: a name is
    not a sentence, and capitalising every word would turn "St John's" into
    "St John'S".
    """
    key = str(slug or "").strip().lower()
    if not key:
        return ""
    if key in CITY_SLUGS:
        return CITY_SLUGS[key]
    name = key.replace("-", " ")
    return name[:1].upper() + name[1:]


def city_path(city_name):
    """The address of a city's page.

    The address is made of the name the city was asked for, never of the
    name the geocoder answers with: the geocoder's own name is a full
    address ("London, United Kingdom"), and an address built from it would
    not be the same one the reader asked for.

    A city that is in the curated list keeps the slug the list gives it, so
    that the address in the city index, the address in the sitemap and the
    address the page claims for itself are the same one. Any other city
    gets a slug of its own.
    """
    name = str(city_name or "").strip()
    slug = CITY_NAMES.get(name.lower())
    if not slug:
        slug = city_slug(name)
    if not slug:
        return ""
    return f"/city/{slug}"


def short_city_name(city, display_city=None):
    """The city's own name, without the state and the country.

    The geocoder answers with a full address - "London, Greater London,
    England, United Kingdom" - which is more than a title or a heading can
    carry, and more than a reader scanning the page needs. The first part
    of it is the city.

    A city that is in the curated list keeps the name the list gives it,
    because the list has the name written the way it is usually written.
    """
    name = str(city or "").strip()
    if name.lower() in CITY_NAMES:
        return name
    if display_city:
        first = str(display_city).split(",")[0].strip()
        if first:
            return first
    return name


def page_title(city, alert=None):
    """The title of the page.

    The title is the alert: it names the first wet day, and the favicon
    changes with it. On a city's page the city is in the title as well,
    because a title that says only "Rain tomorrow" tells a reader - or a
    search engine - nothing about which city the page is about. The app's
    name stays a suffix, in the usual "page - site" order, so that a reader
    with a row of tabs open can still tell which one is Rain Alert.
    """
    if alert:
        when = alert["when"]
        if city:
            return f"{TAB_TITLE_PREFIX} {when} in {city} - {TAB_TITLE_SUFFIX}"
        return f"{TAB_TITLE_PREFIX} {when} - {TAB_TITLE_SUFFIX}"
    if city:
        return f"7-day rain chance for {city} - {TAB_TITLE_SUFFIX}"
    # The start page leads with the name, because there the name is what
    # the page is: a page for every city, not a page about one.
    return f"{TAB_TITLE_SUFFIX} - 7-day rain chance for any city"


def page_description(city=None, forecast=None, headline=None):
    """The description of the page: the sentence under the title in a search
    result.

    On a city's page it is the headline the page already shows, so that the
    snippet in the search results says the same thing as the page does.
    """
    if city and forecast:
        sentence = (f"The chance of rain in {city} for the next 7 days, "
                    f"hour by hour for today.")
        if headline:
            sentence += " " + headline["text"]
        return sentence
    if city:
        return (f"The 7-day rain chance for {city}: rain unlikely, rain "
                f"possible or rain likely for every day, and today's "
                f"forecast hour by hour.")
    return ("The chance of rain for the next seven days in any city, hour by "
            "hour for today. Rain unlikely, rain possible or rain likely, "
            "every day. Free, no signup.")


def canonical_url(path):
    """The absolute address of a page on this site."""
    return f"{config.SITE_URL}{path}"


def structured_data(city=None, forecast=None):
    """The page in a machine-readable form.

    Three things are described: the site, the app, and - on a city's page -
    the week itself, day by day. A search engine reads this to work out
    what the page is about, and a rich result may be built from it.
    """
    graph = [
        {
            "@type": "Organization",
            "@id": f"{config.SITE_URL}/#organization",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "logo": f"{config.SITE_URL}/static/icon-512.png",
        },
        {
            "@type": "WebSite",
            "@id": f"{config.SITE_URL}/#website",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "description": "The 7-day rain chance for any city.",
            "inLanguage": "en",
            "publisher": {"@id": f"{config.SITE_URL}/#organization"},
        },
        {
            "@type": "WebApplication",
            "name": config.APP_NAME,
            "url": f"{config.SITE_URL}/",
            "applicationCategory": "WeatherApplication",
            "operatingSystem": "Any",
            "description": page_description(),
            "offers": {
                "@type": "Offer",
                "price": "0",
                "priceCurrency": "EUR",
            },
        },
    ]
    if city and forecast:
        graph.append({
            "@type": "ItemList",
            "name": f"7-day rain chance for {city}",
            "numberOfItems": len(forecast),
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index + 1,
                    "item": {
                        "@type": "Thing",
                        "name": f"{day['date']}: {day['rain_sr_label']}",
                        "description": (f"{day['severity_label']}. "
                                        f"Temperature {day['temp_label']}."),
                    },
                }
                for index, day in enumerate(forecast)
            ],
        })
    return {"@context": "https://schema.org", "@graph": graph}


def page_meta(title, description, path, city=None, forecast=None):
    """Everything a page's head carries, for ``render_template(**...)``.

    The title, the description and the address are the page's own; the
    social card and the structured data are the site's, with the week added
    on a city's page. Every page passes its head through here, so no page
    can forget the card or point its canonical link somewhere else.
    """
    return {
        "page_title": title,
        "page_description": description,
        "canonical_url": canonical_url(path),
        "og_image_url": config.OG_IMAGE,
        "og_image_width": config.OG_IMAGE_WIDTH,
        "og_image_height": config.OG_IMAGE_HEIGHT,
        "structured_data": structured_data(city, forecast),
    }
