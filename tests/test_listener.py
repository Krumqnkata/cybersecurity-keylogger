from __future__ import annotations

import types
import unittest

from keyboard_demo.listener import GlobalKeyboardListener


class CharacterKey:
    def __init__(self, char: str, vk: int | None = None) -> None:
        self.char = char
        self.vk = vk


class FakeKeyboard:
    Key = types.SimpleNamespace(
        ctrl=object(),
        ctrl_l=object(),
        ctrl_r=object(),
        alt=object(),
        alt_l=object(),
        alt_r=object(),
        alt_gr=object(),
        space=object(),
        enter=object(),
        backspace=object(),
        tab=object(),
        shift=object(),
        shift_l=object(),
        shift_r=object(),
        left=object(),
        right=object(),
        up=object(),
        down=object(),
        delete=object(),
        esc=object(),
        home=object(),
        end=object(),
        page_up=object(),
        page_down=object(),
    )


def synthetic_listener(*, detailed: bool = True):
    captured: list[str | None] = []
    emergencies: list[bool] = []
    failures: list[str] = []
    listener = GlobalKeyboardListener(
        captured.append,
        lambda: emergencies.append(True) or True,
        failures.append,
        lambda: True,
        lambda: detailed,
    )
    listener._keyboard = FakeKeyboard  # Synthetic adapter; no OS hook is created.
    return listener, captured, emergencies, failures


class GlobalKeyboardListenerTests(unittest.TestCase):
    def test_ctrl_alt_q_calls_emergency_directly_and_does_not_capture_q(self) -> None:
        listener, captured, emergencies, failures = synthetic_listener()

        listener._safe_press(FakeKeyboard.Key.ctrl_l, False)
        listener._safe_press(FakeKeyboard.Key.alt_r, False)
        listener._safe_press(CharacterKey("q"), False)

        self.assertEqual([True], emergencies)
        self.assertEqual(["[CTRL]", "[ALT]"], captured)
        self.assertEqual([], failures)

    def test_counter_mode_never_formats_or_forwards_key_content(self) -> None:
        listener, captured, emergencies, failures = synthetic_listener(detailed=False)

        def forbidden(_key):
            raise AssertionError("content formatter must not run")

        listener._display_name = forbidden
        listener._safe_press(CharacterKey("S"), "injected metadata is ignored")

        self.assertEqual([None], captured)
        self.assertEqual([], emergencies)
        self.assertEqual([], failures)

    def test_release_is_not_forwarded_as_a_second_event(self) -> None:
        listener, captured, _, failures = synthetic_listener()
        key = CharacterKey("a")

        listener._safe_press(key)
        listener._safe_release(key)

        self.assertEqual(["a"], captured)
        self.assertEqual([], failures)

    def test_release_clears_hotkey_modifier_state(self) -> None:
        listener, _, emergencies, failures = synthetic_listener()

        listener._safe_press(FakeKeyboard.Key.ctrl)
        listener._safe_press(FakeKeyboard.Key.alt)
        listener._safe_release(FakeKeyboard.Key.alt)
        listener._safe_press(CharacterKey("q"))

        self.assertEqual([], emergencies)
        self.assertEqual([], failures)

    def test_virtual_q_key_still_triggers_when_modifiers_change_character(self) -> None:
        listener, _, emergencies, failures = synthetic_listener()

        listener._safe_press(FakeKeyboard.Key.ctrl_l)
        listener._safe_press(FakeKeyboard.Key.alt_l)
        listener._safe_press(CharacterKey("@", vk=0x51))

        self.assertEqual([True], emergencies)
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
