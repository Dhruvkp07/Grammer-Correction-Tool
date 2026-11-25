"""Verify the boundaries around cross-app text access with a fake UIA provider."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

name = "writing_assistant._editor_test"
source = Path(__file__).resolve().parents[1] / "writing_assistant" / "editor.py"
spec = importlib.util.spec_from_file_location(name, source)
editor_module = importlib.util.module_from_spec(spec)
native = Mock()
with patch.dict(sys.modules, {name: editor_module, "writing_assistant.windows": native}):
    spec.loader.exec_module(editor_module)


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.editor = editor_module.Editor.__new__(editor_module.Editor)
        self.editor.uia = Mock()
        self.editor.walker = Mock()
        self.editor.com_error = RuntimeError
        self.target = editor_module.Target(500, (123, 1, 2), (10, 10, 40, 30))
        self.element = Mock(
            CurrentControlType=editor_module.EDIT, CurrentHasKeyboardFocus=True,
            CurrentNativeWindowHandle=900, CurrentIsEnabled=True,
            CurrentProcessId=123, CurrentBoundingRectangle=(10, 10, 40, 30),
        )
        self.element.GetRuntimeId.return_value = (1, 2)
        self.element.GetCurrentPropertyValueEx.return_value = False
        self.editor.uia.GetFocusedElement.return_value = self.element
        self.editor.walker.GetParentElement.return_value = None
        self.native = editor_module.windows
        self.native.reset_mock()
        self.native.foreground.return_value = 500
        self.native.process_id.return_value = 123
        self.native.native_password.return_value = False
        self.native.active_modifiers.return_value = False

    def test_rejects_password_before_opening_any_patterns(self):
        for state in (True, None, object()):
            with self.subTest(state=state):
                self.element.GetCurrentPropertyValueEx.return_value = state
                self.assertEqual(self.editor.probe(True), (None, None))
                self.element.GetCurrentPattern.assert_not_called()

    def test_rejects_native_password_independent_of_uia(self):
        self.native.native_password.return_value = True
        with self.assertRaises(editor_module.EditorError):
            self.editor.capture(500)
        self.element.GetCurrentPropertyValueEx.assert_not_called()
        self.element.GetCurrentPattern.assert_not_called()

    def test_refuses_protected_ancestor_before_reading(self):
        self.editor.walker.GetParentElement.return_value = SimpleNamespace(CurrentIsPassword=True)
        self.assertEqual(self.editor.probe(True), (None, None))
        self.element.GetCurrentPattern.assert_not_called()

    def test_uses_selection_without_reading_entire_field(self):
        selection = Mock()
        selection.CompareEndpoints.return_value = -1
        selection.GetText.return_value = "selected text"
        value = Mock(CurrentIsReadOnly=False)
        text = Mock()
        self.editor._patterns = Mock(return_value=(value, text))
        self.editor._selection = Mock(return_value=selection)
        excerpt, selected = self.editor.capture(500)
        self.assertEqual((excerpt.scope, excerpt.text, selected), ("selection", "selected text", selection))
        self.assertNotIn("CurrentValue", repr(value.mock_calls))
        selection.GetText.assert_called_once_with(4001)

    def test_refuses_changed_selection_without_replacing_or_copying(self):
        value = Mock(CurrentIsReadOnly=False, CurrentValue="Edited in another window.")
        self.editor._patterns = Mock(return_value=(value, None))
        original = editor_module.Excerpt(self.target, "field", "Original text.", (), self.target.box)
        with self.assertRaisesRegex(editor_module.EditorError, "changed"):
            self.editor.apply(original, "Polished text.", 70, None)
        value.SetValue.assert_not_called()
        self.native.copy_text.assert_not_called()
        self.native.paste.assert_not_called()

    def test_only_explicit_apply_replaces_writable_field(self):
        value = Mock(CurrentIsReadOnly=False, CurrentValue="Original text.")
        self.editor._patterns = Mock(return_value=(value, None))
        original, text_range = self.editor.capture(500)
        value.SetValue.assert_not_called()
        self.editor.apply(original, "Polished text.", 70, text_range)
        value.SetValue.assert_called_once_with("Polished text.")

    def test_rejects_same_text_from_different_range(self):
        selection = Mock()
        selection.CompareEndpoints.return_value = -1
        selection.GetText.return_value = "text"
        old = Mock()
        old.Compare.return_value = False
        value = Mock(CurrentIsReadOnly=False)
        text = Mock()
        self.editor._patterns = Mock(return_value=(value, text))
        self.editor._selection = Mock(return_value=selection)
        original, _ = self.editor.capture(500)
        with self.assertRaisesRegex(editor_module.EditorError, "moved"):
            self.editor.apply(original, "new text", 70, old)
        self.native.copy_text.assert_not_called()

    def test_aborts_paste_when_foreground_changes_after_clipboard_write(self):
        selection = Mock()
        selection.CompareEndpoints.return_value = -1
        selection.GetText.return_value = "old text"
        old = Mock()
        old.Compare.return_value = True
        value = Mock(CurrentIsReadOnly=False)
        text = Mock()
        self.editor._patterns = Mock(return_value=(value, text))
        self.editor._selection = Mock(return_value=selection)
        original, _ = self.editor.capture(500)
        self.native.foreground.side_effect = (500, 500, 500, 999, 999)
        try:
            with self.assertRaisesRegex(editor_module.EditorError, "changed"):
                self.editor.apply(original, "new text", 70, old)
        finally:
            self.native.foreground.side_effect = None
        selection.Select.assert_not_called()
        self.native.paste.assert_not_called()
