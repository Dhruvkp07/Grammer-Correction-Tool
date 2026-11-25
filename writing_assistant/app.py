"""Writing Assistant's Windows tray, settings, and review interface."""

import ctypes
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import settings, windows
from .core import GeminiError, Spelling, parse_shortcut, request_rewrites
from .worker import EditorWorker

BG = "#f4f7fb"
INK = "#132038"
MUTED = "#495a72"
BLUE = "#1a5bd8"
WHITE = "#ffffff"


class WritingAssistant:
    def __init__(self, root, background=False):
        self.root = root
        self.pid = os.getpid()
        self.settings = settings.Settings.load()
        self.worker = EditorWorker()
        self.network = queue.SimpleQueue()
        self.auto_seen = None
        self.auto_changed = None
        self.auto_sent = None
        self.auto_pending = False
        self.auto_busy = False
        self.auto_result = None
        self.variants = ()
        self.inline_notice = ""
        self.auto_queue = queue.SimpleQueue()
        self.target = None
        self.word = None
        self.hidden_word = None
        self.pending_probe = False
        self.pending_capture = False
        self.pending_apply = False
        self.next_probe = 0
        self.word_input = None
        self.paused = False
        self.revision = 0
        self.excerpt = None
        self.options = []
        self.ui_fault = ""

        root.withdraw()
        root.title("Writing Assistant")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_settings)
        self._styles()
        root.update_idletasks()
        self.hwnd = windows.own_window(root)
        self.hotkey = windows.Hotkey(self.hwnd)
        self.tray = windows.Tray(self.hwnd)
        try:
            self.hotkey.set(parse_shortcut(self.settings.shortcut))
        except ValueError as exc:
            self.ui_fault = str(exc)

        self._settings_window()
        self._overlay_window()
        self._review_window()
        if not background or not self.tray.visible:
            self.open_settings()
        self.tick_id = self.root.after(40, self.tick)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 21))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 10))
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE)
        style.map("Primary.TButton", background=[("active", "#174caf"), ("disabled", "#839cbd")])
        style.configure("TCheckbutton", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("TEntry", padding=5)

    def _settings_window(self):
        body = ttk.Frame(self.root, padding=24)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Writing Assistant", style="Title.TLabel").grid(sticky="w")
        self.run_status = tk.StringVar()
        ttk.Label(body, textvariable=self.run_status, style="Muted.TLabel", wraplength=455).grid(
            sticky="w", pady=(2, 14)
        )
        actions = ttk.Frame(body)
        actions.grid(sticky="w", pady=(0, 16))
        ttk.Button(actions, text="Open review", style="Primary.TButton", command=self.manual).pack(side="left")
        self.pause_button = ttk.Button(actions, command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Exit", command=self.exit).pack(side="left")
        ttk.Separator(body).grid(sticky="ew", pady=(0, 14))

        ttk.Label(body, text="Editor settings", style="Section.TLabel").grid(sticky="w")
        self.spelling_control = tk.BooleanVar(value=self.settings.spelling)
        self.overlay_control = tk.BooleanVar(value=self.settings.overlay)
        self.auto_control = tk.BooleanVar(value=self.settings.automatic)
        self.startup_control = tk.BooleanVar(value=False)
        for label, value in (
            ("Show local spelling and word completions", self.spelling_control),
            ("Auto-polish: send the current paragraph to Gemini after a typing pause", self.auto_control),
            ("Show floating Review button", self.overlay_control),
            ("Start in the tray when I sign in to Windows", self.startup_control),
        ):
            ttk.Checkbutton(body, text=label, variable=value).grid(sticky="w", pady=(3, 0))
        self.shortcut_control = tk.StringVar(value=self.settings.shortcut)
        ttk.Label(body, text="Review shortcut").grid(sticky="w", pady=(10, 0))
        ttk.Entry(body, textvariable=self.shortcut_control, width=54).grid(sticky="ew", pady=(2, 12))

        ttk.Label(body, text="Gemini", style="Section.TLabel").grid(sticky="w")
        ttk.Label(body, text="Gemini API key", style="Muted.TLabel").grid(sticky="w", pady=(4, 0))
        self.key_control = tk.StringVar()
        ttk.Entry(body, textvariable=self.key_control, show="•", width=54).grid(sticky="ew", pady=(2, 0))
        self.key_status = tk.StringVar()
        ttk.Label(body, textvariable=self.key_status, style="Muted.TLabel").grid(sticky="w", pady=(5, 0))
        ttk.Label(body, text="Gemini model ID", style="Muted.TLabel").grid(sticky="w", pady=(9, 0))
        self.model_control = tk.StringVar(value=self.settings.model)
        ttk.Entry(body, textvariable=self.model_control, width=54).grid(sticky="ew", pady=(2, 10))
        ttk.Label(body, text="Auto-polish sends edited paragraphs when enabled. Manual Review sends the displayed text on request.",
                  style="Muted.TLabel", wraplength=455).grid(sticky="w")
        footer = ttk.Frame(body)
        footer.grid(sticky="ew", pady=(12, 0))
        ttk.Button(footer, text="Save settings", command=self.save_settings).pack(side="left")
        ttk.Button(footer, text="Remove API key", command=self.remove_key).pack(side="left", padx=8)
        self.settings_status = tk.StringVar()
        ttk.Label(body, textvariable=self.settings_status, wraplength=455).grid(sticky="w", pady=(7, 0))

    def open_settings(self):
        self._refresh_settings_status()
        self.root.deiconify()
        self.root.lift()

    def hide_settings(self):
        self.key_control.set("")
        if self.tray.visible:
            self.root.withdraw()
        else:
            self.settings_status.set("The system tray is unavailable. Minimize this window to keep running.")
            self.root.iconify()

    def _refresh_settings_status(self):
        status = "Editor integration paused." if self.paused else "Ready in supported Windows text fields."
        self.run_status.set(self.ui_fault or status)
        self.pause_button.configure(text="Resume editor integration" if self.paused else "Pause editor integration")
        try:
            self.startup_control.set(settings.startup_enabled())
            if settings.CREDENTIAL.is_file():
                self.key_status.set("Key saved for this Windows user. Paste a new key to replace it.")
            else:
                self.key_status.set("Paste your Google AI Studio API key here when ready.")
        except OSError:
            self.settings_status.set("Windows settings could not be read.")

    def save_settings(self):
        key = self.key_control.get().strip()
        model = self.model_control.get().strip()
        previous = self.settings
        try:
            shortcut = parse_shortcut(self.shortcut_control.get())
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", model):
                raise ValueError("Enter a valid Gemini model ID.")
            if key and (not key.isascii() or re.search(r"\s", key) or len(key) > 512):
                raise ValueError("Paste the API key as a single value.")
            updated = settings.Settings(shortcut.label, self.spelling_control.get(), self.overlay_control.get(), model, self.auto_control.get())
            self.hotkey.set(shortcut)
            try:
                updated.save()
            except OSError:
                self.hotkey.set(parse_shortcut(previous.shortcut))
                raise
            self._observe(None)
            self.settings = updated
            self.shortcut_control.set(shortcut.label)
            if key:
                settings.save_key(key)
                self.key_control.set("")
            startup = self.startup_control.get()
            if startup != settings.startup_enabled():
                settings.set_startup(startup)
            if self.ui_fault.endswith("is unavailable. Try another shortcut."):
                self.ui_fault = ""
            self.word = None
            self.word_input = None
            self._refresh_settings_status()
            self.settings_status.set("Settings saved.")
        except ValueError as exc:
            self.settings_status.set(str(exc))
        except OSError:
            self._refresh_settings_status()
            self.settings_status.set("Windows could not save all settings. Check the displayed values and try again.")

    def remove_key(self):
        try:
            settings.remove_key()
            self.key_control.set("")
            self._refresh_settings_status()
            self.settings_status.set("API key removed.")
        except OSError:
            self.settings_status.set("Windows could not remove the saved API key.")

    def toggle_pause(self):
        self._observe(None)
        self.paused = not self.paused
        self.word = self.target = None
        self.word_input = None
        self.overlay.withdraw()
        self._refresh_settings_status()

    def _overlay_window(self):
        window = self.overlay = tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        surface = tk.Frame(window, bg="#192a48", padx=4, pady=4)
        surface.pack(fill="both", expand=True)
        self.word_button = ttk.Button(surface, style="Primary.TButton", command=self.apply_word)
        self.dismiss_word = ttk.Button(surface, text="×", width=2, command=self.hide_word)
        self.review_button = ttk.Button(surface, text="Review", command=self.capture)
        self.card = tk.Frame(surface, bg=WHITE, padx=8, pady=5)
        self.preview = tk.Button(self.card, bg=WHITE, fg=INK, justify="left", wraplength=350,
                                 anchor="w", relief="flat", cursor="hand2", takefocus=False,
                                 command=self.auto_apply)
        self.choices = tk.Frame(self.card, bg=WHITE)
        self.notice = tk.Label(surface, bg=WHITE, fg=INK, justify="left", wraplength=340)
        self.overlay.update_idletasks()
        self.overlay_guard = windows.NoActivate(self.overlay)
        self.preview.pack(anchor="w")
        for label, command in (("Copy", self.auto_copy), ("Apply", self.auto_apply),
                               ("3 more", self.auto_more), ("Dismiss", self.auto_hide)):
            button = ttk.Button(self.card, text=label, command=command, takefocus=False)
            button.pack(side="left")
            if label == "Apply":
                self.inline_apply = button
        # ttk's default mouse binding may move keyboard focus into the popup.
        # Hold the displayed suggestion across a mouse press and UIA poll.
        self.pressed_rewrite = None
        self.inline_apply.bind("<ButtonPress-1>", self._press_apply)
        self.inline_apply.bind("<ButtonRelease-1>", self._release_apply)
        self.overlay_signature = None

    def _press_apply(self, event):
        self.pressed_rewrite = self.auto_result
        event.widget.state(["pressed"])
        return "break"

    def _release_apply(self, event):
        suggestion, self.pressed_rewrite = self.pressed_rewrite, None
        event.widget.state(["!pressed"])
        inside = 0 <= event.x < event.widget.winfo_width() and 0 <= event.y < event.widget.winfo_height()
        if suggestion and inside:
            self._apply_inline(*suggestion, "paragraph")
        return "break"

    def auto_hide(self):
        self.auto_result = None
        self.variants = ()
        self.inline_notice = ""
        self._update_overlay()

    def auto_copy(self):
        if self.auto_result:
            try:
                windows.copy_text(self.hwnd, self.auto_result[1])
                self.auto_hide()
            except OSError:
                self.inline_notice = "Clipboard busy. Try Copy again."

    def auto_apply(self):
        if self.auto_result:
            excerpt, result = self.auto_result
            self._apply_inline(excerpt, result, "paragraph")

    def _apply_inline(self, excerpt, replacement, token):
        if self.pending_apply or self.paused:
            return
        self.pending_apply = "inline"
        self.hidden_word = self.word
        self.inline_notice = ""
        overlay_had_focus = windows.foreground() == windows.own_window(self.overlay)
        self.overlay.withdraw()
        if overlay_had_focus:
            windows.restore_foreground(excerpt.target.window)
        self.root.after(120 if overlay_had_focus else 40,
                        lambda: self.worker.submit("apply", token, excerpt, replacement, self.hwnd))

    def auto_more(self):
        if self.auto_result and not self.auto_busy:
            self._request_inline(self.auto_result[0], True)

    def _request_inline(self, excerpt, more=False):
        try:
            key = settings.load_key()
        except OSError:
            key = None
        if not key:
            self.inline_notice = "Add your Gemini key in Settings."
            return
        self.auto_busy = True
        model = self.settings.model
        self.inline_notice = "Getting three versions…" if more else ""

        def send():
            try:
                options = request_rewrites(excerpt.text, key, model, "three" if more else False)
            except GeminiError as exc:
                self.auto_queue.put((excerpt, more, (), str(exc)))
            else:
                self.auto_queue.put((excerpt, more, options, ""))

        threading.Thread(target=send, daemon=True).start()

    def _observe(self, excerpt):
        previous = self.auto_seen
        self.auto_seen = excerpt
        if excerpt != previous:
            self.auto_result = self.auto_sent = None
            self.variants = ()
            self.inline_notice = ""
            same = previous and excerpt and previous.target.identity == excerpt.target.identity
            self.auto_changed = time.monotonic() if same and previous.text != excerpt.text else None
        if (not excerpt or not self.auto_changed or self.auto_busy or self.auto_sent == excerpt
                or time.monotonic() - self.auto_changed < 1.6 or len(excerpt.text.split()) < 2
                or windows.foreground() != excerpt.target.window):
            return
        self.auto_sent = excerpt
        self._request_inline(excerpt)

    def _update_overlay(self):
        if self.pressed_rewrite and not self.paused:
            return
        target = self.target
        if self.paused or not target or self.pending_capture or self.pending_apply or self.review.state() != "withdrawn":
            self.overlay.withdraw()
            self.overlay_signature = None
            return
        word = self.word if self.settings.spelling and self.word != self.hidden_word else None
        floating = self.settings.overlay
        result = self.auto_result if self.settings.automatic and self.auto_result and self.auto_result[0].target.identity == target.identity else None
        floating = floating and not (word or result or self.settings.automatic)
        signature = (target, word, floating, result, self.variants, self.inline_notice)
        if self.overlay_signature == signature:
            return
        self.overlay_signature = signature
        for button in (self.word_button, self.dismiss_word, self.review_button):
            button.pack_forget()
        self.card.pack_forget()
        self.notice.pack_forget()
        if self.inline_notice:
            self.notice.configure(text=self.inline_notice)
            self.notice.pack(side="top")
        for child in self.choices.winfo_children():
            child.destroy()
        self.choices.pack_forget()
        if result and self.variants:
            self.choices.pack(side="top", before=self.preview)
            for tone, version in self.variants:
                tk.Button(self.choices, text=f"{tone} · {version}", wraplength=350, justify="left",
                          anchor="w", relief="flat", cursor="hand2", takefocus=False,
                          command=lambda v=version, e=result[0]: self._apply_inline(e, v, "paragraph")
                          ).pack(fill="x")
        if result:
            self.preview.configure(text=result[1][:350] + ("…" if len(result[1]) > 350 else ""))
            self.card.pack(side="top")
        if word:
            self.word_button.configure(text=word[1])
            self.word_button.pack(side="left", padx=(0, 3))
            self.dismiss_word.pack(side="left", padx=(0, 3))
        if floating:
            self.review_button.pack(side="left")
        if word or floating or result or self.inline_notice:
            box = word[0].box if word else target.box
            if (box[2] > box[0] and box[3] > box[1]
                    and all(abs(coordinate) < 100000 for coordinate in box)):
                windows.place_popup(self.overlay, box)
                return
        self.overlay.withdraw()

    def hide_word(self):
        self.hidden_word = self.word
        self._update_overlay()

    def apply_word(self):
        if not self.word or self.pending_apply or self.paused:
            return
        excerpt, replacement = self.word
        self._apply_inline(excerpt, replacement, None)

    def _review_window(self):
        window = self.review = tk.Toplevel(self.root)
        window.withdraw()
        window.title("Review writing")
        window.configure(bg=BG)
        window.geometry("650x655")
        window.minsize(460, 530)
        window.protocol("WM_DELETE_WINDOW", self.dismiss)
        window.bind("<Escape>", lambda _event: self.dismiss())
        body = ttk.Frame(window, padding=20)
        body.pack(expand=True, fill="both")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(6, weight=1)
        ttk.Label(body, text="Review writing", style="Title.TLabel").grid(sticky="w")
        self.scope = tk.StringVar()
        ttk.Label(body, textvariable=self.scope, style="Muted.TLabel", wraplength=600).grid(
            sticky="w", pady=(3, 5)
        )
        self.source = self._text_box(body, 5, 2)
        actions = ttk.Frame(body)
        actions.grid(sticky="ew", pady=10)
        self.polish = ttk.Button(actions, text="Polish with Gemini", style="Primary.TButton",
                                 command=lambda: self.analyze(False))
        self.polish.pack(side="left")
        self.variations = ttk.Button(actions, text="Get 5 versions", command=lambda: self.analyze(True))
        self.variations.pack(side="left", padx=8)
        self.review_status = tk.StringVar()
        ttk.Label(body, textvariable=self.review_status, wraplength=590).grid(sticky="w", pady=(0, 8))
        self.tones = ttk.Combobox(body, state="disabled", width=20)
        self.tones.grid(sticky="w", pady=(0, 6))
        self.tones.bind("<<ComboboxSelected>>", lambda _event: self._show_option())
        self.output = self._text_box(body, 7, 6)
        footer = ttk.Frame(body)
        footer.grid(sticky="ew", pady=(10, 0))
        self.apply_button = ttk.Button(footer, text="Apply", style="Primary.TButton", command=self.apply)
        self.apply_button.pack(side="left")
        self.copy_button = ttk.Button(footer, text="Copy", command=self.copy)
        self.copy_button.pack(side="left", padx=8)
        ttk.Button(footer, text="Dismiss", command=self.dismiss).pack(side="right")

    def _text_box(self, parent, height, row):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        text = tk.Text(frame, height=height, wrap="word", font=("Segoe UI", 11), bg=WHITE, fg=INK,
                       relief="flat", padx=9, pady=7, highlightthickness=1, highlightbackground="#d1dae8",
                       highlightcolor=BLUE, undo=False)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", expand=True, fill="both")
        return text

    @staticmethod
    def _set_text(widget, text, editable=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if not editable:
            widget.configure(state="disabled")

    def capture(self):
        if self.pending_capture or self.pending_apply:
            return
        if self.review.state() != "withdrawn":
            self.review.lift()
            return
        hwnd = windows.foreground()
        if self.paused or not hwnd:
            self.manual("Editor integration is paused." if self.paused else "")
            return
        ours = windows.process_id(hwnd) == self.pid
        if ours:
            if self.target is None or hwnd != windows.own_window(self.overlay):
                self.manual()
                return
            hwnd = self.target.window
            windows.restore_foreground(hwnd)
        self.overlay.withdraw()
        self.pending_capture = True
        self.revision += 1
        token = self.revision
        self.root.after(70 if ours else 0, lambda: self.worker.submit("capture", token, hwnd))

    def manual(self, message=""):
        if self.pending_capture or self.pending_apply:
            return
        if self.review.state() != "withdrawn":
            self.review.lift()
            return
        self.revision += 1
        self.show_review(None, message)

    def show_review(self, excerpt, message=""):
        self.overlay.withdraw()
        self.excerpt = excerpt
        self.options = []
        self.scope.set({
            "paragraph": "Current paragraph · Choose an alternative to copy or apply.",
            "selection": "Selected text · Only this excerpt is sent when you request a rewrite.",
            "field": "Current text field · This field is sent when you request a rewrite.",
            "manual": "Paste or type text below. Only that text is sent when you request a rewrite.",
        }[excerpt.scope if excerpt else "manual"])
        self._set_text(self.source, excerpt.text if excerpt else "", editable=excerpt is None)
        self.tones.configure(state="disabled", values=[])
        self.tones.set("")
        self._show_option()
        self._set_request_controls(True)
        self.review_status.set(message)
        self.review.deiconify()
        self.review.lift()
        if not excerpt:
            self.source.focus_set()

    def _set_request_controls(self, available):
        state = "normal" if available else "disabled"
        self.polish.configure(state=state)
        self.variations.configure(state=state)

    def analyze(self, alternatives):
        source = self.excerpt.text if self.excerpt else self.source.get("1.0", "end-1c")
        try:
            key = settings.load_key()
        except OSError:
            self.review_status.set("The saved key could not be read. Update it in Settings.")
            return
        if not key:
            self.review_status.set("Add your Gemini API key in Settings first.")
            self.open_settings()
            return
        self.options = []
        self.tones.set("")
        self.tones.configure(state="disabled", values=[])
        self._show_option()
        self._set_request_controls(False)
        self.source.configure(state="disabled")
        self.review_status.set("Waiting for Gemini…")
        revision, model = self.revision, self.settings.model

        def send():
            try:
                result = request_rewrites(source, key, model, alternatives)
                self.network.put((revision, "", result))
            except GeminiError as exc:
                self.network.put((revision, str(exc), []))

        threading.Thread(target=send, name="Gemini request", daemon=True).start()

    def _show_option(self):
        index = self.tones.current()
        option = self.options[index][1] if 0 <= index < len(self.options) else ""
        self._set_text(self.output, option)
        self.copy_button.configure(state="normal" if option else "disabled")
        can_apply = option and self.excerpt and option != self.excerpt.text
        self.apply_button.configure(state="normal" if can_apply else "disabled")

    def _option(self):
        index = self.tones.current()
        return self.options[index][1] if 0 <= index < len(self.options) else ""

    def copy(self):
        if self._option():
            try:
                windows.copy_text(self.hwnd, self._option())
                self.review_status.set("Copied to the Windows clipboard.")
            except (OSError, ValueError):
                self.review_status.set("The clipboard is unavailable. Try Copy again.")

    def apply(self):
        replacement = self._option()
        if not self.excerpt or not replacement or self.pending_apply or self.paused:
            self.review_status.set("Editor integration is paused or the original field is unavailable. Use Copy.")
            return
        excerpt = self.excerpt
        self.pending_apply = "review"
        token = self.revision
        if windows.process_id(windows.foreground()) == self.pid:
            windows.restore_foreground(excerpt.target.window)
        self.review.withdraw()
        self.root.after(120, lambda: self.worker.submit("apply", token, excerpt, replacement, self.hwnd))

    def dismiss(self):
        self.worker.submit("clear", self.revision)
        self.revision += 1
        self.excerpt = None
        self.options = []
        self.review.withdraw()
        self._set_text(self.source, "")
        self._set_text(self.output, "")
        self.review_status.set("")

    def _worker_results(self):
        while True:
            try:
                action, error, result = self.worker.results.get_nowait()
            except queue.Empty:
                return
            if action == "startup":
                self.ui_fault = f"Windows accessibility could not start ({error}). Manual review is available."
                self._refresh_settings_status()
            elif action == "probe":
                self.pending_probe = False
                target, excerpt, candidate = result or (None, None, None)
                previous = self.target
                self.target = target
                if not previous or not target or previous.identity != target.identity or previous.window != target.window:
                    self.word = self.hidden_word = None
                if self.probe_requested_word:
                    self.word = (excerpt, candidate) if candidate else None
                    if self.word != self.hidden_word:
                        self.hidden_word = None
            elif action == "paragraph":
                self.auto_pending = False
                paragraph, continuous = result or (None, False)
                if not continuous:
                    self._observe(None)
                self._observe(paragraph if self.settings.automatic and not self.paused and self.review.state() == "withdrawn" else None)
            elif action == "capture":
                self.pending_capture = False
                self.show_review(result[1] if result else None, error)
            elif action == "apply":
                mode, self.pending_apply = self.pending_apply, False
                if mode == "review":
                    if error:
                        self.review.deiconify()
                        self.review.lift()
                        self.review_status.set(error)
                    else:
                        self.dismiss()
                elif error:
                    self.inline_notice = error
                else:
                    self.auto_hide()
                    self._observe(None)
                    self.word = None

    def _network_results(self):
        while True:
            try:
                revision, error, result = self.network.get_nowait()
            except queue.Empty:
                return
            if revision != self.revision:
                continue
            self._set_request_controls(True)
            if not self.excerpt:
                self.source.configure(state="normal")
            self.options = result
            if result:
                self.tones.configure(state="readonly", values=[tone for tone, _ in result])
                self.tones.current(0)
            self._show_option()
            self.review_status.set(error or "Choose a version to apply or copy.")

    def tick(self):
        if self.tray.take():
            self.open_settings()
        if self.hotkey.take():
            self.capture()
        self._worker_results()
        self._network_results()
        moment = time.monotonic()
        active = not self.paused and not self.ui_fault.startswith("Windows accessibility")
        try:
            excerpt, more, options, error = self.auto_queue.get_nowait()
            self.auto_busy = False
            if self.settings.automatic and not self.paused and self.auto_seen == excerpt:
                self.inline_notice = error
                if options and more and self.auto_result:
                    self.variants = tuple(options)
                elif options and not more:
                    self.auto_result = (excerpt, options[0][1])
        except queue.Empty:
            pass
        if active and (self.settings.spelling or self.settings.overlay or self.settings.automatic) and self.review.state() == "withdrawn":
            if moment >= self.next_probe and not self.pending_probe and not self.pending_capture and not self.pending_apply:
                input_id, idle_ms = windows.last_input()
                read_word = self.settings.spelling and input_id != self.word_input and 275 <= idle_ms <= 5000
                if read_word:
                    self.word_input = input_id
                self.pending_probe = True
                self.probe_requested_word = read_word
                self.next_probe = moment + 0.32
                self.worker.submit("probe", read_word)
                if self.settings.automatic and not self.auto_pending:
                    self.auto_pending = True
                    self.worker.submit("paragraph")
        self._update_overlay()
        self.tick_id = self.root.after(40, self.tick)

    def exit(self):
        self.root.after_cancel(self.tick_id)
        self.overlay_guard.close()
        self.tray.close()
        self.hotkey.close()
        self.root.destroy()


def _smoke_test():
    # Runs in the packaged executable to catch missing Windows or dictionary dependencies.
    root = tk.Tk()
    root.withdraw()
    try:
        app = WritingAssistant(root, background=True)
        app.worker.submit("probe", False)
        action, error, _ = app.worker.results.get(timeout=25)
        if action != "probe":
            raise RuntimeError(error)
        if Spelling().suggest("writng", True) != "writing":
            raise RuntimeError("English dictionary unavailable.")
        if windows.dpapi(windows.dpapi(b"smoke test", True), False) != b"smoke test":
            raise RuntimeError("Windows key storage failed.")
        app.exit()
        return 0
    except Exception:
        # A windowed executable may have no stderr. The build checks the exit code.
        return 1


def main():
    # Initialize per-monitor awareness before creating any Tk windows.
    try:
        windows.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        pass
    if "--self-test" in sys.argv:
        raise SystemExit(_smoke_test())
    mutex = windows.create_mutex(None, False, r"Local\WritingAssistant")
    already_running = ctypes.get_last_error() == 183
    try:
        root = tk.Tk()
        root.withdraw()
        if not mutex or already_running:
            if "--background" not in sys.argv:
                messagebox.showinfo("Writing Assistant", "Writing Assistant is already running or could not start. Check the tray.")
            root.destroy()
            return
        WritingAssistant(root, background="--background" in sys.argv)
        root.mainloop()
    finally:
        if mutex:
            windows.close_handle(mutex)
