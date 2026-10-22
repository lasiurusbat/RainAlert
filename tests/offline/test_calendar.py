"""The calendar file, its route and the link to it.
"""

import re
import unittest
from datetime import date

from rainalert import calendar_ics, errors
from rainalert.domain.model import Day
from tests.fixtures import AppTestCase, FakeResponse


class TestCalendarFile(unittest.TestCase):
    """The calendar file itself: the parts that do not need a server.

    The format is iCalendar (RFC 5545), so a file that is nearly right is a
    file that no calendar app can read.
    """

    def test_the_text_of_a_value_is_escaped(self):
        """A comma would otherwise split the value in two."""
        self.assertEqual(calendar_ics.calendar_escape("a,b"), "a\\,b")
        self.assertEqual(calendar_ics.calendar_escape("a;b"), "a\\;b")
        self.assertEqual(calendar_ics.calendar_escape("a\\b"), "a\\\\b")
        self.assertEqual(calendar_ics.calendar_escape("a\nb"), "a\\nb")

    def test_a_long_line_is_folded(self):
        """A content line may not be longer than 75 octets."""
        folded = calendar_ics.calendar_fold("x" * 200)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertTrue(folded.split("\r\n")[1].startswith(" "))

    def test_a_short_line_is_left_alone(self):
        self.assertEqual(calendar_ics.calendar_fold("SUMMARY:Rain"), "SUMMARY:Rain")

    def test_a_name_with_an_umlaut_is_not_cut_in_half(self):
        """The length is counted in octets, not in characters."""
        folded = calendar_ics.calendar_fold("SUMMARY:München" * 10)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertIn("München", folded)

    def test_the_event_ids_never_change(self):
        """Importing the file again has to update the same events.

        The id is built from ``calendar_slug``, which does not fold accents
        the way the address slug does. That difference is load-bearing: an
        id that changed would make a reader's calendar add a second copy of
        every event instead of updating the first.
        """
        forecast = [Day(iso_date="2026-10-21", chance=80)]
        for city, uid in (
                ("São Paulo", "rainalert-s-o-paulo-20261021@rainalert.live"),
                ("Washington, D.C.",
                 "rainalert-washington-d-c-20261021@rainalert.live"),
                ("London", "rainalert-london-20261021@rainalert.live")):
            body = calendar_ics.build_calendar(forecast, city, 50)
            self.assertIn(f"UID:{uid}\r\n", body)

    def test_a_date_becomes_an_icalendar_date(self):
        self.assertEqual(calendar_ics.calendar_day("2026-10-21"), "20261021")
        self.assertEqual(calendar_ics.calendar_next_day("2026-10-21"), "20261022")

    def test_the_day_after_a_month_is_the_first_of_the_next(self):
        """The end of an all-day event is the start of the next day.

        A month or a year has to roll over, and a leap day has to be
        counted, or the event covers the wrong days.
        """
        self.assertEqual(calendar_ics.calendar_next_day("2026-10-31"), "20261101")
        self.assertEqual(calendar_ics.calendar_next_day("2026-12-31"), "20270101")
        self.assertEqual(calendar_ics.calendar_next_day("2028-02-28"), "20280229")
        self.assertEqual(calendar_ics.calendar_next_day("2026-02-28"), "20260301")

    def test_an_unreadable_date_is_left_out(self):
        self.assertEqual(calendar_ics.calendar_day("not a date"), "")
        self.assertEqual(calendar_ics.calendar_next_day("not a date"), "")

    def test_the_file_name_is_safe(self):
        self.assertEqual(calendar_ics.calendar_slug("London, England"), "london-england")
        self.assertEqual(calendar_ics.calendar_slug("../../etc/passwd"), "etc-passwd")
        self.assertEqual(calendar_ics.calendar_slug(""), "forecast")

    def test_the_calendar_has_a_header_and_a_footer(self):
        text = calendar_ics.build_calendar([], "London", 50)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))

    def test_the_lines_end_with_carriage_returns(self):
        """A calendar file is read line by line, and the lines end in CRLF."""
        text = calendar_ics.build_calendar([], "London", 50)
        self.assertIn("\r\n", text)
        self.assertNotIn("\n\n", text)
        for line in text.split("\r\n")[:-1]:
            self.assertNotIn("\n", line)

    def test_no_line_of_the_finished_file_is_too_long(self):
        """The 75-octet limit is a property of the file, not of one value.

        The description, the summary and the calendar name are all built
        out of what the page says, so a long city name can make any of
        them long.
        """
        text = calendar_ics.build_calendar(
            [Day(iso_date="2026-10-21", chance=80)],
            "München, Bayern, Deutschland", 50)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)


class TestCalendarExport(AppTestCase):
    """Tier 2: the rainy days as a calendar file the reader can import.

    The file is built on the server, so the rule that decides which days
    go into it is tested here and not in the browser.
    """

    def payload(self, chances):
        return {
            "daily": {
                "time": [f"2026-10-{21 + offset:02d}"
                         for offset in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }

    def export(self, query="?city=London", chances=(100, 86, 40)):
        self.mock_get.return_value = FakeResponse(
            payload=self.payload(list(chances)))
        return self.client.get("/calendar.ics" + query)

    def text(self, query="?city=London", chances=(100, 86, 40)):
        return self.export(query, chances).get_data(as_text=True)

    def readable(self, query="?city=London", chances=(100, 86, 40)):
        """The file with the folded lines joined back together.

        A long description is split over several lines, so a sentence in it
        is only whole again once the file has been unfolded.
        """
        lines = self.text(query, chances).split("\r\n")
        joined = []
        for line in lines:
            if line.startswith(" ") and joined:
                joined[-1] += line[1:]
            else:
                joined.append(line)
        return "\r\n".join(joined)

    # -- the request -----------------------------------------------------------

    def test_it_needs_a_city(self):
        response = self.export("?city=")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Please enter a city name.",
                      response.get_data(as_text=True))

    def test_the_file_is_a_calendar(self):
        response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response.headers["Content-Type"])
        # The city can be anything, so the file has to say it is UTF-8.
        self.assertIn("charset=utf-8", response.headers["Content-Type"])

    def test_the_file_is_offered_as_a_download(self):
        response = self.export()
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("rain-alert-london.ics",
                      response.headers["Content-Disposition"])

    def test_the_file_is_never_cached(self):
        """It holds a forecast, so a copy of one would be a lie."""
        response = self.export()
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_an_unknown_city_is_reported(self):
        self.mock_geocode.return_value = None
        response = self.export()
        self.assertEqual(response.status_code, 404)
        self.assertIn("City not found", response.get_data(as_text=True))

    def test_a_geocoder_outage_is_not_reported_as_a_missing_city(self):
        self.mock_geocode.side_effect = errors.GeocodingUnavailable("boom")
        response = self.export()
        self.assertEqual(response.status_code, 503)
        self.assertIn("geocoding service is unavailable",
                      response.get_data(as_text=True))

    def test_a_weather_outage_is_reported(self):
        self.mock_get.side_effect = errors.WeatherUnavailable("boom")
        response = self.export()
        self.assertEqual(response.status_code, 503)
        self.assertIn("weather service is unavailable",
                      response.get_data(as_text=True))

    # -- which days go in ------------------------------------------------------

    def test_a_wet_day_becomes_an_event(self):
        text = self.text()
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("DTSTART;VALUE=DATE:20261021", text)
        self.assertIn("DTSTART;VALUE=DATE:20261022", text)

    def test_a_dry_day_does_not(self):
        """Only the days that reach the threshold are in the file."""
        text = self.text(chances=(100, 86, 40))
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)
        self.assertNotIn("DTSTART;VALUE=DATE:20261023", text)

    def test_the_apps_own_threshold_is_used_without_one(self):
        """Without a threshold of the reader's own, the app's advice rules."""
        text = self.text(chances=(50, 49))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_the_readers_own_threshold_is_used_when_it_is_sent(self):
        text = self.text("?city=London&threshold=40", chances=(50, 39))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_an_unreported_day_is_never_an_event(self):
        """A missing value is not a chance of anything."""
        text = self.text(chances=(80, None))
        self.assertEqual(text.count("BEGIN:VEVENT"), 1)

    def test_an_unreadable_threshold_falls_back_to_the_apps_own(self):
        """A nonsense threshold is not the reader's own, so it is not used.

        The browser only ever sends a number, but the link can be edited
        or typed by hand, and a hand-typed threshold must not be taken as
        the reader's own answer.
        """
        text = self.readable("?city=London&threshold=soon")
        self.assertIn("Bring an umbrella.", text)
        self.assertNotIn("alert threshold", text)
        # The app's own threshold still decides which days go in.
        self.assertIn("DTSTART;VALUE=DATE:20261021", text)
        self.assertNotIn("DTSTART;VALUE=DATE:20261023", text)

    def test_a_threshold_of_zero_takes_every_reported_day(self):
        """Zero is a threshold a reader can set, and it means every day."""
        text = self.readable("?city=London&threshold=0",
                             chances=(100, 86, 40, 0, None))
        self.assertEqual(text.count("BEGIN:VEVENT"), 4)
        # The day the service did not report is still not in the file.
        self.assertNotIn("DTSTART;VALUE=DATE:20261025", text)

    def test_the_events_are_the_days_the_page_shows(self):
        """The calendar and the list can never disagree about the wet days.

        The same forecast produces both, so the dates in the file have to
        be the dates on the page.
        """
        chances = [100, 86, 40, 15]
        self.mock_get.return_value = FakeResponse(payload=self.payload(chances))
        page = self.client.get("/city/london").get_data(as_text=True)
        text = self.readable(chances=chances)

        # The app's own threshold is 50, so the first two days are the wet
        # ones, and the file holds exactly those two.
        starts = re.findall(r"DTSTART;VALUE=DATE:(\d{8})", text)
        self.assertEqual(starts, ["20261021", "20261022"])
        for start in starts:
            day = date(int(start[:4]), int(start[4:6]), int(start[6:]))
            self.assertIn(day.strftime("%d.%m.%Y"), page)

    def test_a_dry_week_produces_a_calendar_with_no_events(self):
        """The file is still a calendar; it simply has nothing in it."""
        text = self.text(chances=(5, 10))
        self.assertNotIn("BEGIN:VEVENT", text)
        self.assertIn("END:VCALENDAR", text)

    # -- what the events say ----------------------------------------------------

    def test_the_event_covers_the_whole_day(self):
        """The end of an all-day event is the start of the next day."""
        text = self.text(chances=(80,))
        self.assertIn("DTEND;VALUE=DATE:20261022", text)

    def test_the_summary_names_the_band_and_the_chance(self):
        """The band is the one the row in the list carries."""
        text = self.readable(chances=(80,))
        self.assertIn("SUMMARY:Rain likely - 80% chance of rain", text)

    def test_the_description_names_the_city_and_the_chance(self):
        text = self.readable(chances=(80,))
        self.assertIn("80% chance of rain in London on Wednesday 21.10.2026",
                      text)

    def test_the_apps_own_advice_brings_the_umbrella(self):
        text = self.readable(chances=(80,))
        self.assertIn("Bring an umbrella", text)

    def test_the_readers_own_threshold_is_named_in_the_description(self):
        text = self.readable("?city=London&threshold=40", chances=(80,))
        self.assertIn("At or above your 40% alert threshold.", text)

    def test_the_umbrella_is_not_mixed_into_the_readers_own_alert(self):
        """The umbrella is the app's advice; the limit is the reader's."""
        text = self.readable("?city=London&threshold=40", chances=(80,))
        self.assertNotIn("Bring an umbrella", text)

    def test_the_weather_data_is_credited(self):
        """Open-Meteo's licence asks for the credit wherever the data goes."""
        text = self.readable(chances=(80,))
        self.assertIn("Open-Meteo.com", text)

    def test_the_event_id_is_the_same_every_time(self):
        """Importing the file again updates the events instead of adding
        a second copy of every one of them."""
        first = self.text(chances=(80,))
        second = self.text(chances=(80,))
        uid = [line for line in first.split("\r\n") if line.startswith("UID:")]
        self.assertTrue(uid)
        self.assertEqual(uid, [line for line in second.split("\r\n")
                                if line.startswith("UID:")])

    def test_the_calendar_is_named_after_the_city(self):
        text = self.text(chances=(80,))
        self.assertIn("X-WR-CALNAME:Rain forecast - London", text)


class TestCalendarLink(AppTestCase):
    """The link on the page that starts the export."""

    def body_with_forecast(self, chances=(100, 86, 40)):
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + offset:02d}"
                         for offset in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def test_the_link_is_on_the_forecast_page(self):
        body = self.body_with_forecast()
        self.assertIn('id="calendar-export"', body)
        self.assertIn("Add rainy days to my calendar", body)

    def test_the_link_carries_the_city(self):
        body = self.body_with_forecast()
        self.assertIn("/calendar.ics?city=London", body)

    def test_the_link_sits_on_the_heading_row(self):
        """It is on the line the heading already takes: the card has no
        vertical room for another one."""
        body = self.body_with_forecast()
        head = body[body.index("result-head"):body.index("severity-legend")]
        self.assertIn('id="calendar-export"', head)

    def test_the_link_is_on_the_same_line_as_the_caption(self):
        """The link and "7-day rain chance" are one line, not two rows."""
        body = self.body_with_forecast()
        subline = body[body.index("result-subline"):]
        subline = subline[:subline.index("</div>")]
        self.assertIn("7-day rain chance", subline)
        self.assertIn('id="calendar-export"', subline)

    def test_the_link_is_hidden_when_nothing_would_be_exported(self):
        """A link that would download an empty calendar is not an offer."""
        body = self.body_with_forecast(chances=(5, 10))
        link = body[body.index('id="calendar-export"'):]
        link = link[:link.index(">")]
        self.assertIn("hidden", link)

    def test_the_link_is_not_hidden_when_a_day_would_be_exported(self):
        body = self.body_with_forecast(chances=(80, 10))
        link = body[body.index('id="calendar-export"'):]
        link = link[:link.index(">")]
        self.assertNotIn("hidden", link)

    def test_the_link_is_not_on_the_start_page(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('id="calendar-export"', body)

    def test_the_link_is_not_on_an_error_page(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertNotIn('id="calendar-export"', body)
