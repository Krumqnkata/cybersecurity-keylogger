"""Thread-safe session state and deliberately small key-event processing."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable, Sequence

from .domain import (
    CaptureMode,
    GuiNotification,
    KeyCaptured,
    KeyRecord,
    SessionOrigin,
    SessionSnapshot,
    SessionStarted,
    SessionState,
    SessionStopped,
    StopReason,
)


class SessionStartError(RuntimeError):
    """Raised when a bounded session cannot be started safely."""


class SessionManager:
    """Owns capture state; it never calls Tkinter and never writes captured data."""

    ALLOWED_DURATIONS = (60, 120, 300)
    DEFAULT_JOURNAL_LIMIT = 5000
    DEFAULT_QUEUE_CAPACITY = DEFAULT_JOURNAL_LIMIT + 20

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        journal_limit: int = DEFAULT_JOURNAL_LIMIT,
        notification_capacity: int = DEFAULT_QUEUE_CAPACITY,
        watchdog_enabled: bool = True,
    ) -> None:
        self._clock = clock
        self._journal_limit = journal_limit
        self._watchdog_enabled = watchdog_enabled
        self.notifications: queue.Queue[GuiNotification] = queue.Queue(
            maxsize=notification_capacity
        )
        self._lock = threading.RLock()
        self._state = SessionState.READY
        self._mode = CaptureMode.EVENTS
        self._origin = SessionOrigin.LIVE
        self._duration = 120
        self._session_id = 0
        self._started_at = 0.0
        self._deadline = 0.0
        self._remaining_at_stop = 120.0
        self._elapsed_at_stop = 0.0
        self._event_count = 0
        self._journal: list[KeyRecord] = []
        self._stop_reason: StopReason | None = None
        self._emergency_ready = False
        self._error_detail = ""
        self._timer: threading.Timer | None = None
        self._closed = False

    def set_emergency_ready(self, ready: bool, detail: str = "") -> None:
        with self._lock:
            self._emergency_ready = ready
            self._error_detail = "" if ready else detail
            if not ready and self._state is SessionState.RECORDING:
                self._finish_locked(StopReason.LISTENER_ERROR, detail)

    def start(self, duration_seconds: int) -> int:
        if duration_seconds not in self.ALLOWED_DURATIONS:
            raise SessionStartError("Продължителността трябва да е 1, 2 или 5 минути.")

        with self._lock:
            if self._closed:
                raise SessionStartError("Приложението вече се затваря.")
            if not self._emergency_ready:
                detail = self._error_detail or "Глобалното аварийно спиране не е готово."
                raise SessionStartError(detail)
            if self._state is SessionState.RECORDING:
                raise SessionStartError("Вече има активна записваща сесия.")

            # No listener can add ordinary events while the state is not RECORDING.
            self._drain_notifications_locked()
            self._cancel_timer_locked()
            self._session_id += 1
            self._duration = duration_seconds
            self._origin = SessionOrigin.LIVE
            self._started_at = self._clock()
            self._deadline = self._started_at + duration_seconds
            self._remaining_at_stop = float(duration_seconds)
            self._elapsed_at_stop = 0.0
            self._event_count = 0
            self._journal.clear()
            self._stop_reason = None
            self._error_detail = ""
            self._state = SessionState.RECORDING
            self._emit_locked(
                SessionStarted(self._session_id, self._mode, self._duration)
            )
            self._start_timer_locked()
            return self._session_id

    def handle_key_press(self, display_key: str | None) -> None:
        """Handle one press signal; release signals are intentionally not supplied."""
        with self._lock:
            if self._state is not SessionState.RECORDING:
                return
            now = self._clock()
            if now >= self._deadline:
                self._finish_locked(StopReason.TIMEOUT)
                return

            self._event_count += 1
            if self._mode is CaptureMode.COUNT_ONLY:
                # Privacy rule: do not retain or enqueue the key value or a timeline.
                return

            record = KeyRecord(
                sequence=self._event_count,
                elapsed_seconds=max(0.0, now - self._started_at),
                display_key=display_key if display_key is not None else "[НЕИЗВЕСТЕН]",
            )
            self._journal.append(record)
            if not self._emit_locked(KeyCaptured(self._session_id, record)):
                self._finish_locked(
                    StopReason.LISTENER_ERROR,
                    "Ограничената опашка към интерфейса се запълни.",
                )
                return
            if len(self._journal) >= self._journal_limit:
                self._finish_locked(StopReason.LIMIT)

    def stop(self, reason: StopReason = StopReason.USER) -> bool:
        with self._lock:
            if self._state is not SessionState.RECORDING:
                return False
            self._finish_locked(reason)
            return True

    def emergency_stop(self) -> bool:
        """Called directly by the listener thread; it does not wait for Tkinter."""
        return self.stop(StopReason.EMERGENCY)

    def check_timeout(self) -> bool:
        with self._lock:
            if (
                self._state is SessionState.RECORDING
                and self._clock() >= self._deadline
            ):
                self._finish_locked(StopReason.TIMEOUT)
                return True
            return False

    def listener_failed(self, detail: str) -> None:
        with self._lock:
            self._emergency_ready = False
            self._error_detail = detail
            if self._state is SessionState.RECORDING:
                self._finish_locked(StopReason.LISTENER_ERROR, detail)

    def load_synthetic(self, records: Sequence[KeyRecord]) -> int:
        """Load a stopped in-memory lesson result without starting capture."""
        if len(records) > self._journal_limit:
            raise ValueError("Синтетичният пример надвишава лимита на журнала.")

        normalized: list[KeyRecord] = []
        previous_time = 0.0
        for sequence, record in enumerate(records, start=1):
            if record.elapsed_seconds < previous_time:
                raise ValueError("Времената в синтетичния пример не са подредени.")
            if not isinstance(record.display_key, str) or not record.display_key:
                raise ValueError("Синтетичният пример съдържа невалиден клавиш.")
            previous_time = record.elapsed_seconds
            normalized.append(
                KeyRecord(sequence, record.elapsed_seconds, record.display_key)
            )

        with self._lock:
            if self._closed:
                raise SessionStartError("Приложението вече се затваря.")
            if self._state is SessionState.RECORDING:
                self._finish_locked(StopReason.CLEARED)
            self._cancel_timer_locked()
            self._drain_notifications_locked()
            self._session_id += 1
            self._mode = CaptureMode.EVENTS
            self._origin = SessionOrigin.SYNTHETIC
            self._journal = normalized
            self._event_count = len(normalized)
            self._elapsed_at_stop = previous_time
            self._remaining_at_stop = 0.0
            self._state = SessionState.STOPPED
            self._stop_reason = StopReason.SYNTHETIC_EXAMPLE
            self._emit_locked(
                SessionStopped(
                    self._session_id,
                    StopReason.SYNTHETIC_EXAMPLE,
                )
            )
            return self._session_id

    def reset(self, *, mode: CaptureMode | None = None) -> None:
        """Stop first, then remove all in-memory data and pending GUI messages."""
        with self._lock:
            if self._state is SessionState.RECORDING:
                self._finish_locked(
                    StopReason.MODE_CHANGED if mode is not None else StopReason.CLEARED
                )
            self._cancel_timer_locked()
            if mode is not None:
                self._mode = mode
            self._event_count = 0
            self._journal.clear()
            self._origin = SessionOrigin.LIVE
            self._stop_reason = None
            self._error_detail = "" if self._emergency_ready else self._error_detail
            self._remaining_at_stop = float(self._duration)
            self._elapsed_at_stop = 0.0
            self._state = SessionState.READY
            self._drain_notifications_locked()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._state is SessionState.RECORDING:
                self._finish_locked(StopReason.CLOSED)
            self._closed = True
            self._cancel_timer_locked()
            self._event_count = 0
            self._journal.clear()
            self._drain_notifications_locked()

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            if self._state is SessionState.RECORDING:
                remaining = max(0.0, self._deadline - self._clock())
                elapsed = min(
                    float(self._duration), max(0.0, self._clock() - self._started_at)
                )
            else:
                remaining = max(0.0, self._remaining_at_stop)
                elapsed = max(0.0, self._elapsed_at_stop)
            return SessionSnapshot(
                session_id=self._session_id,
                state=self._state,
                mode=self._mode,
                origin=self._origin,
                duration_seconds=self._duration,
                elapsed_seconds=elapsed,
                remaining_seconds=remaining,
                event_count=self._event_count,
                stop_reason=self._stop_reason,
                emergency_ready=self._emergency_ready,
                error_detail=self._error_detail,
            )

    def journal(self) -> tuple[KeyRecord, ...]:
        with self._lock:
            return tuple(self._journal)

    def is_recording(self) -> bool:
        with self._lock:
            return self._state is SessionState.RECORDING

    def records_details(self) -> bool:
        with self._lock:
            return (
                self._state is SessionState.RECORDING
                and self._mode is CaptureMode.EVENTS
            )

    def _finish_locked(self, reason: StopReason, detail: str = "") -> None:
        if self._state is not SessionState.RECORDING:
            return
        self._remaining_at_stop = max(0.0, self._deadline - self._clock())
        self._elapsed_at_stop = min(
            float(self._duration), max(0.0, self._clock() - self._started_at)
        )
        self._state = SessionState.STOPPED
        self._stop_reason = reason
        if detail:
            self._error_detail = detail
        self._cancel_timer_locked()
        self._emit_locked(SessionStopped(self._session_id, reason, detail))

    def _start_timer_locked(self) -> None:
        if not self._watchdog_enabled:
            return
        timer = threading.Timer(
            self._duration, self._watchdog_expired, args=(self._session_id,)
        )
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _watchdog_expired(self, session_id: int) -> None:
        with self._lock:
            if (
                not self._closed
                and self._state is SessionState.RECORDING
                and self._session_id == session_id
            ):
                self._finish_locked(StopReason.TIMEOUT)

    def _cancel_timer_locked(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def _emit_locked(self, message: GuiNotification) -> bool:
        try:
            self.notifications.put_nowait(message)
            return True
        except queue.Full:
            return False

    def _drain_notifications_locked(self) -> None:
        while True:
            try:
                self.notifications.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def rounded_remaining(snapshot: SessionSnapshot) -> int:
        return int(math.ceil(snapshot.remaining_seconds))
