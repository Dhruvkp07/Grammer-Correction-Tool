"""Keep cross-process accessibility calls off the interface thread."""

import queue
import threading

from .core import Spelling
from .editor import Editor, EditorError


class EditorWorker:
    def __init__(self):
        self.jobs = queue.Queue()
        self.results = queue.SimpleQueue()
        threading.Thread(target=self._run, name="Windows UI Automation", daemon=True).start()

    def submit(self, action, *data):
        self.jobs.put((action, data))

    def _execute(self, editor, action, data):
        if action == "probe":
            read_word, = data
            target, word = editor.probe(read_word)
            if word and not self.spelling_failed:
                if self.spelling is None:
                    try:
                        self.spelling = Spelling()
                    except (ImportError, OSError, ValueError):
                        self.spelling_failed = True
                if self.spelling:
                    candidate = self.spelling.suggest(word.text, word.finished)
                    if candidate:
                        return target, word, candidate
            return target, word, None
        if action == "paragraph":
            excerpt, region = editor.paragraph()
            previous = self.ranges.get("paragraph")
            self.ranges["paragraph"] = region
            continuous = False
            if previous and region:
                try:
                    continuous = previous.CompareEndpoints(0, region, 0) == 0
                except editor.com_error:
                    pass
            return excerpt, continuous
        if action == "capture":
            token, hwnd = data
            excerpt, text_range = editor.capture(hwnd)
            self.ranges.clear()
            self.ranges[token] = text_range
            return token, excerpt
        if action == "apply":
            token, excerpt, value, hwnd = data
            editor.apply(excerpt, value, hwnd, self.ranges.get(token))
            return token
        raise ValueError("Unknown accessibility action.")

    def _run(self):
        self.ranges = {}
        self.spelling = None
        self.spelling_failed = False
        editor = None
        try:
            editor = Editor()
        except Exception as exc:
            # Report the failure without including provider messages or user text.
            self.results.put(("startup", type(exc).__name__, None))
        while True:
            action, data = self.jobs.get()
            if action == "clear":
                self.ranges.pop(data[0], None)
                continue
            if editor is None:
                self.results.put((action, "Windows accessibility is unavailable. Paste text into Review.", None))
                continue
            try:
                self.results.put((action, "", self._execute(editor, action, data)))
            except EditorError as exc:
                self.results.put((action, str(exc), None))
            except (editor.com_error, OSError, ValueError, TypeError, AttributeError):
                message = {
                    "capture": "This editor did not expose usable text. Paste text into Review.",
                    "apply": "Windows could not apply the replacement here. Use Copy.",
                }
                self.results.put((action, message.get(action, "Editor unavailable."), None))
