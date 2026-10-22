"""The pages: the start page, a city's page, the city index and the release
notes.

Every forecast page is rendered by :func:`render_forecast_page`, whichever
address it was asked for, so the title, the description, the canonical link
and the structured data are decided in one place.
"""

from flask import (abort, make_response, redirect, render_template,
                   request)

from rainalert import config
from rainalert.calendar_ics import calendar_days
from rainalert.data.cities import CURATED_CITIES
from rainalert.data.releases import RELEASES
from rainalert.domain.alerts import forecast_headline, tab_alert
from rainalert.errors import FORECAST_ERRORS, MISSING_CITY
from rainalert.present.forecast_view import day_view
from rainalert.present.seo import (city_from_slug, city_path, page_description,
                                   page_meta, page_title, short_city_name)
from rainalert.upstream.geocoding import get_coordinates
from rainalert.upstream.open_meteo import load_forecast
from rainalert.web.common import report_failure


# The favicon is the alert a visitor sees without looking at the page.
# Whether there is an alert is decided by tab_alert(), by the same rule as
# the banner. It is two files rather than one recoloured, because a
# browser caches a favicon by its URL.
FAVICON_DEFAULT = "favicon.svg"

FAVICON_RAIN = "favicon-rain.svg"


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
            "", unit, error=MISSING_CITY)
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
    days = ()
    headline = None
    display_city = None
    alert = None

    if error is None and city:
        try:
            latitude, longitude, display_city = get_coordinates(city)
            forecast = load_forecast(latitude, longitude, unit)
            days = forecast.days
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
        except FORECAST_ERRORS as exc:
            failure = report_failure(exc, city)
            error = failure.page_message
            if city_page:
                # A city's page that fails is a missing page or an upstream
                # that is down, and says so with its status code. The start
                # page answers 200: a failed search is not a missing page.
                status = failure.status

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
    calendar_days_count = len(calendar_days(days, config.UMBRELLA_THRESHOLD))

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
        robots=robots,
        **page_meta(title, description, canonical_path, page_city,
                    weather_data),
        favicon=(FAVICON_RAIN if alert else FAVICON_DEFAULT),
        autoload=autoload,
        search_status=search_status,
        calendar_days=calendar_days_count,
    ))
    response.status_code = status
    return response


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


def cities_index():
    """The index of the cities the site has a page for.

    It is the front door of the crawlable part of the site: every city on
    it has a page of its own, and the links on it are how a crawler finds
    them. The list is short on purpose - the geocoder is rate-limited, and
    every address here is a forecast the app has to fetch.
    """
    return render_template(
        'cities.html',
        **page_meta("Rain forecasts by city - Rain Alert",
                    ("The 7-day rain chance for a city: rain unlikely, "
                     "rain possible or rain likely for every day, and "
                     "today's forecast hour by hour."),
                    "/cities"),
        cities=[{"slug": slug, "name": name} for slug, name in CURATED_CITIES],
    )


def release_notes():
    """What each release brought.

    The notes are written by hand, in `rainalert/data/releases.py`, the
    same way the API reference is: they describe the app rather than being
    generated from it. The page is a page like any other, with the same
    panel and the same background, and the footer links to it from
    everywhere else.
    """
    return render_template(
        'release_notes.html',
        **page_meta("Release notes - Rain Alert",
                    ("What Rain Alert is and what it does: the 7-day rain "
                    "chance for any city, hour by hour, with the umbrella "
                    "answer, your own threshold, a calendar export and an "
                    "installable app."),
                    "/release-notes"),
        releases=RELEASES,
    )


def register(app):
    """Add the pages to the app, under the endpoint names the templates use."""
    app.add_url_rule("/", view_func=index, methods=["GET", "POST"])
    app.add_url_rule("/city/<path:city_slug>", view_func=city_page)
    app.add_url_rule("/cities", view_func=cities_index)
    app.add_url_rule("/release-notes", view_func=release_notes)
