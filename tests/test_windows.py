import sys
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
        self.assertEqual(spelling.suggest("writng", True), "writing")
        self.assertIsNone(spelling.suggest("writing", True))
