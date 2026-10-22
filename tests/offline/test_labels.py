"""The labels the page shows for a chance, a date and a temperature.
"""

import re

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
