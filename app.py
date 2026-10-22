"""RainAlert: look up the 7-day rain chance for any city.

Two free, keyless APIs are used:
  * Nominatim (OpenStreetMap) turns a city name into coordinates.
  * Open-Meteo returns the daily forecast for those coordinates.
"""

import logging
import os
import re
import unicodedata
from datetime import date

from flask import (Flask, Response, abort, jsonify, make_response, redirect,
                   render_template, request, send_from_directory)
from flask.logging import default_handler

from rainalert import config
from rainalert.calendar_ics import build_calendar, calendar_days, calendar_slug
from rainalert.data.cities import CITY_NAMES, CITY_SLUGS, CURATED_CITIES
from rainalert.data.releases import RELEASES
from rainalert.domain.alerts import (clock, forecast_headline, notification_event,
                                     tab_alert)
from rainalert.domain.rain import alert_threshold
from rainalert.errors import CityNotFound, GeocodingUnavailable, WeatherUnavailable
from rainalert.present.forecast_view import day_view, hour_view
from rainalert.upstream.geocoding import get_coordinates
from rainalert.upstream.open_meteo import load_forecast

app = Flask(__name__)

# The package's modules log to their own loggers, under "rainalert". They
# get the same handler, and so the same format, as app.logger.
logging.getLogger("rainalert").addHandler(default_handler)




# --- The tab title and the favicon --------------------------------------------
# The title and the favicon are the alert a visitor sees without looking at
# the page. Whether there is an alert is decided by tab_alert(), in
# rainalert/domain/alerts.py, by the same rule as the banner.

# The title says "Rain tomorrow" and not the day's date: a tab title is
# read at a glance, and "tomorrow" is the thing a reader is asking about.
TAB_TITLE_PREFIX = "Rain"
TAB_TITLE_SUFFIX = "Rain Alert"
DEFAULT_TAB_TITLE = "Rain Alert"

# The favicon that says "rain is coming", and the one that says nothing.
FAVICON_DEFAULT = "favicon.svg"
FAVICON_RAIN = "favicon-rain.svg"


# --- The page's address and its metadata --------------------------------------
# A search engine finds the site by its pages, and it needs three things from
# each of them: a title that says what the page is about, a description that
# says the same thing in a sentence, and an address that is the page's own.
# The app has all three, and they are decided here, in one place, so that
# the title a reader sees in the tab and the title a search engine shows in
# its results can never drift apart.


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


# --- Calendar export ---------------------------------------------------------
def calendar_failure(message, status):
    """A plain-text answer for a request that cannot be answered.

    The export is a download, so there is no page to render: the reader
    gets a sentence and a status code instead of a broken calendar.
    """
    response = Response(message, status=status, mimetype="text/plain")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# --- Data sources ------------------------------------------------------------
# The clients live in rainalert/upstream/, and the views they feed in
# rainalert/present/forecast_view.py. These two keep the shape the tests of
# the whole pipeline call.


def fetch_forecast(latitude, longitude, unit=None):
    """Return the daily forecast as a list of dicts.

    An empty list means the service responded but had no forecast for the
    location; transport and payload problems raise :class:`WeatherUnavailable`.
    """
    forecast, _ = fetch_weather(latitude, longitude, unit)
    return forecast


def fetch_weather(latitude, longitude, unit=None):
    """Return the daily forecast and today's hourly rain chances, as the
    template renders them.

    The daily list is the primary result. The hourly list is an addition to
    it, so it may be empty when the service omits the hourly block, but a
    transport or payload problem raises :class:`WeatherUnavailable` and the
    page shows the error rather than a half-rendered forecast.
    """
    forecast = load_forecast(latitude, longitude, unit)
    return ([day_view(day, index) for index, day in enumerate(forecast.days)],
            [hour_view(hour) for hour in forecast.today])


# --- Routes ------------------------------------------------------------------
@app.context_processor
def inject_site_info():
    """Make the donation link and the build's identity available to every
    template.

    They are read from the module on each request, not copied at import
    time, so a test can switch the donation link on and off.
    """
    return {
        "donation_url": config.DONATION_URL,
        "app_version": config.APP_VERSION,
        "app_commit": config.APP_COMMIT,
    }


def temperature_unit_from_request():
    """The temperature scale this request asks for.

    The unit comes from the query string on a GET and from the form on a
    POST. Anything unrecognised falls back to the default rather than
    failing: a stray query parameter should not break the page.
    """
    source = request.form if request.method == "POST" else request.args
    unit = (source.get("unit") or "").strip().lower()
    if unit in config.TEMPERATURE_UNITS:
        return unit
    return config.DEFAULT_TEMPERATURE_UNIT


@app.route('/', methods=['GET', 'POST'])
def index():
    """The start page, and the result of a search.

    A POST carries the city in the form; a GET carries it in the query
    string, which is how the temperature switch and the browser's own
    remembered city ask for the same forecast. Either way the page is the
    same page, and the city it is about has an address of its own that the
    page points at.

    A GET with a city is sent on to that address. A city has one address,
    and it is the one a reader can share, bookmark and a search engine can
    index; the query string is only ever the way in. The redirect is
    permanent, because the city page is the address from now on, and it
    costs nothing: the address is worked out before the forecast is
    fetched, so the extra hop asks the server for no more than a header.
    """
    source = request.form if request.method == 'POST' else request.args
    city = (source.get('city') or '').strip()
    unit = temperature_unit_from_request()
    if request.method == 'POST' and not city:
        return render_forecast_page(
            "", unit, error="Please enter a city name.")
    if request.method == 'GET' and city:
        target = city_path(city)
        if target:
            if unit != config.DEFAULT_TEMPERATURE_UNIT:
                target += f"?unit={unit}"
            return redirect(target, code=301)
    return render_forecast_page(city, unit)


def render_forecast_page(city, unit, city_page=False, error=None, status=200):
    """The page: the start page, a forecast, or a message.

    Every page of the site is rendered here, whichever address it was asked
    for, so that the title, the description, the canonical link and the
    structured data are decided in one place and cannot disagree with each
    other.

    ``city_page`` says that the page was asked for at a city's own address.
    That makes the difference between a page that is missing - a city
    nobody knows, which answers ``404`` - and a search that did not work,
    which answers ``200`` and says what went wrong.
    """
    weather_data = None
    headline = None
    display_city = None
    alert = None

    if error is None and city:
        try:
            latitude, longitude, display_city = get_coordinates(city)
            forecast = load_forecast(latitude, longitude, unit)
            weather_data = [day_view(day, index)
                            for index, day in enumerate(forecast.days)]
            # The umbrella advice is about the hours ahead, so the
            # headline is told which of today's hours are still to come.
            remaining_hours = [hour for hour in forecast.today
                               if not hour.past]
            headline = forecast_headline(forecast.days, remaining_hours)
            # The tab title and the favicon are the same alert as the
            # banner, decided by the same rule, so they can never
            # disagree with it.
            alert = tab_alert(forecast.days, remaining_hours)
        except CityNotFound:
            error = "City not found. Please try a different name (e.g., 'Paris')."
            if city_page:
                # A city's page that names a city nobody knows is a missing
                # page, and says so with its status code. A page that says
                # "not found" but answers 200 is a soft 404, and search
                # engines treat it as one.
                status = 404
        except GeocodingUnavailable:
            app.logger.warning("Geocoding service unavailable for %r", city)
            error = ("The geocoding service is unavailable right now. "
                     "Please try again in a moment.")
            if city_page:
                # The upstream is down, not the page: 503 says "come back
                # later" and keeps the address out of the index for now.
                status = 503
        except WeatherUnavailable:
            app.logger.warning("Forecast service unavailable for %r", city)
            error = ("The weather service is unavailable right now. "
                     "Please try again in a moment.")
            if city_page:
                status = 503

    # The saved city and the personal alert threshold live in the browser's
    # localStorage, so the server has to tell the page what kind of page it
    # is. A start page - no city at all - may load a remembered city by
    # itself; any other page already shows what the reader came for, and
    # reloading it would throw their forecast away.
    autoload = not city and error is None

    # The strip draws the day the reader picks, so it needs at least one day
    # that has hours in it. A forecast without any hourly data has no graph
    # at all, and says nothing about one.
    has_hourly = any(day.get("hours") for day in (weather_data or []))

    # How many days the app's own threshold would put into a calendar. The
    # browser uses it to decide whether the export link is worth offering:
    # a link that would download an empty calendar is not an offer.
    calendar_days_count = len(
        calendar_days(weather_data or [], config.UMBRELLA_THRESHOLD))

    # Whether the page carries a forecast, an error, or nothing at all. The
    # browser uses it to decide whether a search that was just submitted
    # should be remembered: only a search that worked is worth remembering.
    if error:
        search_status = "error"
    elif weather_data:
        search_status = "ok"
    else:
        search_status = "none"

    # The address this page claims for itself. A forecast has an address of
    # its own, so that a city is one page and not many; the start page is
    # the site itself.
    canonical_path = city_path(city) if city else "/"

    # The name the page calls the city by: the city on its own, without the
    # state and the country the geocoder adds.
    page_city = short_city_name(city, display_city)

    title = page_title(page_city, alert)
    description = page_description(page_city, weather_data, headline)
    # A page with an error on it is not worth indexing: there is no
    # forecast on it, and indexing it would fill the results with pages
    # that say nothing.
    robots = ("noindex, follow" if error
              else "index, follow, max-image-preview:large")

    # The temperature switch asks for the same page in the other scale, so
    # the links point at the page's own address and keep the unit.
    unit_links = {option: f"{canonical_path}?unit={option}"
                  for option in config.TEMPERATURE_UNITS}

    response = make_response(render_template(
        'index.html',
        weather_data=weather_data,
        has_hourly=has_hourly,
        headline=headline,
        error=error,
        city=city,
        display_city=display_city or city,
        page_city=page_city,
        unit=unit,
        temperature_units=config.TEMPERATURE_UNITS,
        unit_links=unit_links,
        page_title=title,
        page_description=description,
        canonical_url=canonical_url(canonical_path),
        robots=robots,
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(page_city, weather_data),
        favicon=(FAVICON_RAIN if alert else FAVICON_DEFAULT),
        autoload=autoload,
        search_status=search_status,
        calendar_days=calendar_days_count,
    ))
    response.status_code = status
    return response


@app.route('/city/<path:city_slug>')
def city_page(city_slug):
    """The forecast for one city, at the city's own address.

    Every city has one address, and that address is the canonical one: the
    page says so with a canonical link, so a search engine indexes the
    city's page rather than the many ways of asking for the same forecast.
    An address that is not the canonical one is sent there for good, so
    that "/city/London" and "/city/london" are one page and not two.

    A city that the geocoder does not know is a ``404`` and not a page with
    a message on it, because a page that says "not found" but answers
    ``200`` is a soft 404 and search engines treat it as one.
    """
    city = city_from_slug(city_slug)
    if not city:
        abort(404)
    canonical = city_path(city)
    if request.path != canonical:
        return redirect(canonical, code=301)
    return render_forecast_page(city, temperature_unit_from_request(),
                                 city_page=True)


@app.route('/cities')
def cities_index():
    """The index of the cities the site has a page for.

    It is the front door of the crawlable part of the site: every city on
    it has a page of its own, and the links on it are how a crawler finds
    them. The list is short on purpose - the geocoder is rate-limited, and
    every address here is a forecast the app has to fetch.
    """
    return render_template(
        'cities.html',
        page_title="Rain forecasts by city - Rain Alert",
        page_description=("The 7-day rain chance for a city: rain unlikely, "
                          "rain possible or rain likely for every day, and "
                          "today's forecast hour by hour."),
        canonical_url=canonical_url("/cities"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
        cities=[{"slug": slug, "name": name} for slug, name in CURATED_CITIES],
    )


@app.route('/release-notes')
def release_notes():
    """What each release brought.

    The notes are written by hand, in `rainalert/data/releases.py`, the
    same way the API reference is: they describe the app rather than being
    generated from it. The page is a page like any other, with the same panel and the
    same background, and the footer links to it from everywhere else.
    """
    return render_template(
        'release_notes.html',
        page_title="Release notes - Rain Alert",
        page_description=("What changed in each release of Rain Alert: the "
                          "night street page, the calendar export, the "
                          "browser notification and the installable app."),
        canonical_url=canonical_url("/release-notes"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
        releases=RELEASES,
    )


@app.route('/robots.txt')
def robots():
    """Where the crawlers may go.

    The alert poll and the calendar export are not pages, and fetching them
    costs two upstream requests each, so they are kept out of the crawl. The
    sitemap says where the pages are.
    """
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "Disallow: /calendar.ics",
        "",
        f"Sitemap: {canonical_url('/sitemap.xml')}",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route('/sitemap.xml')
def sitemap():
    """The pages of the site, for the crawlers.

    The home page and the city index are here, and so is every city that
    has a page of its own. The dates are today's, because the forecast on
    every one of these pages changes.
    """
    today = date.today().isoformat()
    urls = [
        ("/", "1.0", "daily"),
        ("/cities", "0.8", "weekly"),
        ("/release-notes", "0.4", "monthly"),
    ]
    for slug, _name in CURATED_CITIES:
        urls.append((f"/city/{slug}", "0.7", "daily"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, changefreq in urls:
        body.extend([
            "  <url>",
            f"    <loc>{canonical_url(path)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
    body.append("</urlset>")
    return Response("\n".join(body) + "\n", mimetype="application/xml")


@app.errorhandler(404)
def page_not_found(error):
    """The page for an address that is not on this site.

    A real ``404`` with a search form on it, rather than Flask's bare
    error page: a crawler that lands on a missing address should be told
    so clearly, and a reader who mistyped one should be able to search
    from there.
    """
    response = make_response(render_template(
        '404.html',
        page_title="Page not found - Rain Alert",
        page_description=("The 7-day rain chance for any city: rain "
                          "unlikely, rain possible or rain likely for every "
                          "day, and today's forecast hour by hour."),
        canonical_url=canonical_url("/"),
        og_image_url=config.OG_IMAGE,
        og_image_width=config.OG_IMAGE_WIDTH,
        og_image_height=config.OG_IMAGE_HEIGHT,
        structured_data=structured_data(),
    ), 404)
    return response


def noindex(response):
    """Keep a response out of the search results.

    The alert poll and the calendar export are not pages: they are an
    endpoint the page uses and a file the page hands over. Indexing either
    of them would put a JSON blob or a download in the results, and
    crawling them costs two upstream requests each.
    """
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.route('/api/alert')
def api_alert():
    """What the browser should tell the reader, if anything.

    The page polls this every ``NOTIFICATION_POLL_MINUTES`` while it is
    open. The answer is one event at most - the one thing worth interrupting
    the reader for - and the browser keeps the keys of the events it has
    already shown, so the same news is never announced twice.

    The city comes from the page, so the reader never has to type it again.
    The threshold is the reader's own, and is optional: without one the
    app's umbrella threshold is used, which is the advice the page gives.
    """
    city = (request.args.get('city') or '').strip()
    if not city:
        return noindex(jsonify(
            {"error": "Please enter a city name."})), 400

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        hours = load_forecast(latitude, longitude).today
    except CityNotFound:
        return noindex(jsonify({
            "error": "City not found. Please try a different name "
                     "(e.g., 'Paris')."})), 404
    except GeocodingUnavailable:
        app.logger.warning("Geocoding service unavailable for %r", city)
        return noindex(jsonify({
            "error": "The geocoding service is unavailable right now."})), 503
    except WeatherUnavailable:
        app.logger.warning("Forecast service unavailable for %r", city)
        return noindex(jsonify({
            "error": "The weather service is unavailable right now."})), 503

    remaining = [hour for hour in hours if not hour.past]
    now = clock(remaining[0]) if remaining else None
    return noindex(jsonify({
        "city": display_city,
        "now": now,
        "threshold": threshold,
        "personal_threshold": personal,
        "lead_hours": config.NOTIFICATION_LEAD_HOURS,
        "poll_minutes": config.NOTIFICATION_POLL_MINUTES,
        "event": notification_event(hours, threshold, display_city, personal),
    }))


@app.route('/calendar.ics')
def calendar_export():
    """The rainy days as a calendar file the reader can import.

    The city comes from the page, and the threshold is the reader's own
    when they have set one - the same split the notifications use, for the
    same reason. Without a threshold the app's umbrella threshold is used,
    which is the advice the rest of the page gives.

    The file is built here, on the server, so the rule that decides which
    days go into it is one piece of code with the offline test suite
    behind it, and not a string in the browser's script.
    """
    city = (request.args.get('city') or '').strip()
    if not city:
        return calendar_failure("Please enter a city name.", 400)

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        forecast = fetch_forecast(latitude, longitude)
    except CityNotFound:
        return calendar_failure(
            "City not found. Please try a different name (e.g., 'Paris').", 404)
    except GeocodingUnavailable:
        app.logger.warning("Geocoding service unavailable for %r", city)
        return calendar_failure(
            "The geocoding service is unavailable right now.", 503)
    except WeatherUnavailable:
        app.logger.warning("Forecast service unavailable for %r", city)
        return calendar_failure(
            "The weather service is unavailable right now.", 503)

    body = build_calendar(forecast, display_city, threshold, personal)
    response = Response(body, mimetype="text/calendar")
    response.headers['Content-Disposition'] = (
        f'attachment; filename="rain-alert-{calendar_slug(display_city)}.ics"')
    # The file holds a forecast, so it is never a copy of an old one.
    response.headers['Cache-Control'] = 'no-store'
    # It is a download, not a page: it has no business in the results.
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@app.route('/manifest.json')
def manifest():
    """The web app manifest, so the site can be installed on a phone.

    It is served from the root so that its scope can be the whole site:
    the page is at "/", the alert poll is at "/api/alert" and the worker is
    at "/service-worker.js", and a manifest served from a subdirectory
    would default to a scope of that subdirectory.
    """
    response = send_from_directory(app.static_folder, 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    # The manifest names the icons and the colours of the installed app, so
    # a changed one has to reach the phone straight away.
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/service-worker.js')
def service_worker():
    """The service worker, served from the root so that it covers the app.

    A worker served from "/static/" would only control "/static/", so it
    is served from the root instead. The Service-Worker-Allowed header is
    belt and braces: the scope of a worker is its own path unless the
    server widens it.
    """
    response = send_from_directory(app.static_folder, 'service-worker.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    # A worker that is cached is a worker that never updates.
    response.headers['Cache-Control'] = 'no-cache'
    return response


if __name__ == '__main__':
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
