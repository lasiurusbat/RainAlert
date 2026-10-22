"""The forecast in the form the template renders.

A :class:`~rainalert.domain.model.Day` becomes one dict per column of the
week, and an :class:`~rainalert.domain.model.Hour` one dict per bar of the
strip. Every word and number on them comes from the labels and the rules,
so the panel, the column, the strip and the banner never disagree.
"""

from rainalert.domain.alerts import clock, summarise_hours
from rainalert.domain.days import day_name
from rainalert.domain.parse import parse_forecast
from rainalert.domain.rain import (chance_number, needs_umbrella, rain_chance,
                                   severity_band, severity_label)
from rainalert.present.labels import (describe_rain_chance, format_date,
                                      format_date_parts, format_precipitation,
                                      format_rain_chance, format_rain_chance_short,
                                      format_rain_hours, format_temperature,
                                      hour_height_step)


def hour_view(hour):
    """One hour of the strip, in the form the template renders."""
    band = severity_band(hour.chance)
    return {
        "day": hour.day,
        "hour": hour.moment.hour,
        "hour_label": f"{hour.moment.hour:02d}",
        "time_label": clock(hour),
        "chance": hour.chance,
        # The tooltip and the screen-reader text stand on their own, so
        # they carry the full phrase. The table cell sits under a real
        # "Rain chance" column heading, so it can be the bare number.
        "chance_label": describe_rain_chance(hour.chance),
        "chance_cell": format_rain_chance(hour.chance),
        # The bare number, for the strip's own value row: one narrow
        # column per hour does not have room for the sign.
        "chance_short": format_rain_chance_short(hour.chance),
        "severity": band,
        "severity_label": severity_label(band),
        "height": hour_height_step(hour.chance),
        # A value the app cannot read is unknown, whether it arrived as
        # null or as something that is not a number.
        "unknown": rain_chance(hour.chance) is None,
        "past": hour.past,
        "now": hour.now,
    }


def parse_today_hours(payload):
    """Today's hours, in the form the template renders."""
    return [hour_view(hour) for hour in parse_forecast(payload).today]


def day_view(day, index):
    """One day of the week, in the form the template renders."""
    chance = day.chance
    band = severity_band(chance)
    weekday_short, date_short = format_date_parts(day.iso_date)
    panel_name = day_name(day.iso_date, index, "panel")
    return {
        "date": format_date(day.iso_date),
        # The raw date, kept so the headline can name the weekday without
        # having to take the formatted date apart again.
        "iso_date": day.iso_date,
        # The short forms, for the week that is a row of seven narrow
        # columns. The long date is still on the page, for screen
        # readers.
        "weekday_short": weekday_short,
        "date_short": date_short,
        # The visible number, and the full phrase for the screen reader.
        # The column heading above the list says "chance of rain" once.
        "rain_label": format_rain_chance(chance),
        "rain_sr_label": describe_rain_chance(chance),
        "temp_label": format_temperature(day.high, day.low),
        # What the day panel says about this day: which day it is, how
        # much rain falls in it and how long it lasts. The panel is
        # built from the same chance the column shows, so the two can
        # never disagree.
        "day_name": panel_name,
        "day_label": f"{panel_name} {date_short}".strip(),
        "chance_label": (
            f"{chance_number(chance)}% chance of rain"
            if chance_number(chance) is not None
            else ""
        ),
        "amount_label": format_precipitation(day.amount),
        "hours_label": format_rain_hours(day.rain_hours),
        "chance": chance,
        # The number the row shows, and the number a personal alert
        # threshold in the browser is compared against. The browser
        # reads it from the markup, so the threshold and the number on
        # the page are always the same value.
        "chance_number": chance_number(chance),
        "severity": band,
        "severity_label": severity_label(band),
        # The panel names the band in words. A day the service did not
        # report is named as such, and the panel leaves the figures out
        # altogether: a day with no chance reported is never counted as
        # a dry one.
        "band_label": ("Rain not reported" if band == "unknown"
                       else severity_label(band)),
        "umbrella": needs_umbrella(chance),
        # The hours of this day, for the strip the reader can pick.
        # The strip and the panel are the same day, so the two can
        # never be about different days.
        "hours": [hour_view(hour) for hour in day.hours],
        # The title the strip carries while this day is the one that
        # shows, and the sentence under it.
        "hourly_title": f"{panel_name}, hour by hour",
        "hourly_summary": (summarise_hours(
            day.hours, day_name(day.iso_date, index, "summary"))
            if day.hours else ""),
        # How a caption names this day.
        "day_when": day_name(day.iso_date, index, "caption"),
    }
