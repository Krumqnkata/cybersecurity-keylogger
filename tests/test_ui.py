from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import patch

from keyboard_demo.domain import CaptureMode, RevealStage, SessionOrigin, SessionState
import keyboard_demo.ui as ui


class FakeController:
    def __init__(self, session, _listener_factory) -> None:
        self.session = session
        self.prepared = False
        self.closed = False

    def prepare(self) -> bool:
        self.prepared = True
        self.session.set_emergency_ready(True)
        return True

    def check_listener_health(self) -> bool:
        return self.prepared

    def close(self) -> None:
        self.closed = True
        self.session.shutdown()


class InteractiveLessonUiTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tkinter desktop is unavailable: {exc}")
        self.root.withdraw()
        self.controller_patch = patch.object(ui, "DemoController", FakeController)
        self.controller_patch.start()
        self.app = ui.MainApplication(self.root)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        if hasattr(self, "app") and not self.app._closed:
            self.app._close()
        if hasattr(self, "controller_patch"):
            self.controller_patch.stop()

    def test_synthetic_example_needs_no_listener_and_reveals_three_stages(self) -> None:
        self.assertFalse(self.app.controller.prepared)

        self.app._load_synthetic_example()

        snapshot = self.app.session.snapshot()
        self.assertEqual(SessionOrigin.SYNTHETIC, snapshot.origin)
        self.assertEqual(SessionState.STOPPED, snapshot.state)
        self.assertFalse(self.app.controller.prepared)
        self.assertEqual(RevealStage.SUMMARY, self.app._reveal_stage)
        self.assertEqual("Готов синтетичен пример", self.app.summary_vars["origin"].get())
        self.assertEqual((), self.app.journal_tree.get_children())
        self.assertEqual("", self.app.reconstructed_text.get("1.0", "end-1c"))
        visible_summary = " ".join(value.get() for value in self.app.summary_vars.values())
        self.assertNotIn("Среща", visible_summary)

        self.app._show_replay_stage()
        self.app._step_replay(1)
        replay_text = self.app.replay_text.get("1.0", "end-1c")
        self.assertEqual(RevealStage.REPLAY, self.app._reveal_stage)
        self.assertEqual("С▌", replay_text)

        self.app._show_full_stage()
        final_text = self.app.reconstructed_text.get("1.0", "end-1c")
        self.assertEqual(RevealStage.FULL, self.app._reveal_stage)
        self.assertEqual(snapshot.event_count, len(self.app.journal_tree.get_children()))
        self.assertEqual("Среща в 16:00", final_text)

    def test_count_only_stops_at_content_free_summary(self) -> None:
        self.app.session.set_emergency_ready(True)
        self.app.session.reset(mode=CaptureMode.COUNT_ONLY)
        self.app.mode_var.set(CaptureMode.COUNT_ONLY.value)
        self.app.session.start(60)
        self.app.session.handle_key_press("Secret")
        self.app.session.handle_key_press("[ENTER]")
        self.app.session.stop()

        self.app._show_summary_stage()

        self.assertEqual(RevealStage.SUMMARY, self.app._reveal_stage)
        self.assertEqual("2", self.app.summary_vars["events"].get())
        self.assertEqual("Не се съхранява", self.app.summary_vars["characters"].get())
        self.assertEqual("disabled", str(self.app.summary_next_button.cget("state")))
        self.assertEqual((), self.app.session.journal())

    def test_playback_is_cancelled_by_clear_mode_change_and_new_start(self) -> None:
        self.app._load_synthetic_example()
        self.app._show_replay_stage()
        self.app._toggle_playback()
        self.assertTrue(self.app._playback_running)
        self.assertIsNotNone(self.app._playback_after_id)

        self.app._clear()
        self.assertFalse(self.app._playback_running)
        self.assertIsNone(self.app._playback_after_id)
        self.assertIsNone(self.app._replay_model)
        self.assertEqual(RevealStage.HIDDEN, self.app._reveal_stage)

        self.app._load_synthetic_example()
        self.app._show_replay_stage()
        self.app._toggle_playback()
        self.app.mode_var.set(CaptureMode.COUNT_ONLY.value)
        self.app._mode_changed()
        self.assertFalse(self.app._playback_running)
        self.assertIsNone(self.app._playback_after_id)

        self.app._load_synthetic_example()
        self.app._show_replay_stage()
        self.app._toggle_playback()
        self.app.session.set_emergency_ready(True)
        self.app.duration_var.set("1 минута")
        self.app._start()
        self.assertEqual(SessionState.RECORDING, self.app.session.snapshot().state)
        self.assertFalse(self.app._playback_running)
        self.assertIsNone(self.app._playback_after_id)

    def test_automatic_playback_stops_at_last_event(self) -> None:
        self.app._load_synthetic_example()
        self.app._show_replay_stage()
        total = self.app._replay_model.total
        self.app._render_replay_index(total - 1)
        self.app._toggle_playback()
        scheduled = self.app._playback_after_id
        self.root.after_cancel(scheduled)
        self.app._playback_after_id = None

        self.app._playback_tick()

        self.assertEqual(total, self.app._playback_index)
        self.assertFalse(self.app._playback_running)
        self.assertIsNone(self.app._playback_after_id)

    def test_close_cancels_playback_and_releases_controller(self) -> None:
        self.app._load_synthetic_example()
        self.app._show_replay_stage()
        self.app._toggle_playback()
        controller = self.app.controller

        self.app._close()

        self.assertFalse(self.app._playback_running)
        self.assertIsNone(self.app._playback_after_id)
        self.assertTrue(controller.closed)


if __name__ == "__main__":
    unittest.main()
