from __future__ import annotations

import time
import unittest

from keyboard_demo.domain import KeyRecord
from keyboard_demo.lesson import build_synthetic_example
from keyboard_demo.presentation import (
    ReplayModel,
    apply_key_event,
    describe_key,
    format_countdown,
    format_event_time,
    ReconstructionState,
    reconstruct_text,
    summarize_session,
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

    def test_apply_key_event_is_pure(self) -> None:
        original = ReconstructionState("ab", 1)

        changed = apply_key_event(original, "X")

        self.assertEqual(ReconstructionState("ab", 1), original)
        self.assertEqual(ReconstructionState("aXb", 2), changed)


class ReplayModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = (
            KeyRecord(1, 0.1, "a"),
            KeyRecord(2, 0.2, "b"),
            KeyRecord(3, 0.3, "c"),
            KeyRecord(4, 0.4, "[LEFT]"),
            KeyRecord(5, 0.5, "X"),
        )

    def test_frames_support_start_forward_back_jump_and_end(self) -> None:
        replay = ReplayModel(self.records)

        start = replay.frame_at(0)
        forward = replay.frame_at(3)
        backward = replay.frame_at(1)
        end = replay.frame_at(999)

        self.assertEqual((0, "", 0, None), (start.index, start.text, start.cursor, start.record))
        self.assertEqual((3, "abc", 3), (forward.index, forward.text, forward.cursor))
        self.assertEqual((1, "a", 1), (backward.index, backward.text, backward.cursor))
        self.assertEqual((5, "abXc", 3), (end.index, end.text, end.cursor))
        self.assertEqual("X", end.record.display_key)

    def test_synthetic_example_finishes_with_expected_text(self) -> None:
        records = build_synthetic_example()
        replay = ReplayModel(records)

        final = replay.frame_at(replay.total)

        self.assertEqual("Среща в 16:00", final.text)
        self.assertEqual(5, sum(r.display_key == "[BACKSPACE]" for r in records))

    def test_summary_contains_counts_but_no_content(self) -> None:
        records = self.records + (KeyRecord(6, 0.6, "[BACKSPACE]"),)
        summary = summarize_session(
            records,
            total_events=len(records),
            elapsed_seconds=0.6,
            detailed=True,
        )

        self.assertEqual(6, summary.total_events)
        self.assertEqual(4, summary.printable_characters)
        self.assertEqual(1, summary.corrections)
        self.assertEqual(1, summary.special_keys)
        self.assertNotIn("abc", repr(summary))

    def test_count_only_summary_exposes_no_content_categories(self) -> None:
        summary = summarize_session(
            (), total_events=42, elapsed_seconds=12.0, detailed=False
        )

        self.assertEqual(42, summary.total_events)
        self.assertIsNone(summary.printable_characters)
        self.assertIsNone(summary.corrections)
        self.assertIsNone(summary.special_keys)

    def test_5000_event_random_access_stays_responsive(self) -> None:
        records = tuple(
            KeyRecord(index, index / 20, "x") for index in range(1, 5001)
        )
        replay = ReplayModel(records)

        started = time.perf_counter()
        end = replay.frame_at(5000)
        middle = replay.frame_at(2450)
        near_end = replay.frame_at(4999)
        elapsed = time.perf_counter() - started

        self.assertEqual(5000, len(end.text))
        self.assertEqual(2450, len(middle.text))
        self.assertEqual(4999, len(near_end.text))
        self.assertLess(elapsed, 3.0)


if __name__ == "__main__":
    unittest.main()
