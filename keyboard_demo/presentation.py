"""Human-friendly formatting, summaries, and in-memory lesson replay."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .domain import KeyRecord


SPECIAL_KEY_NAMES = {
    "[SPACE]": "Интервал",
    "[ENTER]": "Enter — нов ред или потвърждение",
    "[BACKSPACE]": "Backspace — изтриване назад",
    "[TAB]": "Tab — табулация или следващо поле",
    "[SHIFT]": "Shift — модификатор",
    "[CTRL]": "Ctrl — модификатор",
    "[ALT]": "Alt — модификатор",
    "[LEFT]": "Стрелка наляво",
    "[RIGHT]": "Стрелка надясно",
    "[UP]": "Стрелка нагоре",
    "[DOWN]": "Стрелка надолу",
    "[DELETE]": "Delete — изтриване напред",
    "[ESC]": "Escape",
    "[HOME]": "Home — начало",
    "[END]": "End — край",
    "[PAGE UP]": "Page Up — страница нагоре",
    "[PAGE DOWN]": "Page Down — страница надолу",
    "[НЕИЗВЕСТЕН]": "Неразпознат клавиш",
}


@dataclass(frozen=True, slots=True)
class ReconstructionState:
    text: str = ""
    cursor: int = 0


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    index: int
    total: int
    text: str
    cursor: int
    record: KeyRecord | None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    total_events: int
    elapsed_seconds: float
    printable_characters: int | None
    corrections: int | None
    special_keys: int | None


def format_event_time(elapsed_seconds: float) -> str:
    """Format relative event time as mm:ss.t for quick projector reading."""
    safe_seconds = max(0.0, elapsed_seconds)
    minutes = int(safe_seconds // 60)
    seconds = safe_seconds - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def format_countdown(total_seconds: int) -> str:
    """Format a non-negative countdown as mm:ss."""
    safe_seconds = max(0, total_seconds)
    minutes, seconds = divmod(safe_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def describe_key(display_key: str) -> str:
    """Describe one event without combining it with neighbouring events."""
    known_name = SPECIAL_KEY_NAMES.get(display_key)
    if known_name is not None:
        return known_name
    if len(display_key) == 1 and display_key.isprintable():
        return f"Символ „{display_key}“"
    if display_key.startswith("[") and display_key.endswith("]"):
        return f"Специален клавиш {display_key}"
    return f"Получен клавиш: {display_key}"


def apply_key_event(state: ReconstructionState, display_key: str) -> ReconstructionState:
    """Return a new reconstruction state after applying one received event."""
    text, cursor = state.text, state.cursor
    inserted = {"[SPACE]": " ", "[ENTER]": "\n", "[TAB]": "\t"}

    if len(display_key) == 1 and display_key.isprintable():
        return _insert(state, display_key)
    if display_key in inserted:
        return _insert(state, inserted[display_key])
    if display_key == "[BACKSPACE]" and cursor > 0:
        return ReconstructionState(text[: cursor - 1] + text[cursor:], cursor - 1)
    if display_key == "[DELETE]" and cursor < len(text):
        return ReconstructionState(text[:cursor] + text[cursor + 1 :], cursor)
    if display_key == "[LEFT]":
        return ReconstructionState(text, max(0, cursor - 1))
    if display_key == "[RIGHT]":
        return ReconstructionState(text, min(len(text), cursor + 1))
    if display_key == "[HOME]":
        return ReconstructionState(text, _line_start(text, cursor))
    if display_key == "[END]":
        return ReconstructionState(text, _line_end(text, cursor))
    if display_key == "[UP]":
        return ReconstructionState(text, _move_vertical(text, cursor, -1))
    if display_key == "[DOWN]":
        return ReconstructionState(text, _move_vertical(text, cursor, 1))
    return state


def reconstruct_text(display_keys: Iterable[str]) -> str:
    state = ReconstructionState()
    for key in display_keys:
        state = apply_key_event(state, key)
    return state.text


def summarize_session(
    records: Sequence[KeyRecord],
    *,
    total_events: int,
    elapsed_seconds: float,
    detailed: bool,
) -> SessionSummary:
    """Build a content-free summary; count-only details stay unavailable."""
    if not detailed:
        return SessionSummary(total_events, elapsed_seconds, None, None, None)
    printable = sum(
        1 for record in records if len(record.display_key) == 1 and record.display_key.isprintable()
    )
    corrections = sum(
        1 for record in records if record.display_key in {"[BACKSPACE]", "[DELETE]"}
    )
    return SessionSummary(
        total_events,
        elapsed_seconds,
        printable,
        corrections,
        max(0, total_events - printable - corrections),
    )


class ReplayModel:
    """Random-access replay with sparse checkpoints for responsive sliders."""

    CHECKPOINT_INTERVAL = 100

    def __init__(self, records: Sequence[KeyRecord]) -> None:
        self.records = tuple(records)
        self._checkpoints: dict[int, ReconstructionState] = {
            0: ReconstructionState()
        }
        self._current_index = 0
        self._current_state = ReconstructionState()

    @property
    def total(self) -> int:
        return len(self.records)

    def frame_at(self, index: int) -> ReplayFrame:
        target = max(0, min(self.total, int(index)))
        if target >= self._current_index:
            start = self._current_index
            state = self._current_state
        else:
            start = max(item for item in self._checkpoints if item <= target)
            state = self._checkpoints[start]

        for position in range(start, target):
            state = apply_key_event(state, self.records[position].display_key)
            completed = position + 1
            if completed % self.CHECKPOINT_INTERVAL == 0:
                self._checkpoints[completed] = state

        self._current_index = target
        self._current_state = state
        record = self.records[target - 1] if target else None
        return ReplayFrame(target, self.total, state.text, state.cursor, record)


def _insert(state: ReconstructionState, value: str) -> ReconstructionState:
    text, cursor = state.text, state.cursor
    return ReconstructionState(text[:cursor] + value + text[cursor:], cursor + len(value))


def _line_start(text: str, cursor: int) -> int:
    return text.rfind("\n", 0, cursor) + 1


def _line_end(text: str, cursor: int) -> int:
    result = text.find("\n", cursor)
    return len(text) if result < 0 else result


def _move_vertical(text: str, cursor: int, direction: int) -> int:
    current_start = _line_start(text, cursor)
    column = cursor - current_start
    if direction < 0:
        if current_start == 0:
            return cursor
        previous_end = current_start - 1
        previous_start = _line_start(text, previous_end)
        return previous_start + min(column, previous_end - previous_start)

    current_end = _line_end(text, cursor)
    if current_end >= len(text):
        return cursor
    next_start = current_end + 1
    next_end = _line_end(text, next_start)
    return next_start + min(column, next_end - next_start)
