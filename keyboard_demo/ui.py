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
    RevealStage,
    SessionStarted,
    SessionState,
    SessionStopped,
    StopReason,
)
from .lesson import build_synthetic_example
from .listener import GlobalKeyboardListener
from .presentation import (
    ReplayModel,
    describe_key,
    format_countdown,
    format_event_time,
    reconstruct_text,
    summarize_session,
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
    PLAYBACK_SPEEDS = {
        "0,5 сек.": 500,
        "0,2 сек.": 200,
        "0,1 сек.": 100,
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
        self._reveal_stage = RevealStage.HIDDEN
        self._replay_model: ReplayModel | None = None
        self._replay_session_id: int | None = None
        self._playback_index = 0
        self._playback_running = False
        self._playback_after_id: str | None = None
        self._slider_after_id: str | None = None
        self._suppress_slider_callback = False
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
            controls, text="Покажи обобщението", command=self._toggle_journal
        )
        self.clear_button = ttk.Button(controls, text="Изчисти", command=self._clear)
        self.practice_button = ttk.Button(
            controls, text="Учебно поле", command=self._open_practice
        )
        self.questions_button = ttk.Button(
            controls, text="Въпроси за класа", command=self._open_questions
        )
        self.example_button = ttk.Button(
            controls, text="Готов пример", command=self._load_synthetic_example
        )
        self.exit_button = ttk.Button(controls, text="Изход", command=self._close)
        buttons = (
            self.start_button,
            self.stop_button,
            self.reveal_button,
            self.clear_button,
            self.practice_button,
            self.questions_button,
            self.example_button,
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

        self.results_group = ttk.LabelFrame(
            body, text="Резултат в оперативната памет", padding=8
        )
        self.results_group.grid(row=8, column=0, sticky="nsew")
        self.results_group.columnconfigure(0, weight=1)
        self.results_group.rowconfigure(0, weight=1)
        self.journal_placeholder = ttk.Label(
            self.results_group,
            text="Предположете какво е записано. Водещият ще разкрие резултата.",
            anchor="center",
            font=("Segoe UI", 13, "italic"),
        )
        self.journal_placeholder.grid(row=0, column=0, sticky="nsew", pady=35)
        self._build_summary_stage()
        self._build_replay_stage()
        self._build_full_stage()

    def _build_summary_stage(self) -> None:
        self.summary_frame = ttk.Frame(self.results_group, padding=8)
        self.summary_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.summary_frame,
            text="Етап 1 от 3 — Обобщение без съдържание",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.summary_frame,
            text="Преди да разкриете клавишите, нека класът предположи какво ще види.",
            wraplength=950,
        ).grid(row=1, column=0, sticky="w", pady=(3, 10))

        facts = ttk.Frame(self.summary_frame)
        facts.grid(row=2, column=0, sticky="ew")
        for column in range(3):
            facts.columnconfigure(column, weight=1)
        self.summary_vars = {
            "origin": tk.StringVar(value="—"),
            "events": tk.StringVar(value="0"),
            "elapsed": tk.StringVar(value="00:00.0"),
            "characters": tk.StringVar(value="—"),
            "corrections": tk.StringVar(value="—"),
            "special": tk.StringVar(value="—"),
        }
        summary_fields = (
            ("Източник", "origin"),
            ("Общо събития", "events"),
            ("Продължителност", "elapsed"),
            ("Печатни символи", "characters"),
            ("Редакции", "corrections"),
            ("Специални клавиши", "special"),
        )
        for index, (caption, key) in enumerate(summary_fields):
            card = ttk.LabelFrame(facts, text=caption, padding=8)
            card.grid(
                row=index // 3,
                column=index % 3,
                sticky="nsew",
                padx=4,
                pady=4,
            )
            ttk.Label(
                card,
                textvariable=self.summary_vars[key],
                font=("Segoe UI", 13, "bold"),
                wraplength=260,
            ).pack(anchor="center")

        self.summary_privacy_var = tk.StringVar(value="")
        ttk.Label(
            self.summary_frame,
            textvariable=self.summary_privacy_var,
            foreground="#7c2d12",
            wraplength=950,
        ).grid(row=3, column=0, sticky="w", pady=10)
        summary_controls = ttk.Frame(self.summary_frame)
        summary_controls.grid(row=4, column=0, sticky="ew")
        self.summary_next_button = ttk.Button(
            summary_controls,
            text="Към възпроизвеждането →",
            command=self._show_replay_stage,
        )
        self.summary_next_button.pack(side="right")

    def _build_replay_stage(self) -> None:
        self.replay_frame = ttk.Frame(self.results_group, padding=8)
        self.replay_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.replay_frame,
            text="Етап 2 от 3 — Възпроизвеждане стъпка по стъпка",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.replay_step_var = tk.StringVar(value="Стъпка 0 от 0")
        self.replay_event_var = tk.StringVar(value="Начало — няма приложено събитие.")
        self.replay_time_var = tk.StringVar(value="Момент: 00:00.0")
        replay_head = ttk.Frame(self.replay_frame)
        replay_head.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(
            replay_head,
            textvariable=self.replay_step_var,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")
        ttk.Label(replay_head, textvariable=self.replay_time_var).pack(side="right")
        ttk.Label(
            self.replay_frame,
            textvariable=self.replay_event_var,
            font=("Segoe UI", 13),
            wraplength=950,
        ).grid(row=2, column=0, sticky="w", pady=(2, 8))

        self.replay_scale_var = tk.DoubleVar(value=0)
        self.replay_scale = ttk.Scale(
            self.replay_frame,
            from_=0,
            to=1,
            variable=self.replay_scale_var,
            command=self._on_replay_slider,
        )
        self.replay_scale.grid(row=3, column=0, sticky="ew")

        replay_controls = ttk.Frame(self.replay_frame)
        replay_controls.grid(row=4, column=0, sticky="ew", pady=8)
        self.replay_previous_button = ttk.Button(
            replay_controls, text="← Назад", command=lambda: self._step_replay(-1)
        )
        self.replay_previous_button.pack(side="left")
        self.replay_play_button = ttk.Button(
            replay_controls, text="Пусни", command=self._toggle_playback
        )
        self.replay_play_button.pack(side="left", padx=6)
        self.replay_next_button = ttk.Button(
            replay_controls, text="Напред →", command=lambda: self._step_replay(1)
        )
        self.replay_next_button.pack(side="left")
        ttk.Button(
            replay_controls, text="Отначало", command=self._restart_replay
        ).pack(side="left", padx=6)
        ttk.Label(replay_controls, text="Скорост:").pack(side="left", padx=(14, 4))
        self.playback_speed_var = tk.StringVar(value="0,2 сек.")
        self.playback_speed_box = ttk.Combobox(
            replay_controls,
            textvariable=self.playback_speed_var,
            values=tuple(self.PLAYBACK_SPEEDS),
            state="readonly",
            width=9,
        )
        self.playback_speed_box.pack(side="left")
        self.playback_speed_box.bind("<<ComboboxSelected>>", self._speed_changed)

        ttk.Label(
            self.replay_frame,
            text="Червената черта ▌ показва симулираната позиция на курсора.",
            foreground="#991b1b",
        ).grid(row=5, column=0, sticky="w")
        self.replay_text = tk.Text(
            self.replay_frame,
            height=8,
            wrap="word",
            font=("Consolas", 15),
            padx=8,
            pady=8,
            state="disabled",
        )
        self.replay_text.tag_configure("cursor", foreground="#b3261e")
        self.replay_text.grid(row=6, column=0, sticky="ew", pady=(4, 8))

        replay_navigation = ttk.Frame(self.replay_frame)
        replay_navigation.grid(row=7, column=0, sticky="ew")
        ttk.Button(
            replay_navigation, text="← Обобщение", command=self._show_summary_stage
        ).pack(side="left")
        ttk.Button(
            replay_navigation,
            text="Покажи пълния резултат →",
            command=self._show_full_stage,
        ).pack(side="right")

    def _build_full_stage(self) -> None:
        self.full_frame = ttk.Frame(self.results_group, padding=8)
        self.full_frame.columnconfigure(0, weight=1)
        self.full_frame.rowconfigure(1, weight=1)
        ttk.Label(
            self.full_frame,
            text="Етап 3 от 3 — Пълен журнал и сглобен текст",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.journal_tree = ttk.Treeview(
            self.full_frame,
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
            self.full_frame, orient="vertical", command=self.journal_tree.yview
        )
        self.journal_tree.configure(yscrollcommand=journal_scroll.set)
        self.journal_tree.grid(row=1, column=0, sticky="nsew")
        journal_scroll.grid(row=1, column=1, sticky="ns")

        reconstructed = ttk.LabelFrame(
            self.full_frame,
            text="Сглобен текст от получените събития",
            padding=8,
        )
        reconstructed.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
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
        full_navigation = ttk.Frame(self.full_frame)
        full_navigation.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            full_navigation,
            text="← Възпроизвеждане",
            command=self._show_replay_stage,
        ).pack(side="left")
        ttk.Button(
            full_navigation,
            text="Скрий резултатите",
            command=self._hide_results,
        ).pack(side="right")

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
        self._reset_results()
        self._last_stop_notice = None
        self.stop_detail_var.set("")
        self.overlay.show()
        self._update_ui()

    def _stop(self) -> None:
        self.session.stop(StopReason.USER)
        self._update_ui()

    def _clear(self) -> None:
        self.session.reset()
        self._reset_results()
        self.stop_detail_var.set("")
        self.overlay.hide()
        self._update_ui()

    def _mode_changed(self) -> None:
        self.session.reset(mode=CaptureMode(self.mode_var.get()))
        self._reset_results()
        self.stop_detail_var.set("Режимът е сменен. Натиснете „Старт“ за нова сесия.")
        self.overlay.hide()
        self._update_ui()

    def _toggle_journal(self) -> None:
        if self._reveal_stage is RevealStage.HIDDEN:
            self._show_summary_stage()
        else:
            self._hide_results()

    def _show_summary_stage(self) -> None:
        self._pause_playback()
        snapshot = self.session.snapshot()
        records = self.session.journal()
        summary = summarize_session(
            records,
            total_events=snapshot.event_count,
            elapsed_seconds=snapshot.elapsed_seconds,
            detailed=snapshot.mode is CaptureMode.EVENTS,
        )
        self.summary_vars["origin"].set(snapshot.origin.bulgarian_name)
        self.summary_vars["events"].set(str(summary.total_events))
        self.summary_vars["elapsed"].set(format_event_time(summary.elapsed_seconds))
        if summary.printable_characters is None:
            hidden = "Не се съхранява"
            self.summary_vars["characters"].set(hidden)
            self.summary_vars["corrections"].set(hidden)
            self.summary_vars["special"].set(hidden)
            self.summary_privacy_var.set(
                "Режимът „Само брояч“ пази единствено общия брой. "
                "Няма данни за възпроизвеждане или пълен журнал."
            )
            self.summary_next_button.configure(state="disabled")
        else:
            self.summary_vars["characters"].set(str(summary.printable_characters))
            self.summary_vars["corrections"].set(str(summary.corrections))
            self.summary_vars["special"].set(str(summary.special_keys))
            self.summary_privacy_var.set(
                "Съдържанието все още е скрито. Попитайте класа какъв текст очаква."
            )
            self.summary_next_button.configure(
                state="normal" if records else "disabled"
            )
        self._display_stage(RevealStage.SUMMARY)

    def _show_replay_stage(self) -> None:
        snapshot = self.session.snapshot()
        if snapshot.mode is not CaptureMode.EVENTS or snapshot.event_count == 0:
            return
        if self._replay_session_id != snapshot.session_id or self._replay_model is None:
            self._replay_model = ReplayModel(self.session.journal())
            self._replay_session_id = snapshot.session_id
            self._playback_index = 0
        self._pause_playback()
        self.replay_scale.configure(to=max(1, self._replay_model.total))
        self._render_replay_index(self._playback_index)
        self._display_stage(RevealStage.REPLAY)

    def _show_full_stage(self) -> None:
        snapshot = self.session.snapshot()
        if snapshot.mode is not CaptureMode.EVENTS or snapshot.event_count == 0:
            return
        self._pause_playback()
        self._populate_full_result()
        self._display_stage(RevealStage.FULL)

    def _display_stage(self, stage: RevealStage) -> None:
        self.journal_placeholder.grid_remove()
        for frame in (self.summary_frame, self.replay_frame, self.full_frame):
            frame.grid_remove()
        self._reveal_stage = stage
        if stage is RevealStage.HIDDEN:
            self.journal_placeholder.grid(row=0, column=0, sticky="nsew", pady=35)
            self.reveal_button.configure(text="Покажи обобщението")
        elif stage is RevealStage.SUMMARY:
            self.summary_frame.grid(row=0, column=0, sticky="nsew")
            self.reveal_button.configure(text="Скрий резултатите")
        elif stage is RevealStage.REPLAY:
            self.replay_frame.grid(row=0, column=0, sticky="nsew")
            self.reveal_button.configure(text="Скрий резултатите")
        elif stage is RevealStage.FULL:
            self.full_frame.grid(row=0, column=0, sticky="nsew")
            self.reveal_button.configure(text="Скрий резултатите")

    def _hide_results(self) -> None:
        self._cancel_playback(clear_model=True)
        self._display_stage(RevealStage.HIDDEN)

    def _reset_results(self) -> None:
        self._cancel_playback(clear_model=True)
        self._clear_journal_tree()
        self._set_text_widget(self.reconstructed_text, "")
        self._set_text_widget(self.replay_text, "")
        self._display_stage(RevealStage.HIDDEN)

    def _clear_journal_tree(self) -> None:
        children = self.journal_tree.get_children()
        if children:
            self.journal_tree.delete(*children)

    def _populate_full_result(self) -> None:
        records = self.session.journal()
        self._clear_journal_tree()
        for record in records:
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
        assembled = reconstruct_text(record.display_key for record in records)
        self._set_text_widget(self.reconstructed_text, assembled)

    def _load_synthetic_example(self) -> None:
        self._reset_results()
        try:
            self.session.load_synthetic(build_synthetic_example())
        except (SessionStartError, ValueError) as exc:
            messagebox.showerror("Примерът не е зареден", str(exc), parent=self.root)
            return
        self.mode_var.set(CaptureMode.EVENTS.value)
        self._last_stop_notice = None
        self.stop_detail_var.set(StopReason.SYNTHETIC_EXAMPLE.bulgarian_message)
        self._show_summary_stage()
        self._update_ui()

    def _render_replay_index(self, index: int) -> None:
        model = self._replay_model
        if model is None:
            return
        frame = model.frame_at(index)
        self._playback_index = frame.index
        self._suppress_slider_callback = True
        self.replay_scale_var.set(frame.index)
        self._suppress_slider_callback = False
        self.replay_step_var.set(f"Стъпка {frame.index} от {frame.total}")
        if frame.record is None:
            self.replay_event_var.set("Начало — няма приложено събитие.")
            self.replay_time_var.set("Момент: 00:00.0")
        else:
            self.replay_event_var.set(describe_key(frame.record.display_key))
            self.replay_time_var.set(
                f"Момент: {format_event_time(frame.record.elapsed_seconds)}"
            )
        marked = frame.text[: frame.cursor] + "▌" + frame.text[frame.cursor :]
        self._set_text_widget(self.replay_text, marked, cursor_index=frame.cursor)
        self.replay_previous_button.configure(
            state="normal" if frame.index > 0 else "disabled"
        )
        self.replay_next_button.configure(
            state="normal" if frame.index < frame.total else "disabled"
        )

    def _on_replay_slider(self, raw_value: str) -> None:
        if self._suppress_slider_callback or self._replay_model is None:
            return
        self._pause_playback()
        target = int(round(float(raw_value)))
        self._cancel_after("_slider_after_id")
        self._slider_after_id = self.root.after(
            75, lambda: self._finish_slider_move(target)
        )

    def _finish_slider_move(self, target: int) -> None:
        self._slider_after_id = None
        if not self._closed and self._reveal_stage is RevealStage.REPLAY:
            self._render_replay_index(target)

    def _step_replay(self, offset: int) -> None:
        self._pause_playback()
        self._render_replay_index(self._playback_index + offset)

    def _restart_replay(self) -> None:
        self._pause_playback()
        self._render_replay_index(0)

    def _toggle_playback(self) -> None:
        if self._playback_running:
            self._pause_playback()
            return
        if self._replay_model is None or self._replay_model.total == 0:
            return
        if self._playback_index >= self._replay_model.total:
            self._render_replay_index(0)
        self._playback_running = True
        self.replay_play_button.configure(text="Пауза")
        self._schedule_playback_tick()

    def _schedule_playback_tick(self) -> None:
        self._cancel_after("_playback_after_id")
        delay = self.PLAYBACK_SPEEDS.get(self.playback_speed_var.get(), 200)
        self._playback_after_id = self.root.after(delay, self._playback_tick)

    def _playback_tick(self) -> None:
        self._playback_after_id = None
        if (
            not self._playback_running
            or self._closed
            or self._reveal_stage is not RevealStage.REPLAY
            or self._replay_model is None
        ):
            return
        self._render_replay_index(self._playback_index + 1)
        if self._playback_index >= self._replay_model.total:
            self._pause_playback()
        else:
            self._schedule_playback_tick()

    def _speed_changed(self, _event: tk.Event) -> None:
        if self._playback_running:
            self._schedule_playback_tick()

    def _pause_playback(self) -> None:
        self._playback_running = False
        self._cancel_after("_playback_after_id")
        self.replay_play_button.configure(text="Пусни")

    def _cancel_playback(self, *, clear_model: bool) -> None:
        self._pause_playback()
        self._cancel_after("_slider_after_id")
        if clear_model:
            self._replay_model = None
            self._replay_session_id = None
            self._playback_index = 0

    def _cancel_after(self, attribute: str) -> None:
        after_id = getattr(self, attribute)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    @staticmethod
    def _set_text_widget(
        widget: tk.Text, value: str, *, cursor_index: int | None = None
    ) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if cursor_index is None:
            widget.insert("1.0", value)
        else:
            widget.insert("1.0", value[:cursor_index])
            widget.insert("end", "▌", "cursor")
            widget.insert("end", value[cursor_index + 1 :])
        widget.configure(state="disabled")

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
        self._pause_playback()
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
                # The bounded queue is drained here, but content stays hidden
                # until the teacher reaches the full-result stage.
                pass
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
                if (
                    snapshot.stop_reason is StopReason.LISTENER_ERROR
                    and snapshot.error_detail
                ):
                    detail = f"{detail} {snapshot.error_detail}"
                self.stop_detail_var.set(detail)
        self.start_button.configure(
            state="normal" if snapshot.emergency_ready and not recording else "disabled"
        )
        self.stop_button.configure(state="normal" if recording else "disabled")
        option_state = "disabled" if recording else "normal"
        for button in self.mode_buttons:
            button.configure(state=option_state)
        self.duration_box.configure(state="disabled" if recording else "readonly")
        self.example_button.configure(state="disabled" if recording else "normal")
        can_reveal = (
            snapshot.state is SessionState.STOPPED
            and snapshot.event_count > 0
        )
        self.reveal_button.configure(state="normal" if can_reveal else "disabled")

    def _close(self) -> None:
        if self._closed:
            return
        self._cancel_playback(clear_model=True)
        self._closed = True
        self.overlay.hide()
        self.controller.close()
        self.overlay.destroy()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    MainApplication(root)
    root.mainloop()
