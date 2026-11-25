import json
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Requires Windows")
class WindowsTests(unittest.TestCase):
    def test_uia_worker_can_initialize(self):
        # Run initialization in the same COM apartment type the desktop app uses.
        from writing_assistant.worker import EditorWorker

        worker = EditorWorker()
        worker.submit("probe", False)
        action, error, _ = worker.results.get(timeout=25)
        self.assertNotEqual(action, "startup", error)
        self.assertEqual(action, "probe")

    def test_dpapi_key_add_update_remove(self):
        from writing_assistant import settings

        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "gemini-key.dpapi"
            with patch.object(settings, "CREDENTIAL", credential):
                self.assertEqual(settings.load_key(), "")
                settings.save_key("key-for-local-testing")
                self.assertNotIn(b"key-for-local-testing", credential.read_bytes())
                self.assertEqual(settings.load_key(), "key-for-local-testing")
                settings.save_key("replacement-local-key")
                self.assertEqual(settings.load_key(), "replacement-local-key")
                settings.remove_key()
                self.assertEqual(settings.load_key(), "")

    def test_real_spelling_dictionary(self):
        from writing_assistant.core import Spelling

        spelling = Spelling()
        self.assertEqual(spelling.suggest("happpi", False), "happy")
        self.assertEqual(spelling.suggest("writng", True), "writing")
        self.assertIsNone(spelling.suggest("writing", True))


    def test_cross_process_native_edit_and_password(self):
        import tkinter as tk
        from writing_assistant import windows
        from writing_assistant.worker import EditorWorker

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        self.addCleanup(root.destroy)
        owner = windows.own_window(root)
        fixture = subprocess.Popen(
            [sys.executable, "-m", "tests.windows_fixture"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(fixture.stdout.close)

        def cleanup():
            fixture.stdin.close()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
                fixture.wait()

        self.addCleanup(cleanup)
        hwnd = json.loads(fixture.stdout.readline())

        def control(value):
            fixture.stdin.write(f"{value}\n")
            fixture.stdin.flush()
            return json.loads(fixture.stdout.readline())

        worker = EditorWorker()

        def request(name, *args):
            worker.submit(name, *args)
            action, error, result = worker.results.get(timeout=25)
            self.assertEqual(action, name, error)
            return error, result

        if not control(0):
            self.skipTest("Windows runner did not grant foreground access to the fixture")
        error, result = request("probe", True)
        self.assertEqual(error, "")
        _, word, candidate = result
        self.assertIsNotNone(word, "Native edit did not expose a usable caret.")
        self.assertEqual((word.text, candidate), ("writng", "writing"))
        error, _ = request("apply", None, word, candidate, owner)
        self.assertEqual(error, "")

        def assert_corrected():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if control(3) == "I am writing now.":
                    return
                time.sleep(0.05)
            self.assertEqual(control(3), "I am writing now.")

        assert_corrected()
        self.assertTrue(control(0))
        error, result = request("capture", 1, hwnd)
        self.assertEqual(error, "")
        _, excerpt = result
        self.assertEqual((excerpt.scope, excerpt.text), ("field", "I am writng now."))
        error, _ = request("apply", 1, excerpt, "I am writing now.", owner)
        self.assertEqual(error, "")
        self.assertEqual(control(3), "I am writing now.")

        self.assertTrue(control(1))
        error, result = request("capture", 2, hwnd)
        self.assertEqual(error, "")
        _, excerpt = result
        self.assertEqual((excerpt.scope, excerpt.text), ("selection", "writng"))
        error, _ = request("apply", 2, excerpt, "writing", owner)
        self.assertEqual(error, "")
        assert_corrected()

        self.assertTrue(control(2))
        error, result = request("probe", True)
        self.assertEqual((error, result), ("", (None, None, None)))
        error, result = request("capture", 3, hwnd)
        self.assertTrue(error)
        self.assertIsNone(result)
