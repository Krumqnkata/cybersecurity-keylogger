from __future__ import annotations

import queue
import unittest

from keyboard_demo.controller import DemoController
from keyboard_demo.domain import CaptureMode, KeyCaptured, SessionState, StopReason
from keyboard_demo.session import SessionManager, SessionStartError


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def ready_manager(*, limit: int = 5000) -> tuple[SessionManager, FakeClock]:
    clock = FakeClock()
    manager = SessionManager(
        clock=clock,
        journal_limit=limit,
        notification_capacity=limit + 20,
        watchdog_enabled=False,
    )
    manager.set_emergency_ready(True)
    return manager, clock


class SessionManagerTests(unittest.TestCase):
    def test_start_stop_and_no_events_after_stop(self) -> None:
        manager, clock = ready_manager()
        session_id = manager.start(60)
        clock.advance(0.25)
        manager.handle_key_press("а")
        self.assertTrue(manager.stop())
        manager.handle_key_press("б")

        snapshot = manager.snapshot()
        self.assertEqual(session_id, snapshot.session_id)
        self.assertEqual(SessionState.STOPPED, snapshot.state)
        self.assertEqual(1, snapshot.event_count)
        self.assertEqual(["а"], [item.display_key for item in manager.journal()])

    def test_automatic_timeout_uses_monotonic_clock(self) -> None:
        manager, clock = ready_manager()
        manager.start(60)
        clock.advance(60)

        self.assertTrue(manager.check_timeout())
        self.assertEqual(SessionState.STOPPED, manager.snapshot().state)
        self.assertEqual(StopReason.TIMEOUT, manager.snapshot().stop_reason)

    def test_emergency_stop_is_immediate_core_transition(self) -> None:
        manager, _ = ready_manager()
        manager.start(60)

        self.assertTrue(manager.emergency_stop())
        self.assertEqual(SessionState.STOPPED, manager.snapshot().state)
        self.assertEqual(StopReason.EMERGENCY, manager.snapshot().stop_reason)

    def test_detailed_journal_stops_at_limit(self) -> None:
        manager, _ = ready_manager(limit=3)
        manager.start(60)
        for key in ("a", "b", "c", "d"):
            manager.handle_key_press(key)

        self.assertEqual(SessionState.STOPPED, manager.snapshot().state)
        self.assertEqual(StopReason.LIMIT, manager.snapshot().stop_reason)
        self.assertEqual(3, manager.snapshot().event_count)
        self.assertEqual(3, len(manager.journal()))

    def test_count_only_keeps_no_symbols_timeline_or_key_messages(self) -> None:
        manager, clock = ready_manager()
        manager.reset(mode=CaptureMode.COUNT_ONLY)
        manager.start(60)
        clock.advance(1)
        manager.handle_key_press("Secret-42")
        clock.advance(1)
        manager.handle_key_press("[ENTER]")

        self.assertEqual(2, manager.snapshot().event_count)
        self.assertEqual((), manager.journal())
        messages = []
        while True:
            try:
                messages.append(manager.notifications.get_nowait())
            except queue.Empty:
                break
        self.assertFalse(any(isinstance(item, KeyCaptured) for item in messages))

    def test_clear_removes_data_and_pending_queue(self) -> None:
        manager, _ = ready_manager()
        manager.start(60)
        manager.handle_key_press("x")
        manager.reset()

        self.assertEqual(SessionState.READY, manager.snapshot().state)
        self.assertEqual(0, manager.snapshot().event_count)
        self.assertEqual((), manager.journal())
        with self.assertRaises(queue.Empty):
            manager.notifications.get_nowait()

    def test_consecutive_sessions_are_isolated(self) -> None:
        manager, _ = ready_manager()
        first_id = manager.start(60)
        manager.handle_key_press("old")
        manager.stop()
        second_id = manager.start(60)
        manager.handle_key_press("new")

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(["new"], [item.display_key for item in manager.journal()])
        queued = []
        while True:
            try:
                queued.append(manager.notifications.get_nowait())
            except queue.Empty:
                break
        self.assertTrue(all(item.session_id == second_id for item in queued))

    def test_start_refused_without_emergency_stop(self) -> None:
        manager = SessionManager(watchdog_enabled=False)
        manager.set_emergency_ready(False, "Аварийното спиране липсва.")

        with self.assertRaises(SessionStartError):
            manager.start(60)
        self.assertEqual(SessionState.READY, manager.snapshot().state)

    def test_second_concurrent_session_and_unbounded_duration_are_refused(self) -> None:
        manager, _ = ready_manager()
        manager.start(60)

        with self.assertRaises(SessionStartError):
            manager.start(60)
        manager.stop()
        with self.assertRaises(SessionStartError):
            manager.start(301)

    def test_two_and_five_minute_sessions_are_available(self) -> None:
        manager, _ = ready_manager()

        manager.start(120)
        self.assertEqual(120, manager.snapshot().duration_seconds)
        manager.stop()
        manager.start(300)
        self.assertEqual(300, manager.snapshot().duration_seconds)


class FakeListener:
    def __init__(self, *callbacks) -> None:
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.started = False

    def is_alive(self) -> bool:
        return self.started


class ControllerLifecycleTests(unittest.TestCase):
    def test_close_releases_listener_and_clears_session_data(self) -> None:
        manager = SessionManager(watchdog_enabled=False)
        holder: dict[str, FakeListener] = {}

        def factory(*callbacks):
            listener = FakeListener(*callbacks)
            holder["listener"] = listener
            return listener

        controller = DemoController(manager, factory)
        self.assertTrue(controller.prepare())
        manager.start(60)
        manager.handle_key_press("x")

        controller.close()

        self.assertTrue(holder["listener"].stopped)
        self.assertEqual(0, manager.snapshot().event_count)
        self.assertEqual((), manager.journal())

    def test_failed_preparation_releases_partial_listener_and_blocks_start(self) -> None:
        manager = SessionManager(watchdog_enabled=False)

        class BrokenListener(FakeListener):
            def start(self) -> None:
                self.started = True
                raise RuntimeError("synthetic setup failure")

        holder: dict[str, BrokenListener] = {}

        def factory(*callbacks):
            listener = BrokenListener(*callbacks)
            holder["listener"] = listener
            return listener

        controller = DemoController(manager, factory)

        self.assertFalse(controller.prepare())
        self.assertTrue(holder["listener"].stopped)
        self.assertFalse(manager.snapshot().emergency_ready)
        with self.assertRaises(SessionStartError):
            manager.start(60)


if __name__ == "__main__":
    unittest.main()
