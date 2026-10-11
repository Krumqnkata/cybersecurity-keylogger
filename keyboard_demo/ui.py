"""Bulgarian Tkinter interface for the teacher-controlled demonstration."""

from __future__ import annotations

import math
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from .controller import DemoController
from .domain import (
    CaptureMode,
    KeyCaptured,
    SessionStarted,
    SessionState,
    SessionStopped,
    StopReason,
)
from .listener import GlobalKeyboardListener
from .presentation import (
    describe_key,
    format_countdown,
    format_event_time,
    reconstruct_text,
)
from .questions import QUESTIONS
from .session import SessionManager, SessionStartError


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=12)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_body)
        self.canvas.bind_all("<MouseWheel>", self._mousewheel)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_body(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _mousewheel(self, event: tk.Event) -> None:
        if self.winfo_exists():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class RecordingOverlay:
    def __init__(self, root: tk.Tk, stop_command, exit_command) -> None:
        self.window = tk.Toplevel(root)
        self.window.title("Клавишна демонстрация")
        self.window.withdraw()
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", exit_command)
        frame = ttk.Frame(self.window, padding=10)
        frame.grid(sticky="nsew")
        self.status = tk.Label(
            frame,
            text="ЗАПИСЪТ Е ВКЛЮЧЕН",
            bg="#b3261e",
            fg="white",
            font=("Segoe UI", 13, "bold"),
            padx=10,
            pady=5,
        )
        self.status.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.timer_var = tk.StringVar(value="Остават: 02:00")
        ttk.Label(frame, textvariable=self.timer_var, font=("Segoe UI", 11)).grid(
            row=1, column=0, padx=(0, 14), pady=(8, 0)
        )
        ttk.Button(frame, text="Стоп", command=stop_command).grid(
            row=1, column=1, pady=(8, 0)
        )

    def show(self) -> None:
        self.window.update_idletasks()
        width, height = 330, 112
        x = max(0, self.window.winfo_screenwidth() - width - 24)
        self.window.geometry(f"{width}x{height}+{x}+24")
        self.window.deiconify()
        # The window stays topmost, but updates never request keyboard focus.

    def hide(self) -> None:
        self.window.withdraw()

    def update_timer(self, seconds: int) -> None:
        self.timer_var.set(f"Остават: {format_countdown(seconds)}")

    def destroy(self) -> None:
        self.window.destroy()


class PracticeWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.window = tk.Toplevel(root)
        self.window.title("Учебно поле")
        self.window.geometry("650x240")
        self.window.minsize(500, 220)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Използвайте само измислени данни",
            foreground="#9a3412",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Пример: Demo-Klub-42",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(4, 12))
        self.entry = ttk.Entry(frame, font=("Segoe UI", 17))
        self.entry.pack(fill="x")
        self.masked = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Показвай символите като звездички",
            variable=self.masked,
            command=self._toggle_mask,
        ).pack(anchor="w", pady=10)
        ttk.Button(frame, text="Изчисти", command=lambda: self.entry.delete(0, "end")).pack(
            anchor="w"
        )
        self.entry.focus_set()

    def _toggle_mask(self) -> None:
        self.entry.configure(show="*" if self.masked.get() else "")


class QuestionsWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.window = tk.Toplevel(root)
        self.window.title("Въпроси за класа")
        self.window.geometry("850x540")
        self.window.minsize(650, 470)
        self.index = 0
        self.answer_var = tk.StringVar(value="")
        self.frame = ttk.Frame(self.window, padding=24)
        self.frame.pack(fill="both", expand=True)
        self.number_var = tk.StringVar()
        ttk.Label(
            self.frame, textvariable=self.number_var, font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")
        self.question_var = tk.StringVar()
        ttk.Label(
            self.frame,
            textvariable=self.question_var,
            wraplength=780,
            justify="left",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w", pady=(10, 18))
        self.answers_frame = ttk.Frame(self.frame)
        self.answers_frame.pack(fill="x", anchor="w")
        self.explanation_var = tk.StringVar(value="")
        self.explanation = ttk.Label(
            self.frame,
            textvariable=self.explanation_var,
            wraplength=780,
            justify="left",
            font=("Segoe UI", 12),
        )
        self.explanation.pack(fill="x", pady=18)
        controls = ttk.Frame(self.frame)
        controls.pack(fill="x", side="bottom")
        self.previous = ttk.Button(controls, text="← Предишен", command=self._previous)
        self.previous.pack(side="left")
        self.explain_button = ttk.Button(
            controls, text="Покажи обяснението", command=self._show_explanation
        )
        self.explain_button.pack(side="left", padx=10)
        self.next = ttk.Button(controls, text="Следващ →", command=self._next)
        self.next.pack(side="right")
        self._render()

    def _render(self) -> None:
        card = QUESTIONS[self.index]
        self.number_var.set(f"Въпрос {self.index + 1} от {len(QUESTIONS)}")
        self.question_var.set(card["question"])
        self.answer_var.set("")
        for child in self.answers_frame.winfo_children():
            child.destroy()
        for answer in card["answers"]:
            ttk.Radiobutton(
                self.answers_frame,
                text=answer,
                value=answer,
                variable=self.answer_var,
            ).pack(anchor="w", pady=4)
        self.explanation_var.set("Обяснението е скрито.")
        self.explain_button.configure(text="Покажи обяснението")
        self.previous.configure(state="normal" if self.index else "disabled")
        self.next.configure(
            state="normal" if self.index < len(QUESTIONS) - 1 else "disabled"
        )

    def _show_explanation(self) -> None:
        self.explanation_var.set(QUESTIONS[self.index]["explanation"])
        self.explain_button.configure(text="Обяснението е показано")

    def _previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._render()

    def _next(self) -> None:
        if self.index < len(QUESTIONS) - 1:
            self.index += 1
            self._render()


class MainApplication:
    POLL_MS = 50
    REFRESH_MS = 100
    DURATION_OPTIONS = {
        "1 минута": 60,
        "2 минути": 120,
        "5 минути": 300,
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Кой чува клавиатурата?")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = max(720, min(1100, screen_width - 80))
        height = max(480, min(720, screen_height - 100))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(720, 480)
        self._closed = False
        self._journal_visible = False
        self._reconstruction_marker: tuple[int, int] | None = None
        self._last_stop_notice: tuple[int, StopReason] | None = None
        self._practice_window: PracticeWindow | None = None
        self._questions_window: QuestionsWindow | None = None
        self.session = SessionManager()
        self.controller = DemoController(self.session, GlobalKeyboardListener)

        self._configure_styles()
        self._build()
        self.overlay = RecordingOverlay(root, self._stop, self._close)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Unmap>", self._on_unmap)
        self.root.after(0, self._prepare_listener)
        self.root.after(self.POLL_MS, self._process_notifications)
        self.root.after(self.REFRESH_MS, self._refresh)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Segoe UI", 11), padding=(10, 7))
        style.configure("TLabel", font=("Segoe UI", 11))
        style.configure("TRadiobutton", font=("Segoe UI", 11))
        style.configure("TCheckbutton", font=("Segoe UI", 11))
        style.configure(
            "Journal.Treeview",
            font=("Segoe UI", 12),
            rowheight=30,
        )
        style.configure(
            "Journal.Treeview.Heading",
            font=("Segoe UI", 11, "bold"),
        )

    def _build(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        scroll = ScrollableFrame(self.root)
        scroll.grid(row=0, column=0, sticky="nsew")
        body = scroll.body
        body.columnconfigure(0, weight=1)

        ttk.Label(
            body,
            text="Кой чува клавиатурата?",
            font=("Segoe UI", 23, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            body,
            text="Прозрачна учебна демонстрация — използвайте само измислени данни.",
            foreground="#7c2d12",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        self.recording_banner = tk.Label(
            body,
            text="ЗАПИСЪТ Е ИЗКЛЮЧЕН",
            bg="#334155",
            fg="white",
            font=("Segoe UI", 20, "bold"),
            padx=14,
            pady=9,
        )
        self.recording_banner.grid(row=2, column=0, sticky="ew")

        facts = ttk.LabelFrame(body, text="Състояние", padding=10)
        facts.grid(row=3, column=0, sticky="ew", pady=10)
        for column in range(4):
            facts.columnconfigure(column, weight=1)
        self.state_var = tk.StringVar(value="ГОТОВНОСТ")
        self.mode_display_var = tk.StringVar(value="Клавишни събития")
        self.timer_var = tk.StringVar(value="02:00")
        self.count_var = tk.StringVar(value="0")
        for column, (caption, variable) in enumerate(
            (
                ("Състояние", self.state_var),
                ("Режим", self.mode_display_var),
                ("Оставащо време", self.timer_var),
                ("Брой събития", self.count_var),
            )
        ):
            ttk.Label(facts, text=caption).grid(row=0, column=column, padx=6)
            ttk.Label(
                facts, textvariable=variable, font=("Segoe UI", 14, "bold")
            ).grid(row=1, column=column, padx=6, pady=(2, 0))

        options = ttk.LabelFrame(body, text="Настройки преди старт", padding=10)
        options.grid(row=4, column=0, sticky="ew")
        options.columnconfigure(4, weight=1)
        ttk.Label(options, text="Режим:").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=CaptureMode.EVENTS.value)
        self.mode_buttons = []
        for column, mode in enumerate(CaptureMode, start=1):
            button = ttk.Radiobutton(
                options,
                text=mode.bulgarian_name,
                value=mode.value,
                variable=self.mode_var,
                command=self._mode_changed,
            )
            button.grid(row=0, column=column, padx=8, sticky="w")
            self.mode_buttons.append(button)
        ttk.Label(options, text="Продължителност:").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        self.duration_var = tk.StringVar(value="2 минути")
        self.duration_box = ttk.Combobox(
            options,
            textvariable=self.duration_var,
            values=tuple(self.DURATION_OPTIONS),
            state="readonly",
            width=12,
        )
        self.duration_box.grid(row=1, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Label(options, text="(максимум 5 минути)").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(10, 0)
        )

        controls = ttk.Frame(body)
        controls.grid(row=5, column=0, sticky="ew", pady=10)
        for column in range(4):
            controls.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(
            controls, text="Старт", command=self._start, state="disabled"
        )
        self.stop_button = ttk.Button(
            controls, text="Стоп", command=self._stop, state="disabled"
        )
        self.reveal_button = ttk.Button(
            controls, text="Разкрий журнала", command=self._toggle_journal
        )
        self.clear_button = ttk.Button(controls, text="Изчисти", command=self._clear)
        self.practice_button = ttk.Button(
            controls, text="Учебно поле", command=self._open_practice
        )
        self.questions_button = ttk.Button(
            controls, text="Въпроси за класа", command=self._open_questions
        )
        self.exit_button = ttk.Button(controls, text="Изход", command=self._close)
        buttons = (
            self.start_button,
            self.stop_button,
            self.reveal_button,
            self.clear_button,
            self.practice_button,
            self.questions_button,
            self.exit_button,
        )
        for index, button in enumerate(buttons):
            button.grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=4,
                pady=4,
            )

        ttk.Label(
            body,
            text="Ctrl+Alt+Q — спиране",
            foreground="#991b1b",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=6, column=0, sticky="w", pady=(0, 8))
        self.stop_detail_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.stop_detail_var, wraplength=1000).grid(
            row=7, column=0, sticky="w", pady=(0, 8)
        )

        journal_group = ttk.LabelFrame(body, text="Журнал в оперативната памет", padding=8)
        journal_group.grid(row=8, column=0, sticky="nsew")
        journal_group.columnconfigure(0, weight=1)
        journal_group.rowconfigure(0, weight=1)
        self.journal_placeholder = ttk.Label(
            journal_group,
            text="Предположете какво е записано. Водещият ще разкрие резултата.",
            anchor="center",
            font=("Segoe UI", 13, "italic"),
        )
        self.journal_placeholder.grid(row=0, column=0, sticky="nsew", pady=35)
        self.journal_frame = ttk.Frame(journal_group)
        self.journal_frame.columnconfigure(0, weight=1)
        self.journal_frame.rowconfigure(0, weight=1)
        self.journal_tree = ttk.Treeview(
            self.journal_frame,
            columns=("number", "time", "key"),
            show="headings",
            height=11,
            style="Journal.Treeview",
        )
        self.journal_tree.heading("number", text="№")
        self.journal_tree.heading("time", text="Момент (мм:сс.д)")
        self.journal_tree.heading("key", text="Какво се случи")
        self.journal_tree.column("number", width=80, anchor="center", stretch=False)
        self.journal_tree.column("time", width=170, anchor="center", stretch=False)
        self.journal_tree.column("key", width=500, anchor="w")
        self.journal_tree.tag_configure("odd", background="#f8fafc")
        self.journal_tree.tag_configure("even", background="#eaf2f8")
        journal_scroll = ttk.Scrollbar(
            self.journal_frame, orient="vertical", command=self.journal_tree.yview
        )
        self.journal_tree.configure(yscrollcommand=journal_scroll.set)
        self.journal_tree.grid(row=0, column=0, sticky="nsew")
        journal_scroll.grid(row=0, column=1, sticky="ns")

        reconstructed = ttk.LabelFrame(
            self.journal_frame,
            text="Сглобен текст от получените събития",
            padding=8,
        )
        reconstructed.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        reconstructed.columnconfigure(0, weight=1)
        ttk.Label(
            reconstructed,
            text=(
                "Учебна реконструкция след спиране — показва събитията като един текст. "
                "Използвайте само измислени данни."
            ),
            foreground="#9a3412",
            wraplength=950,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.reconstructed_text = tk.Text(
            reconstructed,
            height=6,
            wrap="word",
            font=("Consolas", 14),
            padx=8,
            pady=8,
            state="disabled",
        )
        self.reconstructed_text.grid(row=1, column=0, sticky="ew")

    def _prepare_listener(self) -> None:
        if self._closed:
            return
        if not self.controller.prepare():
            detail = self.session.snapshot().error_detail
            self.stop_detail_var.set(detail)
            messagebox.showerror(
                "Стартът е недостъпен",
                detail
                + "\n\n„Старт“ остава изключен, защото Ctrl+Alt+Q не е готово.",
                parent=self.root,
            )
        self._update_ui()

    def _start(self) -> None:
        try:
            duration = self.DURATION_OPTIONS[self.duration_var.get()]
            self.session.start(duration)
        except (KeyError, SessionStartError) as exc:
            messagebox.showerror("Сесията не стартира", str(exc), parent=self.root)
            return
        self._clear_tree()
        self._hide_journal()
        self._last_stop_notice = None
        self.stop_detail_var.set("")
        self.overlay.show()
        self._update_ui()

    def _stop(self) -> None:
        self.session.stop(StopReason.USER)
        self._update_ui()

    def _clear(self) -> None:
        self.session.reset()
        self._clear_tree()
        self._hide_journal()
        self.stop_detail_var.set("")
        self.overlay.hide()
        self._update_ui()

    def _mode_changed(self) -> None:
        self.session.reset(mode=CaptureMode(self.mode_var.get()))
        self._clear_tree()
        self._hide_journal()
        self.stop_detail_var.set("Режимът е сменен. Натиснете „Старт“ за нова сесия.")
        self.overlay.hide()
        self._update_ui()

    def _toggle_journal(self) -> None:
        if self._journal_visible:
            self._hide_journal()
        else:
            self._update_reconstructed_text()
            self.journal_placeholder.grid_remove()
            self.journal_frame.grid(row=0, column=0, sticky="nsew")
            self._journal_visible = True
            self.reveal_button.configure(text="Скрий журнала")

    def _hide_journal(self) -> None:
        self.journal_frame.grid_remove()
        self.journal_placeholder.grid()
        self._journal_visible = False
        self.reveal_button.configure(text="Разкрий журнала")

    def _clear_tree(self) -> None:
        children = self.journal_tree.get_children()
        if children:
            self.journal_tree.delete(*children)
        self._reconstruction_marker = None
        self._set_reconstructed_text("")

    def _update_reconstructed_text(self) -> None:
        snapshot = self.session.snapshot()
        if snapshot.state is SessionState.RECORDING or snapshot.mode is not CaptureMode.EVENTS:
            self._reconstruction_marker = None
            self._set_reconstructed_text("")
            return
        marker = (snapshot.session_id, snapshot.event_count)
        if marker == self._reconstruction_marker:
            return
        assembled = reconstruct_text(
            record.display_key for record in self.session.journal()
        )
        self._set_reconstructed_text(assembled)
        self._reconstruction_marker = marker

    def _set_reconstructed_text(self, value: str) -> None:
        self.reconstructed_text.configure(state="normal")
        self.reconstructed_text.delete("1.0", "end")
        self.reconstructed_text.insert("1.0", value)
        self.reconstructed_text.configure(state="disabled")

    def _open_practice(self) -> None:
        if (
            self._practice_window is None
            or not self._practice_window.window.winfo_exists()
        ):
            self._practice_window = PracticeWindow(self.root)
        else:
            self._practice_window.window.deiconify()
            self._practice_window.window.lift()

    def _open_questions(self) -> None:
        self.session.stop(StopReason.QUESTIONS_OPENED)
        self._update_ui()
        if (
            self._questions_window is None
            or not self._questions_window.window.winfo_exists()
        ):
            self._questions_window = QuestionsWindow(self.root)
        else:
            self._questions_window.window.deiconify()
            self._questions_window.window.lift()

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self.root.after(25, self._stop_if_minimized)

    def _stop_if_minimized(self) -> None:
        if not self._closed and self.root.state() == "iconic":
            self.session.stop(StopReason.MINIMIZED)
            self._update_ui()

    def _process_notifications(self) -> None:
        if self._closed:
            return
        processed = 0
        while processed < 250:
            try:
                message = self.session.notifications.get_nowait()
            except queue.Empty:
                break
            processed += 1
            current_id = self.session.snapshot().session_id
            if message.session_id != current_id:
                continue
            if isinstance(message, KeyCaptured):
                record = message.record
                self.journal_tree.insert(
                    "",
                    "end",
                    values=(
                        record.sequence,
                        format_event_time(record.elapsed_seconds),
                        describe_key(record.display_key),
                    ),
                    tags=("even" if record.sequence % 2 == 0 else "odd",),
                )
            elif isinstance(message, SessionStopped):
                self._show_stop_notice(message)
            elif isinstance(message, SessionStarted):
                pass
        delay = 1 if processed == 250 else self.POLL_MS
        self.root.after(delay, self._process_notifications)

    def _show_stop_notice(self, message: SessionStopped) -> None:
        marker = (message.session_id, message.reason)
        if marker == self._last_stop_notice:
            return
        self._last_stop_notice = marker
        detail = message.reason.bulgarian_message
        if message.detail:
            detail = f"{detail} {message.detail}"
        self.stop_detail_var.set(detail)
        if message.reason in (StopReason.LIMIT, StopReason.LISTENER_ERROR):
            messagebox.showwarning("Записът е прекратен", detail, parent=self.root)

    def _refresh(self) -> None:
        if self._closed:
            return
        self.session.check_timeout()
        self.controller.check_listener_health()
        self._update_ui()
        self.root.after(self.REFRESH_MS, self._refresh)

    def _update_ui(self) -> None:
        if self._closed:
            return
        snapshot = self.session.snapshot()
        remaining = int(math.ceil(snapshot.remaining_seconds))
        self.state_var.set(snapshot.state.bulgarian_name)
        self.mode_display_var.set(snapshot.mode.bulgarian_name)
        self.timer_var.set(format_countdown(remaining))
        self.count_var.set(str(snapshot.event_count))
        recording = snapshot.state is SessionState.RECORDING
        if recording:
            self.recording_banner.configure(
                text="ЗАПИСЪТ Е ВКЛЮЧЕН", bg="#b3261e", fg="white"
            )
            self.overlay.update_timer(remaining)
        else:
            self.recording_banner.configure(
                text="ЗАПИСЪТ Е ИЗКЛЮЧЕН", bg="#334155", fg="white"
            )
            self.overlay.hide()
            if snapshot.state is SessionState.STOPPED and snapshot.stop_reason is not None:
                detail = snapshot.stop_reason.bulgarian_message
                if snapshot.error_detail:
                    detail = f"{detail} {snapshot.error_detail}"
                self.stop_detail_var.set(detail)
                self._update_reconstructed_text()
        self.start_button.configure(
            state="normal" if snapshot.emergency_ready and not recording else "disabled"
        )
        self.stop_button.configure(state="normal" if recording else "disabled")
        option_state = "disabled" if recording else "normal"
        for button in self.mode_buttons:
            button.configure(state=option_state)
        self.duration_box.configure(state="disabled" if recording else "readonly")
        can_reveal = (
            not recording
            and snapshot.mode is CaptureMode.EVENTS
            and snapshot.event_count > 0
        )
        self.reveal_button.configure(state="normal" if can_reveal else "disabled")

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.overlay.hide()
        self.controller.close()
        self.overlay.destroy()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    MainApplication(root)
    root.mainloop()
