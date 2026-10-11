"""Human-friendly formatting that does not reconstruct entered text."""

from __future__ import annotations

from collections.abc import Iterable


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


def reconstruct_text(display_keys: Iterable[str]) -> str:
    """Rebuild the linear text implied by the received event sequence."""
    buffer: list[str] = []
    cursor = 0
    inserted = {
        "[SPACE]": " ",
        "[ENTER]": "\n",
        "[TAB]": "\t",
    }
    ignored = {
        "[SHIFT]",
        "[CTRL]",
        "[ALT]",
        "[ESC]",
        "[PAGE UP]",
        "[PAGE DOWN]",
        "[НЕИЗВЕСТЕН]",
    }

    for key in display_keys:
        if len(key) == 1 and key.isprintable():
            buffer.insert(cursor, key)
            cursor += 1
        elif key in inserted:
            buffer.insert(cursor, inserted[key])
            cursor += 1
        elif key == "[BACKSPACE]" and cursor > 0:
            cursor -= 1
            buffer.pop(cursor)
        elif key == "[DELETE]" and cursor < len(buffer):
            buffer.pop(cursor)
        elif key == "[LEFT]":
            cursor = max(0, cursor - 1)
        elif key == "[RIGHT]":
            cursor = min(len(buffer), cursor + 1)
        elif key == "[HOME]":
            cursor = _line_start(buffer, cursor)
        elif key == "[END]":
            cursor = _line_end(buffer, cursor)
        elif key == "[UP]":
            cursor = _move_vertical(buffer, cursor, -1)
        elif key == "[DOWN]":
            cursor = _move_vertical(buffer, cursor, 1)
        elif key in ignored or (key.startswith("[") and key.endswith("]")):
            continue

    return "".join(buffer)


def _line_start(buffer: list[str], cursor: int) -> int:
    try:
        return len(buffer) - 1 - buffer[::-1].index("\n", len(buffer) - cursor) + 1
    except ValueError:
        return 0


def _line_end(buffer: list[str], cursor: int) -> int:
    try:
        return buffer.index("\n", cursor)
    except ValueError:
        return len(buffer)


def _move_vertical(buffer: list[str], cursor: int, direction: int) -> int:
    current_start = _line_start(buffer, cursor)
    column = cursor - current_start
    if direction < 0:
        if current_start == 0:
            return cursor
        previous_end = current_start - 1
        previous_start = _line_start(buffer, previous_end)
        return previous_start + min(column, previous_end - previous_start)

    current_end = _line_end(buffer, cursor)
    if current_end >= len(buffer):
        return cursor
    next_start = current_end + 1
    next_end = _line_end(buffer, next_start)
    return next_start + min(column, next_end - next_start)
