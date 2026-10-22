"""The labels the page shows for a chance, a date and a temperature.
"""

import re
import unittest

from rainalert.present import labels
from tests.fixtures import AppTestCase, FakeResponse, hourly_payload


class TestRainChanceLabel(AppTestCase):
    """'Chance of rain' is said once, in the column heading.

    The rows carry the number alone. Repeating the phrase on every row
    said nothing after the first one and made the list hard to scan.
    """

    def _body_for(self, chances):
        payload = {
            "daily": {
                "time": [f"2026-10-{21 + i:02d}" for i in range(len(chances))],
                "precipitation_probability_max": chances,
                "temperature_2m_max": [14.0] * len(chances),
                "temperature_2m_min": [8.0] * len(chances),
            }
        }
        self.mock_get.return_value = FakeResponse(payload=payload)
        return self.client.post("/", data={"city": "London"}).get_data(as_text=True)

    def _rows(self, body):
        """The visible chance of each row, in order."""
        return re.findall(
            r'<span class="chance" aria-hidden="true">([^<]*)</span>', body)

    def test_the_phrase_is_said_once(self):
        """The column heading carries the wording, not the rows."""
        body = self._body_for([10, 45, 80])
        self.assertEqual(body.count(">Rain chance<"), 1)

    def test_the_heading_is_its_own_element(self):
        """The heading is a class of its own, so CSS can line it up."""
        body = self._body_for([10])
        self.assertIn('<span class="column-head">Rain chance</span>', body)

    def test_the_heading_is_above_the_list(self):
        """The heading belongs to the list, so it sits directly above it."""
        body = self._body_for([10, 45, 80])
        self.assertLess(body.index("Rain chance"), body.index("weather-list"))

    def test_the_rows_carry_the_number_alone(self):
        body = self._body_for([10, 45, 80])
        self.assertEqual(self._rows(body), ["10%", "45%", "80%"])

    def test_a_row_does_not_repeat_the_phrase(self):
        """The whole point: the phrase is not in the visible list.

        It stays in the hidden span, because that is the text a screen
        reader gets instead of the bare number.
        """
        body = self._body_for([10, 45, 80])
        listing = body[body.index('class="weather-list"'):]
        visible = re.sub(r'<span class="sr-only">.*?</span>', "", listing,
                         flags=re.DOTALL)
        self.assertNotIn("chance of rain", visible)

    def test_the_screen_reader_still_gets_the_phrase(self):
        """The visible number is hidden from readers, so the phrase stands in."""
        body = self._body_for([10])
        self.assertIn('<span class="sr-only">10% chance of rain</span>', body)

    def test_the_umbrella_is_announced_too(self):
        body = self._body_for([80])
        self.assertIn("Take an umbrella.", body)

    def test_an_unknown_chance_is_not_shown_as_zero(self):
        """A missing value must never read as a dry day."""
        body = self._body_for([None])
        self.assertIn('<span class="chance" aria-hidden="true">unknown</span>', body)
        self.assertNotIn('<span class="chance" aria-hidden="true">0%</span>', body)

    def test_the_hourly_table_cell_is_the_number_alone(self):
        """The table has a real column heading, so the cell can be short."""
        payload = hourly_payload([63] * 24)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("<th scope=\"col\">Rain chance</th>", body)
        self.assertIn("<td>63%</td>", body)

    def test_the_hourly_tooltip_keeps_the_phrase(self):
        """A tooltip stands on its own, so it carries the whole wording."""
        payload = hourly_payload([63] * 24)
        self.mock_get.return_value = FakeResponse(payload=payload)
        body = self.client.post("/", data={"city": "London"}).get_data(as_text=True)
        self.assertIn("63% chance of rain", body)


class TestShortDate(unittest.TestCase):
    """The short forms of a date, for the row of columns."""

    def test_the_weekday_and_the_day_and_month(self):
        self.assertEqual(labels.format_date_parts("2026-10-22"),
                         ("Thu", "22.10"))

    def test_the_weekday_is_always_english(self):
        """The names are hard-coded, so a locale cannot change them."""
        for iso_date, short in (("2026-10-19", "Mon"), ("2026-10-25", "Sun")):
            with self.subTest(iso_date=iso_date):
                self.assertEqual(labels.format_date_parts(iso_date)[0], short)

    def test_a_date_that_cannot_be_read_has_no_short_form(self):
        """A day the service dated unreadably has no weekday and no date.

        An empty string is not "on " and not a wrong weekday: the column
        says nothing rather than something that is not true.
        """
        for value in ("not-a-date", "", None):
            with self.subTest(value=value):
                self.assertEqual(labels.format_date_parts(value), ("", ""))


class TestUnreadableValues(unittest.TestCase):
    """A value the service did not report is not a zero.

    Every one of these turns a value that cannot be read into an empty
    label, so the page says nothing rather than something that is not
    true. A chance the service did not report is "unknown", not "0%".
    """

    def test_an_unreadable_chance_is_unknown(self):
        for value in (None, "not a number", ""):
            with self.subTest(value=value):
                self.assertEqual(labels.format_rain_chance(value), "unknown")
                self.assertEqual(labels.format_rain_chance_short(value), "?")
                self.assertEqual(labels.describe_rain_chance(value),
                                 "chance of rain unknown")

    def test_an_unreadable_amount_says_nothing(self):
        """A day with no rain in it says nothing about the millimetres.

        "0 mm" beside a chance of rain would read as a contradiction,
        because the two come from different parts of the model.
        """
        for value in (None, "not a number", 0, 0.0, -1):
            with self.subTest(value=value):
                self.assertEqual(labels.format_precipitation(value), "")

    def test_an_amount_is_shown_with_one_decimal(self):
        """A difference between 4 mm and 5 mm is a drizzle and a shower."""
        self.assertEqual(labels.format_precipitation(4.04), "4.0 mm")
        self.assertEqual(labels.format_precipitation(5), "5.0 mm")

    def test_an_unreadable_number_of_hours_says_nothing(self):
        for value in (None, "not a number", 0, -1):
            with self.subTest(value=value):
                self.assertEqual(labels.format_rain_hours(value), "")

    def test_the_hours_are_rounded_to_whole(self):
        self.assertEqual(labels.format_rain_hours(3.2), "3 h of rain")
        self.assertEqual(labels.format_rain_hours(3.6), "4 h of rain")

    def test_an_unreadable_temperature_is_left_out(self):
        """One unreadable temperature does not take the other one with it."""
        self.assertEqual(labels.format_temperature("not a number", 8.4),
                         "8°")
        self.assertEqual(labels.format_temperature(11.1, "not a number"),
                         "11°")
        self.assertEqual(labels.format_temperature("not a number",
                                                  "not a number"), "")

    def test_a_temperature_with_no_low_is_only_the_high(self):
        self.assertEqual(labels.format_temperature(14.0, None), "14°")
        self.assertEqual(labels.format_temperature(None, 8.4), "8°")
