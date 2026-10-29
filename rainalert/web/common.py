"""What the route modules share: reporting a failure.

The forecast in the form the template renders is here too, in
:func:`fetch_weather`, but the routes build their own views from the
parsed forecast and do not go through it - it is the one place that turns
a whole forecast into views, which is what the tests want.
"""

from flask import current_app

from rainalert.errors import failure_for
from rainalert.present.forecast_view import day_view, hour_view
from rainalert.upstream.open_meteo import load_forecast


def report_failure(error, city):
    """Log a failed forecast, and say what the reader should be told.

    The messages and the status codes live in one table in
    ``rainalert/errors.py``, so the page, the alert poll and the calendar
    export say the same thing about the same failure. The exception's own
    text - "the forecast service returned HTTP 429" - goes to the log with
    the city, so the log says why; it is never shown to the reader.
    """
    failure = failure_for(error)
    if failure.log:
        current_app.logger.warning(failure.log + ": %s", city, error)
    return failure


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
