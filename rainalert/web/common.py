"""What the route modules share: reporting a failure, and the forecast in
the form the template renders.
"""

from flask import current_app

from rainalert.errors import failure_for
from rainalert.present.forecast_view import day_view, hour_view
from rainalert.upstream.open_meteo import load_forecast


def report_failure(error, city):
    """Log a failed forecast, and say what the reader should be told.

    The messages and the status codes live in one table in
    ``rainalert/errors.py``, so the page, the alert poll and the calendar
    export say the same thing about the same failure.
    """
    failure = failure_for(error)
    if failure.log:
        current_app.logger.warning(failure.log, city)
    return failure


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
