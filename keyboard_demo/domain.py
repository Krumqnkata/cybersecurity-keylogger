"""Small immutable types shared by the capture core and the interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaptureMode(str, Enum):
    EVENTS = "events"
    COUNT_ONLY = "count_only"

    @property
    def bulgarian_name(self) -> str:
        if self is CaptureMode.EVENTS:
            return "Клавишни събития"
        return "Само брояч"


class SessionState(str, Enum):
    READY = "ready"
    RECORDING = "recording"
    STOPPED = "stopped"

    @property
    def bulgarian_name(self) -> str:
        return {
            SessionState.READY: "ГОТОВНОСТ",
            SessionState.RECORDING: "ЗАПИС",
            SessionState.STOPPED: "СПРЯНО",
        }[self]


class StopReason(str, Enum):
    USER = "user"
    TIMEOUT = "timeout"
    EMERGENCY = "emergency"
    LIMIT = "limit"
    MINIMIZED = "minimized"
    MODE_CHANGED = "mode_changed"
    QUESTIONS_OPENED = "questions_opened"
    CLEARED = "cleared"
    LISTENER_ERROR = "listener_error"
    CLOSED = "closed"

    @property
    def bulgarian_message(self) -> str:
        return {
            StopReason.USER: "Записът е спрян от водещия.",
            StopReason.TIMEOUT: "Времето изтече и записът спря автоматично.",
            StopReason.EMERGENCY: "Записът е спрян с Ctrl+Alt+Q.",
            StopReason.LIMIT: "Достигнат е лимитът от 5000 събития.",
            StopReason.MINIMIZED: "Записът спря, защото контролният прозорец беше минимизиран.",
            StopReason.MODE_CHANGED: "Сесията е прекратена при смяна на режима.",
            StopReason.QUESTIONS_OPENED: "Записът спря преди отваряне на въпросите.",
            StopReason.CLEARED: "Данните са изчистени.",
            StopReason.LISTENER_ERROR: "Записът спря поради проблем със слушателя.",
            StopReason.CLOSED: "Приложението се затваря.",
        }[self]


@dataclass(frozen=True, slots=True)
class KeyRecord:
    sequence: int
    elapsed_seconds: float
    display_key: str


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: int
    state: SessionState
    mode: CaptureMode
    duration_seconds: int
    remaining_seconds: float
    event_count: int
    stop_reason: StopReason | None
    emergency_ready: bool
    error_detail: str


@dataclass(frozen=True, slots=True)
class SessionStarted:
    session_id: int
    mode: CaptureMode
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class KeyCaptured:
    session_id: int
    record: KeyRecord


@dataclass(frozen=True, slots=True)
class SessionStopped:
    session_id: int
    reason: StopReason
    detail: str = ""


GuiNotification = SessionStarted | KeyCaptured | SessionStopped
