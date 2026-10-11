"""Built-in synthetic lesson data; no listener or timer is involved."""

from __future__ import annotations

from .domain import KeyRecord


def build_synthetic_example() -> tuple[KeyRecord, ...]:
    keys: list[str] = []
    for character in "Среща в 15:00":
        keys.append("[SPACE]" if character == " " else character)
    keys.extend(["[BACKSPACE]"] * 5)
    keys.extend("16:00")
    return tuple(
        KeyRecord(sequence, sequence * 0.28, key)
        for sequence, key in enumerate(keys, start=1)
    )
