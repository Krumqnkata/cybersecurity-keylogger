"""Windows global key listener. Importing this module never starts capture."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any


class GlobalKeyboardListener:
    """One visible-app-lifetime listener with capture gated by SessionManager."""

    def __init__(
        self,
        on_key_press: Callable[[str | None], None],
        on_emergency: Callable[[], bool],
        on_failure: Callable[[str], None],
        is_recording: Callable[[], bool],
        records_details: Callable[[], bool],
    ) -> None:
        self._on_key_press = on_key_press
        self._on_emergency = on_emergency
        self._on_failure = on_failure
        self._is_recording = is_recording
        self._records_details = records_details
        self._listener: Any | None = None
        self._keyboard: Any | None = None
        self._ctrl_down = False
        self._alt_down = False
        self._state_lock = threading.Lock()

    def start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Глобалната демонстрация е предназначена за Windows.")
        from pynput import keyboard

        self._keyboard = keyboard
        listener = keyboard.Listener(
            on_press=self._safe_press,
            on_release=self._safe_release,
        )
        self._listener = listener
        listener.start()
        listener.wait()

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()
            if listener is not threading.current_thread():
                listener.join(timeout=1.5)
        with self._state_lock:
            self._ctrl_down = False
            self._alt_down = False

    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def _safe_press(self, key: Any, *_metadata: Any) -> None:
        try:
            is_q = self._update_press_state(key)
            with self._state_lock:
                emergency = self._ctrl_down and self._alt_down and is_q
            if emergency:
                self._on_emergency()
                return
            if not self._is_recording():
                return
            if self._records_details():
                self._on_key_press(self._display_name(key))
            else:
                # Counter mode deliberately does not convert or forward content.
                self._on_key_press(None)
        except Exception as exc:
            self._on_failure(
                "Обработката на клавишно събитие се провали "
                f"(тип: {type(exc).__name__})."
            )

    def _safe_release(self, key: Any, *_metadata: Any) -> None:
        try:
            keyboard = self._keyboard
            if keyboard is None:
                return
            with self._state_lock:
                if key in self._ctrl_keys(keyboard):
                    self._ctrl_down = False
                if key in self._alt_keys(keyboard):
                    self._alt_down = False
        except Exception as exc:
            self._on_failure(
                "Обработката на отпускане на клавиш се провали "
                f"(тип: {type(exc).__name__})."
            )

    def _update_press_state(self, key: Any) -> bool:
        keyboard = self._keyboard
        if keyboard is None:
            return False
        with self._state_lock:
            if key in self._ctrl_keys(keyboard):
                self._ctrl_down = True
            if key in self._alt_keys(keyboard):
                self._alt_down = True
        char = getattr(key, "char", None)
        # VK_Q remains stable even when Ctrl/Alt changes the reported character.
        return (isinstance(char, str) and char.casefold() == "q") or getattr(
            key, "vk", None
        ) == 0x51

    @staticmethod
    def _ctrl_keys(keyboard: Any) -> set[Any]:
        return {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}

    @staticmethod
    def _alt_keys(keyboard: Any) -> set[Any]:
        return {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}

    def _display_name(self, key: Any) -> str:
        keyboard = self._keyboard
        if keyboard is None:
            return "[НЕИЗВЕСТЕН]"

        groups = (
            ((keyboard.Key.space,), "[SPACE]"),
            ((keyboard.Key.enter,), "[ENTER]"),
            ((keyboard.Key.backspace,), "[BACKSPACE]"),
            ((keyboard.Key.tab,), "[TAB]"),
            (tuple(self._ctrl_keys(keyboard)), "[CTRL]"),
            (tuple(self._alt_keys(keyboard)), "[ALT]"),
            ((keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r), "[SHIFT]"),
            ((keyboard.Key.left,), "[LEFT]"),
            ((keyboard.Key.right,), "[RIGHT]"),
            ((keyboard.Key.up,), "[UP]"),
            ((keyboard.Key.down,), "[DOWN]"),
            ((keyboard.Key.delete,), "[DELETE]"),
            ((keyboard.Key.esc,), "[ESC]"),
            ((keyboard.Key.home,), "[HOME]"),
            ((keyboard.Key.end,), "[END]"),
            ((keyboard.Key.page_up,), "[PAGE UP]"),
            ((keyboard.Key.page_down,), "[PAGE DOWN]"),
        )
        for candidates, label in groups:
            if key in candidates:
                return label

        char = getattr(key, "char", None)
        if isinstance(char, str) and char:
            if char == " ":
                return "[SPACE]"
            if char.isprintable():
                return char

        name = getattr(key, "name", None)
        if isinstance(name, str) and name:
            return f"[{name.replace('_', ' ').upper()}]"
        return "[НЕИЗВЕСТЕН]"
