"""Lifecycle coordination between the session and a replaceable listener."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from .session import SessionManager


class ListenerBackend(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_alive(self) -> bool: ...


ListenerFactory = Callable[
    [
        Callable[[str | None], None],
        Callable[[], bool],
        Callable[[str], None],
        Callable[[], bool],
        Callable[[], bool],
    ],
    ListenerBackend,
]


class DemoController:
    """Prepares emergency capture before start and releases it on close."""

    def __init__(self, session: SessionManager, listener_factory: ListenerFactory) -> None:
        self.session = session
        self._listener_factory = listener_factory
        self._listener: ListenerBackend | None = None
        self._lock = threading.Lock()
        self._closed = False

    def prepare(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._listener is not None and self._listener.is_alive():
                self.session.set_emergency_ready(True)
                return True
            listener: ListenerBackend | None = None
            try:
                listener = self._listener_factory(
                    self.session.handle_key_press,
                    self.session.emergency_stop,
                    self.session.listener_failed,
                    self.session.is_recording,
                    self.session.records_details,
                )
                listener.start()
                if not listener.is_alive():
                    raise RuntimeError("Слушателят приключи веднага след стартиране.")
                self._listener = listener
            except Exception as exc:
                if listener is not None:
                    try:
                        listener.stop()
                    except Exception:
                        pass
                cause = str(exc).strip()
                detail = (
                    "Глобалният слушател не можа да бъде подготвен "
                    f"({type(exc).__name__})"
                )
                if cause:
                    detail += f": {cause[:300]}"
                else:
                    detail += "."
                self.session.set_emergency_ready(False, detail)
                return False
            self.session.set_emergency_ready(True)
            return True

    def check_listener_health(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._listener is None:
                return False
            healthy = self._listener.is_alive()
        if not healthy:
            self.session.listener_failed(
                "Глобалният слушател е прекратен неочаквано."
            )
        return healthy

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            listener, self._listener = self._listener, None

        # Reject events first, then release the operating-system hook.
        self.session.shutdown()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                # Closing must continue; no captured key value is included here.
                pass
