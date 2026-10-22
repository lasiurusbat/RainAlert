"""The two endpoints the page uses that are not pages: the alert poll and
the calendar export.

Neither belongs in a search engine's results, and fetching either costs two
upstream requests, so both say ``noindex`` in their headers and are
disallowed in ``robots.txt``.
"""

from flask import Response, jsonify, request

from rainalert import config
from rainalert.calendar_ics import build_calendar, calendar_slug
from rainalert.domain.alerts import clock, notification_event
from rainalert.domain.rain import alert_threshold
from rainalert.errors import FORECAST_ERRORS, MISSING_CITY
from rainalert.upstream.geocoding import get_coordinates
from rainalert.upstream.open_meteo import load_forecast
from rainalert.web.common import report_failure


def calendar_failure(message, status):
    """A plain-text answer for a request that cannot be answered.

    The export is a download, so there is no page to render: the reader
    gets a sentence and a status code instead of a broken calendar.
    """
    response = Response(message, status=status, mimetype="text/plain")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
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
        return noindex(jsonify({"error": MISSING_CITY})), 400

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        hours = load_forecast(latitude, longitude).today
    except FORECAST_ERRORS as exc:
        failure = report_failure(exc, city)
        return noindex(jsonify({"error": failure.api_message})), failure.status

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
        return calendar_failure(MISSING_CITY, 400)

    threshold, personal = alert_threshold(request.args.get('threshold'))
    try:
        latitude, longitude, display_city = get_coordinates(city)
        days = load_forecast(latitude, longitude).days
    except FORECAST_ERRORS as exc:
        failure = report_failure(exc, city)
        return calendar_failure(failure.api_message, failure.status)

    body = build_calendar(days, display_city, threshold, personal)
    response = Response(body, mimetype="text/calendar")
    response.headers['Content-Disposition'] = (
        f'attachment; filename="rain-alert-{calendar_slug(display_city)}.ics"')
    # The file holds a forecast, so it is never a copy of an old one.
    response.headers['Cache-Control'] = 'no-store'
    # It is a download, not a page: it has no business in the results.
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def register(app):
    """Add the alert poll and the calendar export to the app."""
    app.add_url_rule("/api/alert", view_func=api_alert)
    app.add_url_rule("/calendar.ics", view_func=calendar_export)
