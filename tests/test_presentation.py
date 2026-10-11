from __future__ import annotations

import unittest

from keyboard_demo.presentation import (
    describe_key,
    format_countdown,
    format_event_time,
    reconstruct_text,
)


class PresentationFormattingTests(unittest.TestCase):
    def test_event_time_is_readable_across_minutes(self) -> None:
        self.assertEqual("00:00.0", format_event_time(0))
        self.assertEqual("02:05.4", format_event_time(125.4))

    def test_countdown_uses_minutes_and_seconds(self) -> None:
        self.assertEqual("05:00", format_countdown(300))
        self.assertEqual("01:01", format_countdown(61))
        self.assertEqual("00:00", format_countdown(-1))

    def test_key_descriptions_are_bulgarian_but_remain_individual_events(self) -> None:
        self.assertEqual("Символ „Ж“", describe_key("Ж"))
        self.assertEqual("Backspace — изтриване назад", describe_key("[BACKSPACE]"))
        self.assertEqual("Стрелка наляво", describe_key("[LEFT]"))
        self.assertEqual("Специален клавиш [F8]", describe_key("[F8]"))

    def test_reconstruction_applies_characters_whitespace_and_backspace(self) -> None:
        keys = ["З", "д", "р", "а", "в", "е", "й", "[BACKSPACE]", "!", "[ENTER]", "О", "К"]

        self.assertEqual("Здраве!\nОК", reconstruct_text(keys))

    def test_reconstruction_applies_cursor_navigation_and_delete(self) -> None:
        keys = ["a", "b", "c", "[LEFT]", "[BACKSPACE]", "X", "[RIGHT]", "[LEFT]", "[DELETE]"]

        self.assertEqual("aX", reconstruct_text(keys))

    def test_reconstruction_handles_home_end_and_vertical_movement(self) -> None:
        keys = ["a", "b", "[ENTER]", "c", "d", "[HOME]", "X", "[UP]", "Y", "[END]", "!"]

        self.assertEqual("aYb!\nXcd", reconstruct_text(keys))


if __name__ == "__main__":
    unittest.main()
