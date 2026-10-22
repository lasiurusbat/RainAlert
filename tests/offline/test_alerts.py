"""What is worth telling a reader: the banner, the tab, the hourly
summary and the notification.
"""

import unittest

from rainalert import config
from rainalert.domain import alerts, days, parse
from rainalert.present import seo
from tests.fixtures import (AppTestCase, FakeResponse, FORECAST_PAYLOAD,
                            hourly_payload, remaining, week)


class TestHourlySummary(AppTestCase):
    """The one-line summary of when rain is likely today."""

    def _summary_for(self, chances, now="2026-10-21T09:00"):
        payload = hourly_payload(chances, now=now)
        hours = parse.parse_forecast(payload).today
        return alerts.summarise_hours(hours)

    def test_a_wet_window_is_reported(self):
        chances = [0] * 9 + [80] * 4 + [0] * 11
        summary = self._summary_for(chances)
        self.assertIn("from about 09:00 to 12:00", summary)
        self.assertIn("80%", summary)
        self.assertIn("umbrella", summary)

    def test_a_single_wet_hour_is_reported(self):
        chances = [0] * 9 + [80] + [0] * 14
        summary = self._summary_for(chances)
        self.assertIn("at about 09:00", summary)

    def test_a_dry_day_says_so(self):
        summary = self._summary_for([0] * 24)
        self.assertIn("No rain likely", summary)

    def test_a_past_window_is_not_reported(self):
        """A window that has already passed is not an alert."""
        chances = [90] * 8 + [0] * 16
        summary = self._summary_for(chances, now="2026-10-21T09:00")
        self.assertIn("No rain likely", summary)

    def test_a_window_starting_now_is_reported(self):
        chances = [0] * 9 + [90] * 3
        summary = self._summary_for(chances, now="2026-10-21T09:00")
        self.assertIn("from about 09:00 to 11:00", summary)

    def test_the_summary_ends_in_a_period(self):
        """User-facing sentences end in a period."""
        summary = self._summary_for([80] * 24)
        self.assertTrue(summary.endswith("."))

    def test_the_summary_appears_on_the_page(self):
        payload = hourly_payload([0] * 9 + [80] * 4 + [0] * 11)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("hourly-summary", body)
        self.assertIn("from about 09:00 to 12:00", body)

    def test_two_windows_are_both_mentioned(self):
        chances = [0] * 9 + [80] * 2 + [0] * 3 + [80] * 2 + [0] * 8
        summary = self._summary_for(chances)
        self.assertIn("and at other times too", summary)

    def test_the_umbrella_threshold_decides_the_window(self):
        """A window is a window only at or above the umbrella threshold."""
        below = self._summary_for([0] * 9 + [49] * 3 + [0] * 12)
        self.assertIn("No rain likely", below)
        at = self._summary_for([0] * 9 + [50] * 3 + [0] * 12)
        self.assertIn("from about 09:00 to 11:00", at)

    def test_the_summary_starts_with_a_capital(self):
        summary = self._summary_for([80] * 24)
        self.assertTrue(summary[0].isupper())

    def test_an_unknown_hour_is_not_called_possible(self):
        """A missing value is not a wet hour, and not a dry one either."""
        chances = [0] * 9 + [None] * 3 + [0] * 12
        summary = self._summary_for(chances)
        self.assertIn("No rain likely", summary)


class TestDayNames(unittest.TestCase):
    """One rule names a day, in the form each part of the page needs."""

    def test_every_form_of_every_day(self):
        expected = {
            "panel": ("Today", "Tomorrow", "Saturday"),
            "tab": ("today", "tomorrow", "Saturday"),
            "caption": ("today", "tomorrow", "on Saturday"),
            "summary": ("for the rest of today", "tomorrow", "on Saturday"),
        }
        dates = ("2026-10-21", "2026-10-22", "2026-10-24")
        for form, names in expected.items():
            for index, (iso_date, name) in enumerate(zip(dates, names)):
                position = index if index < 2 else 3
                with self.subTest(form=form, index=position):
                    self.assertEqual(days.day_name(iso_date, position, form), name)

    def test_an_unreadable_later_day_is_named_by_how_far_off_it_is(self):
        """A weekday nobody knows is not a name; "on " is not a sentence."""
        for form in ("tab", "caption", "summary"):
            self.assertEqual(days.day_name("not a date", 3, form), "in 3 days")
        # The panel puts the name in a heading, so it leaves it empty.
        self.assertEqual(days.day_name("not a date", 3, "panel"), "")


class TestOneAlert(unittest.TestCase):
    """The banner and the tab title are one alert, decided by one rule."""

    WEEKS = (
        [0, 80, 0, 0, 0, 0, 0],
        [100, 0, 0, 0, 0, 0, 0],
        [10, 20, 45, 55, 0, 90, 0],
        [None, None, 70, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [49, 50, 0, 0, 0, 0, 0],
    )
    HOURS = (None, [], [{"chance": 80}], [{"chance": 5}], [{"chance": None}])

    def test_the_banner_and_the_tab_name_the_same_day(self):
        for chances in self.WEEKS:
            for hours in self.HOURS:
                with self.subTest(chances=chances, hours=hours):
                    headline = alerts.forecast_headline(
                        week(chances), remaining(hours))
                    alert = alerts.tab_alert(week(chances), remaining(hours))
                    # The tab alerts exactly when the banner says to bring
                    # an umbrella, and about the day the banner names.
                    self.assertEqual(alert is not None, headline["umbrella"])
                    if alert is not None:
                        self.assertIn(alert["when"], headline["text"])


class TestForecastHeadline(AppTestCase):
    """The one-line headline above the daily list."""

    def _headline(self, chances, days=None, hours=None):
        return alerts.forecast_headline(
            week(chances, days), remaining(hours))

    def test_a_wet_day_names_the_day_and_the_chance(self):
        headline = self._headline([0, 80, 0, 0, 0, 0, 0])
        self.assertIn("Rain likely tomorrow", headline["text"])
        self.assertIn("80%", headline["text"])
        self.assertIn("Bring an umbrella", headline["text"])
        self.assertEqual(headline["severity"], "high")
        self.assertTrue(headline["umbrella"])

    def test_today_is_named_today(self):
        headline = self._headline([80, 0, 0, 0, 0, 0, 0])
        self.assertIn("today", headline["text"])

    def test_a_later_day_is_named_by_its_weekday(self):
        """Beyond tomorrow the banner names the weekday, like the list does."""
        # 2026-10-24 is a Saturday.
        headline = self._headline([0, 0, 0, 55, 0, 0, 0])
        self.assertIn("Saturday", headline["text"])
        self.assertIn("55%", headline["text"])

    def test_the_first_wet_day_wins(self):
        headline = self._headline([0, 60, 90, 0, 0, 0, 0])
        self.assertIn("tomorrow", headline["text"])
        self.assertIn("60%", headline["text"])
        self.assertNotIn("90%", headline["text"])

    def test_a_possible_day_says_possible(self):
        """Below the umbrella threshold the banner does not urge an umbrella."""
        headline = self._headline([0, 45, 0, 0, 0, 0, 0])
        self.assertIn("Rain possible tomorrow", headline["text"])
        self.assertIn("45%", headline["text"])
        self.assertNotIn("umbrella", headline["text"].lower())
        self.assertEqual(headline["severity"], "moderate")
        self.assertFalse(headline["umbrella"])

    def test_a_dry_week_says_so(self):
        headline = self._headline([0, 5, 10, 0, 0, 0, 0])
        self.assertIn("No rain likely for the next 7 days", headline["text"])
        self.assertEqual(headline["severity"], "low")
        self.assertFalse(headline["umbrella"])

    def test_a_week_with_an_unknown_day_is_not_called_dry(self):
        """A missing value is not a 0% chance, so the week is not all dry."""
        headline = self._headline([0, 5, None, 0, 0, 0, 0])
        self.assertIn("most of", headline["text"])
        self.assertNotIn("No rain likely for the next", headline["text"])

    def test_a_week_with_no_values_at_all_says_the_chance_is_unknown(self):
        headline = self._headline([None] * 7)
        self.assertIn("unknown", headline["text"])
        self.assertEqual(headline["severity"], "unknown")

    def test_a_week_that_is_mostly_unknown_says_so(self):
        """A claim about "most of" would be a claim about unreported days."""
        headline = self._headline([5, None, None, None, None, None, None])
        self.assertIn("unknown", headline["text"])
        self.assertEqual(headline["severity"], "unknown")
        self.assertNotIn("No rain likely", headline["text"])

    def test_today_is_judged_on_the_hours_that_are_left(self):
        """The daily maximum covers the whole day, but the reader has today."""
        hours = [{"chance": 5, "past": False}]
        # The daily maximum is 100, but only a dry evening is left.
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertNotIn("Rain likely today", headline["text"])

    def test_todays_sentence_says_which_figure_it_uses(self):
        """The hourly figure and the daily figure are different quantities."""
        hours = [{"chance": 80, "past": False}]
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("for the rest of today", headline["text"])
        self.assertIn("80%", headline["text"])
        # The daily maximum is 100, and the sentence does not quote it.
        self.assertNotIn("100%", headline["text"])

    def test_the_hours_that_are_left_can_still_make_today_wet(self):
        hours = [{"chance": 80, "past": False}]
        headline = self._headline([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("Rain likely for the rest of today", headline["text"])
        self.assertIn("80%", headline["text"])

    def test_the_umbrella_advice_is_dropped_when_today_is_already_over(self):
        """The rain is behind us, so an umbrella would be no use."""
        hours = [{"chance": 0, "past": False}]
        headline = self._headline([80, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertNotIn("today", headline["text"])
        self.assertNotIn("umbrella", headline["text"].lower())
        self.assertFalse(headline["umbrella"])

    def test_today_is_left_out_once_the_day_is_over(self):
        """A day that has been and gone is not worth the banner's one line."""
        headline = self._headline([80, 40, 0, 0, 0, 0, 0], hours=[])
        self.assertIn("tomorrow", headline["text"])
        self.assertNotIn("today", headline["text"])

    def test_the_week_is_described_as_the_rest_of_it_when_today_is_over(self):
        headline = self._headline([80, 5, 0, 0, 0, 0, 0], hours=[])
        self.assertIn("the rest of the week", headline["text"])

    def test_the_umbrella_advice_stays_for_a_later_day(self):
        """Only today's advice is affected by the hours that are left."""
        hours = [{"chance": 0, "past": False}]
        headline = self._headline([0, 80, 0, 0, 0, 0, 0], hours=hours)
        self.assertIn("Bring an umbrella", headline["text"])

    def test_an_empty_forecast_has_no_headline(self):
        self.assertIsNone(alerts.forecast_headline([]))

    def test_the_sentence_ends_in_a_period(self):
        for chances in ([0, 80, 0], [0, 45, 0], [0, 5, 0], [None, None]):
            with self.subTest(chances=chances):
                headline = self._headline(chances)
                self.assertTrue(headline["text"].endswith("."))

    def test_the_sentence_starts_with_a_capital(self):
        headline = self._headline([0, 80, 0, 0, 0, 0, 0])
        self.assertTrue(headline["text"][0].isupper())

    def test_the_banner_appears_above_the_list(self):
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("headline", body)
        self.assertLess(body.index("headline"), body.index("weather-list"))
        self.assertLess(body.index("headline"), body.index("hourly-strip"))

    def test_the_banner_is_absent_without_a_forecast(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("headline", body)

    def test_the_banner_is_absent_on_an_error_page(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assertNotIn("headline", body)

    def test_the_banner_agrees_with_the_row_it_names(self):
        """The banner and the list must not disagree about a day."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        # The mocked forecast is wet today and tomorrow, and the mocked
        # current time is 09:00 with a dry day ahead, so the banner names
        # tomorrow - the same 86% the row for tomorrow carries.
        self.assertIn("Rain likely tomorrow (86%)", body)
        self.assertIn('<span class="chance" aria-hidden="true">86%</span>', body)

    def test_the_band_is_in_the_sentence_not_only_in_the_colour(self):
        """Severity never rests on the colour alone."""
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        # The banner carries a band class, but the sentence names the band.
        banner = body.split('class="headline')[1][:400]
        self.assertIn("Rain likely", banner)


class TestTabAlert(AppTestCase):
    """The tab title and the favicon, which are the alert itself."""

    def _alert(self, chances, days=None, hours=None):
        return alerts.tab_alert(week(chances, days), remaining(hours))

    def _body_with(self, payload):
        self.mock_get.return_value = FakeResponse(payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    # -- the day label --------------------------------------------------------

    def test_the_first_day_is_today(self):
        self.assertEqual(days.day_name("2026-10-21", 0, "tab"), "today")

    def test_the_second_day_is_tomorrow(self):
        self.assertEqual(days.day_name("2026-10-22", 1, "tab"), "tomorrow")

    def test_a_later_day_is_named_by_its_weekday(self):
        # 2026-10-24 is a Saturday.
        self.assertEqual(days.day_name("2026-10-24", 3, "tab"), "Saturday")

    def test_an_unreadable_date_still_names_the_day(self):
        self.assertEqual(days.day_name("not a date", 3, "tab"), "in 3 days")

    # -- when the alert fires -------------------------------------------------

    def test_a_wet_day_alerts(self):
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertIsNotNone(alert)
        self.assertEqual(alert["when"], "tomorrow")
        self.assertEqual(alert["chance"], 80)

    def test_the_title_names_the_day(self):
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertEqual(seo.page_title(None, alert),
                         "Rain tomorrow - Rain Alert")

    def test_the_title_names_the_city_as_well(self):
        """A title that says only "Rain tomorrow" says nothing about which
        city the page is about."""
        alert = self._alert([0, 80, 0, 0, 0, 0, 0])
        self.assertEqual(seo.page_title("London", alert),
                         "Rain tomorrow in London - Rain Alert")

    def test_a_dry_week_does_not_alert(self):
        self.assertIsNone(self._alert([0, 5, 10, 0, 0, 0, 0]))

    def test_a_day_below_the_umbrella_threshold_does_not_alert(self):
        """The same threshold that puts the umbrella on the row."""
        self.assertIsNone(self._alert([0, 49, 0, 0, 0, 0, 0]))

    def test_a_day_at_the_umbrella_threshold_alerts(self):
        self.assertIsNotNone(self._alert([0, 50, 0, 0, 0, 0, 0]))

    def test_the_first_wet_day_wins(self):
        alert = self._alert([0, 60, 90, 0, 0, 0, 0])
        self.assertEqual(alert["when"], "tomorrow")
        self.assertEqual(alert["chance"], 60)

    def test_an_unreported_day_does_not_alert(self):
        """A missing value is not a 0% chance, so it is not a dry day."""
        self.assertIsNone(self._alert([None, None, None]))

    def test_an_unreported_day_does_not_hide_a_wet_one(self):
        alert = self._alert([None, 80, None])
        self.assertEqual(alert["when"], "tomorrow")

    def test_an_empty_forecast_does_not_alert(self):
        self.assertIsNone(alerts.tab_alert([]))

    # -- today is judged on the hours that are left ----------------------------

    def test_today_is_judged_on_the_hours_that_are_left(self):
        """The daily maximum covers the whole day, but the reader has today."""
        hours = [{"chance": 5, "past": False}]
        alert = self._alert([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertIsNone(alert)

    def test_the_hours_that_are_left_can_still_make_today_wet(self):
        hours = [{"chance": 80, "past": False}]
        alert = self._alert([100, 0, 0, 0, 0, 0, 0], hours=hours)
        self.assertEqual(alert["when"], "today")
        self.assertEqual(alert["chance"], 80)

    def test_a_day_that_is_over_is_left_out(self):
        """A day that has been and gone is not worth the title."""
        alert = self._alert([80, 60, 0, 0, 0, 0, 0], hours=[])
        self.assertEqual(alert["when"], "tomorrow")

    def test_a_day_that_is_over_does_not_alert_on_its_own(self):
        """Today's downpour is behind us, so it buys no alert."""
        self.assertIsNone(self._alert([80, 5, 0, 0, 0, 0, 0], hours=[]))

    # -- the page -------------------------------------------------------------

    def test_the_title_carries_the_alert(self):
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("<title>Rain tomorrow in London - Rain Alert</title>", body)

    def test_the_favicon_carries_the_alert(self):
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("favicon-rain.svg", body)

    def test_a_dry_forecast_keeps_the_plain_title(self):
        payload = {
            "daily": {
                "time": ["2026-10-21", "2026-10-22", "2026-10-23"],
                "precipitation_probability_max": [5, 10, 0],
                "temperature_2m_max": [11.1, 14.0, 16.7],
                "temperature_2m_min": [8.5, 8.6, 10.3],
            },
            "hourly": {
                "time": [f"2026-10-21T{hour:02d}:00" for hour in range(24)],
                "precipitation_probability": [0] * 24,
            },
            "current": {"time": "2026-10-21T09:00"},
            "utc_offset_seconds": 3600,
        }
        body = self._body_with(payload)
        self.assertIn("<title>7-day rain chance for London - Rain Alert</title>", body)
        self.assertIn("favicon.svg", body)
        self.assertNotIn("favicon-rain.svg", body)

    def test_an_empty_page_keeps_the_plain_title(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("<title>Rain Alert - 7-day rain chance for any city</title>", body)

    def test_an_error_page_keeps_the_plain_title(self):
        self.mock_geocode.return_value = None
        body = self.client.post("/", data={"city": "Nowhereville"}).get_data(as_text=True)
        self.assertIn('class="error"', body)
        self.assertIn("<title>7-day rain chance for Nowhereville - Rain Alert</title>", body)
        self.assertNotIn("favicon-rain.svg", body)

    def test_the_title_agrees_with_the_banner(self):
        """The tab and the banner are the same alert, so they cannot disagree."""
        body = self._body_with(FORECAST_PAYLOAD)
        self.assertIn("<title>Rain tomorrow in London - Rain Alert</title>", body)
        self.assertIn("Rain likely tomorrow (86%)", body)


class TestNotificationEvent(unittest.TestCase):
    """What is worth interrupting the reader for."""

    def event(self, chances, threshold=None, now="2026-10-21T09:00",
              personal=False, city="London"):
        payload = hourly_payload(chances, now=now)
        hours = parse.parse_forecast(payload).today
        if threshold is None:
            threshold = config.UMBRELLA_THRESHOLD
        return alerts.notification_event(
            hours, threshold, city, personal)

    def test_nothing_to_say_about_a_dry_day(self):
        self.assertIsNone(self.event([0] * 24))

    def test_nothing_to_say_without_hourly_data(self):
        self.assertIsNone(alerts.notification_event(
            [], config.UMBRELLA_THRESHOLD, "London"))

    def test_rain_in_the_current_hour_is_worth_saying(self):
        event = self.event([0] * 9 + [80] + [0] * 14)
        self.assertIsNotNone(event)
        self.assertEqual(event["key"], "now:2026-10-21")
        self.assertEqual(event["title"], "Rain likely right now")
        self.assertIn("80% chance of rain in London right now.", event["body"])

    def test_rain_about_to_start_is_worth_saying(self):
        event = self.event([0] * 10 + [80] + [0] * 13)
        self.assertEqual(event["key"], "hour:2026-10-21T10:00")
        self.assertEqual(event["title"], "Rain likely from 10:00")
        self.assertIn("80% chance of rain in London at 10:00.", event["body"])

    def test_rain_further_off_than_the_lead_is_not_worth_saying(self):
        """Two hours away is the edge; three is too far to act on."""
        self.assertIsNone(self.event([0] * 12 + [80] + [0] * 11))
        event = self.event([0] * 11 + [80] + [0] * 12)
        self.assertIsNotNone(event)

    def test_hours_that_have_gone_are_not_worth_saying(self):
        """The morning's downpour is not news at nine in the morning."""
        self.assertIsNone(self.event([80] * 9 + [0] * 15))

    def test_an_unreported_hour_is_never_a_wet_hour(self):
        """A missing value is not a chance of rain."""
        payload = hourly_payload(
            [0] * 10 + [None] + [0] * 13, now="2026-10-21T09:00")
        hours = parse.parse_forecast(payload).today
        self.assertIsNone(alerts.notification_event(
            hours, config.UMBRELLA_THRESHOLD, "London"))

    def test_the_readers_own_threshold_decides_what_counts(self):
        """A 20% hour is nothing to the app and something to the reader."""
        self.assertIsNone(self.event([0] * 10 + [20] + [0] * 13, threshold=50))
        event = self.event([0] * 10 + [20] + [0] * 13, threshold=20)
        self.assertEqual(event["title"], "Rain unlikely from 10:00")

    def test_the_readers_own_threshold_is_named_in_the_body(self):
        event = self.event([0] * 10 + [45] + [0] * 13, threshold=40,
                            personal=True)
        self.assertIn("45% chance of rain in London at 10:00.", event["body"])
        self.assertIn("Above your 40% threshold.", event["body"])

    def test_the_apps_own_advice_brings_the_umbrella(self):
        event = self.event([0] * 10 + [80] + [0] * 13)
        self.assertIn("Bring an umbrella.", event["body"])

    def test_the_umbrella_is_not_mixed_into_the_readers_own_alert(self):
        """The reader's limit is their own answer, not the app's advice."""
        event = self.event([0] * 10 + [45] + [0] * 13, threshold=40,
                            personal=True)
        self.assertNotIn("umbrella", event["body"].lower())
