"""Work with the foreground editor through Windows UI Automation."""

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import windows
from .core import MAX_SOURCE, trailing_word

EDIT, DOCUMENT = 50004, 50030
PASSWORD_PROPERTY = 30019
VALUE, TEXT, TEXT2 = 10002, 10014, 10024
READ_ONLY = 40015
START, END, CHARACTER = 0, 1, 0


class EditorError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    window: int
    identity: tuple
    box: tuple


@dataclass(frozen=True)
class Excerpt:
    target: Target
    scope: str
    text: str
    context: tuple
    box: tuple
    finished: bool = False


def _as_rect(box):
    if hasattr(box, "left"):
        return (box.left, box.top, box.right, box.bottom)
    return tuple(box)


def _surrounding(text_range, endpoint, count):
    neighbor = text_range.Clone()
    other = END if endpoint == START else START
    neighbor.MoveEndpointByRange(other, text_range, endpoint)
    neighbor.MoveEndpointByUnit(endpoint, CHARACTER, count)
    return neighbor.GetText(abs(count) + 1)


class Editor:
    def __init__(self):
        # comtypes uses these flags for the first importing thread.
        sys.coinit_flags = 0
        import comtypes
        from comtypes.client import CreateObject, GetModule

        comtypes.CoInitializeEx(0)  # The worker owns this MTA for its lifetime.
        self.com_error = comtypes.COMError
        path = Path(os.environ["SystemRoot"]) / "System32" / "UIAutomationCore.dll"
        self.types = GetModule(str(path))
        self.uia = CreateObject(self.types.CUIAutomation8, interface=self.types.IUIAutomation)
        self.walker = self.uia.RawViewWalker

    def _pattern(self, element, pattern, interface):
        try:
            underlying = element.GetCurrentPattern(pattern)
            return underlying.QueryInterface(interface) if underlying else None
        except self.com_error:
            return None

    def _focus(self):
        hwnd = windows.foreground()
        pid = windows.process_id(hwnd)
        if not pid or pid == os.getpid():
            return None
        element = self.uia.GetFocusedElement()
        if not element or not element.CurrentHasKeyboardFocus:
            return None
        if element.CurrentControlType not in (EDIT, DOCUMENT) or not element.CurrentIsEnabled:
            return None
        if windows.native_password(element.CurrentNativeWindowHandle):
            return None
        # Unsupported password status on the focused editor is treated as sensitive.
        state = element.GetCurrentPropertyValueEx(PASSWORD_PROPERTY, True)
        if state is not False and not (type(state) is int and state == 0):
            return None
        parent = self.walker.GetParentElement(element)
        for _ in range(32):
            if not parent:
                break
            if parent.CurrentIsPassword or windows.native_password(parent.CurrentNativeWindowHandle):
                return None
            if parent.CurrentNativeWindowHandle == hwnd:
                break
            parent = self.walker.GetParentElement(parent)
        else:
            return None
        if windows.foreground() != hwnd:
            return None
        identity = (element.CurrentProcessId, *element.GetRuntimeId())
        box = _as_rect(element.CurrentBoundingRectangle)
        return Target(hwnd, identity, box), element

    def _patterns(self, element):
        value = self._pattern(element, VALUE, self.types.IUIAutomationValuePattern)
        text = self._pattern(element, TEXT, self.types.IUIAutomationTextPattern)
        return value, text

    def _editable(self, value, text_range=None):
        if value is not None:
            return not value.CurrentIsReadOnly
        if text_range is None:
            return False
        state = text_range.GetAttributeValue(READ_ONLY)
        return state is False or (type(state) is int and state == 0)

    def _selection(self, text):
        selections = text.GetSelection()
        if selections and selections.Length:
            if selections.Length != 1:
                raise EditorError("Choose one continuous text selection.")
            return selections.GetElement(0)
        return None

    def _caret(self, element, text):
        pattern = self._pattern(element, TEXT2, self.types.IUIAutomationTextPattern2)
        if pattern:
            active, caret = pattern.GetCaretRange()
            if active and caret:
                return caret
        caret = self._selection(text)
        if caret and caret.CompareEndpoints(START, caret, END) == 0:
            return caret
        return None

    def probe(self, read_word):
        focus = self._focus()
        if not focus:
            return None, None
        target, element = focus
        value, text = self._patterns(element)
        if not value and not text:
            return None, None
        if value and value.CurrentIsReadOnly:
            return None, None
        if not read_word:
            return target, None
        excerpt, _ = self._word(target, element, value, text)
        return target, excerpt

    def _word(self, target, element, value, text):
        if not text:
            return None, None
        selection = self._selection(text)
        if selection and selection.CompareEndpoints(START, selection, END) != 0:
            return None, None
        caret = self._caret(element, text)
        if not caret or not self._editable(value, caret):
            return None, None
        if element.CurrentControlType == DOCUMENT:
            nearby = caret.Clone()
            nearby.MoveEndpointByUnit(START, CHARACTER, -32)
            nearby.MoveEndpointByUnit(END, CHARACTER, 1)
            if not self._document_selection_allowed(nearby):
                return None, None
        before = _surrounding(caret, START, -32)
        after = _surrounding(caret, END, 1)
        match = trailing_word(before, after)
        if not match:
            return None, None
        word, space = match
        word_range = caret.Clone()
        word_range.MoveEndpointByUnit(START, CHARACTER, -len(word + space))
        if space:
            word_range.MoveEndpointByUnit(END, CHARACTER, -1)
        if word_range.GetText(len(word) + 1) != word:
            return None, None
        rect = word_range.GetBoundingRectangles()
        box = target.box
        if rect and len(rect) >= 4:
            left, top, width, height = rect[-4:]
            box = (left, top, left + width, top + height)
        context = (before, after)
        return Excerpt(target, "word", word, context, box, bool(space)), word_range

    def _document_selection_allowed(self, selected):
        # A document may embed separate controls. Do not read through a protected one.
        children = selected.GetChildren()
        if not children:
            return True
        if children.Length > 100:
            return False
        for index in range(children.Length):
            child = children.GetElement(index)
            if child.CurrentIsPassword or child.CurrentControlType == EDIT:
                return False
        return True

    def _excerpt(self, target, element, value, text):
        selected = self._selection(text) if text else None
        if selected and selected.CompareEndpoints(START, selected, END) != 0:
            if not self._editable(value, selected):
                raise EditorError("This app reports the selection as read-only or unsupported.")
            if element.CurrentControlType == DOCUMENT and not self._document_selection_allowed(selected):
                raise EditorError("Select text within a single editor without embedded fields.")
            source = selected.GetText(MAX_SOURCE + 1)
            scope = "selection"
            context = (_surrounding(selected, START, -24), _surrounding(selected, END, 24))
        elif element.CurrentControlType == EDIT:
            document = text.DocumentRange if text else None
            if not self._editable(value, document):
                raise EditorError("This app reports the field as read-only or unsupported.")
            source = value.CurrentValue if value else document.GetText(MAX_SOURCE + 1)
            scope, context, selected = "field", (), document
        else:
            raise EditorError("Select the text you want to polish in this document.")
        if not source or not source.strip():
            raise EditorError("There is no text to review.")
        if len(source) > MAX_SOURCE:
            raise EditorError(f"Select an excerpt of at most {MAX_SOURCE:,} characters.")
        return Excerpt(target, scope, source, context, target.box), selected

    def paragraph(self):
        focus = self._focus()
        if not focus:
            return None, None
        target, element = focus
        value, text = self._patterns(element)
        if not text:
            return None, None
        caret = self._caret(element, text)
        if not caret or not self._editable(value, caret):
            return None, None
        region = caret.Clone()
        region.ExpandToEnclosingUnit(4)  # TextUnit_Paragraph
        if not self._document_selection_allowed(region):
            return None, None
        source = region.GetText(MAX_SOURCE + 1)
        if len(source) > MAX_SOURCE or windows.foreground() != target.window:
            return None, None
        # Chromium can include an unselectable block delimiter in the UIA range.
        # Do not replace the separator between this draft and the next paragraph.
        body = source.rstrip("\r\n")
        while source != body:
            if region.MoveEndpointByUnit(END, CHARACTER, -1) != -1:
                return None, None
            shorter = region.GetText(MAX_SOURCE + 1)
            if shorter == source or not shorter.startswith(body):
                return None, None
            source = shorter
        return Excerpt(target, "paragraph", source, (), target.box), region

    def capture(self, expected_window):
        focus = self._focus()
        if not focus or focus[0].window != expected_window:
            raise EditorError("Focus a supported text field. You can also paste text into the review panel.")
        target, element = focus
        excerpt, text_range = self._excerpt(target, element, *self._patterns(element))
        if windows.foreground() != expected_window:
            raise EditorError("The active window changed. Try again.")
        return excerpt, text_range

    def _matches(self, original, current):
        return current and (
            original.target.window, original.target.identity, original.scope, original.text, original.context
        ) == (
            current.target.window, current.target.identity, current.scope, current.text, current.context
        )

    def apply(self, original, replacement, owner, original_range):
        focus = self._focus()
        if not focus or focus[0].identity != original.target.identity or focus[0].window != original.target.window:
            raise EditorError("The original text field is no longer focused. Use Copy to keep the rewrite.")
        target, element = focus
        value, text = self._patterns(element)
        whole_draft = False
        if original.scope == "paragraph":
            current, text_range = self.paragraph()
            # Browser caret and DocumentRange providers can expose different end
            # positions for the same draft. Whole-field equality is unambiguous.
            if text and element.CurrentControlType == EDIT:
                document = text.DocumentRange
                whole_draft = (self._editable(value, document)
                               and self._document_selection_allowed(document)
                               and document.GetText(len(original.text) + 1) == original.text)
                if whole_draft and current is None:
                    current, text_range = original, document
        elif original.scope == "word":
            current, text_range = self._word(target, element, value, text)
        else:
            current, text_range = self._excerpt(target, element, value, text)
        if not self._matches(original, current):
            raise EditorError("The original text or selection changed. Capture it again or use Copy.")
        if not whole_draft and original_range and text_range and not original_range.Compare(text_range):
            raise EditorError("The caret or selection moved. Capture it again or use Copy.")
        if windows.foreground() != target.window or windows.active_modifiers():
            raise EditorError("Return to the original editor and release any shortcut keys.")
        if current.scope == "field" and value:
            value.SetValue(replacement)
            return
        if not text_range or not text:
            raise EditorError("This editor cannot apply the replacement. Use Copy.")
        marker = windows.copy_text(owner, replacement)
        focused = self._focus()
        if not focused or focused[0].identity != target.identity or focused[0].window != target.window:
            raise EditorError("The active field changed. The replacement is available on the clipboard.")
        def normalized(value):
            return value.replace("\r\n", "\n").replace("\xa0", " ")

        def unique_selection(selected):
            # Chromium may use equivalent offsets on different accessibility nodes.
            # Accept a text match only if the bounded, editable field has exactly
            # one occurrence and the selection belongs to that same field.
            if element.CurrentControlType != EDIT or not self._document_selection_allowed(text.DocumentRange):
                return False
            document = text.DocumentRange
            full = document.GetText(MAX_SOURCE + 1)
            if len(full) > MAX_SOURCE:
                return False
            needle = normalized(current.text)
            haystack = normalized(full)
            return (needle and haystack.find(needle) >= 0 and haystack.find(needle) == haystack.rfind(needle)
                    and selected.CompareEndpoints(START, document, START) >= 0
                    and selected.CompareEndpoints(END, document, END) <= 0)

        def selection_matches():
            deadline = time.monotonic() + 0.45
            while windows.foreground() == target.window:
                selected = self._selection(text)
                if selected and normalized(selected.GetText(len(current.text) + 2)) == normalized(current.text):
                    if whole_draft and text.DocumentRange.GetText(len(current.text) + 1) == current.text:
                        return True
                    if ((selected.CompareEndpoints(START, text_range, START) == 0
                             and selected.CompareEndpoints(END, text_range, END) == 0) or unique_selection(selected)):
                        return True
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.025)
            return False

        try:
            text_range.Select()
        except self.com_error:
            pass
        if not selection_matches():
            # Some browser editors expose a range before they implement UIA Select.
            # Use keyboard selection only from a revalidated starting position.
            focused = self._focus()
            if (not focused or focused[0].identity != target.identity or focused[0].window != target.window
                    or windows.active_modifiers()):
                raise EditorError("The target editor changed. Try the suggestion again.")
            if current.scope == "word":
                live, _ = self._word(target, element, value, text)
                if not self._matches(current, live):
                    raise EditorError("The word moved. Try the latest suggestion.")
                windows.select_word_left(len(current.text), current.finished)
            elif (current.scope == "paragraph" and element.CurrentControlType == EDIT
                  and text.DocumentRange.GetText(len(current.text) + 1) == current.text):
                windows.select_all()
            elif current.scope == "paragraph":
                caret = self._caret(element, text)
                if (not caret or caret.CompareEndpoints(START, text_range, START) < 0
                        or caret.CompareEndpoints(END, text_range, END) > 0):
                    raise EditorError("The cursor moved outside this paragraph. Try the latest suggestion.")
                tail = text_range.Clone()
                tail.MoveEndpointByRange(START, caret, END)
                windows.select_paragraph(len(tail.GetText(MAX_SOURCE)), len(current.text))
            else:
                raise EditorError("This editor could not select the suggestion. Use Copy.")
            if not selection_matches():
                raise EditorError("The editor did not confirm the replacement range. Use Copy.")
        focused = self._focus()
        if (not focused or focused[0].identity != target.identity or focused[0].window != target.window):
            raise EditorError("The focused field changed before paste. Use Copy.")
        if not windows.clipboard_still_matches(owner, marker):
            raise EditorError("The clipboard changed before paste. Use Copy.")
        if windows.foreground() != target.window or windows.active_modifiers():
            raise EditorError("Return to the original editor and release any shortcut keys.")
        windows.paste()
        if current.scope != "paragraph":
            return

        def still_in_editor():
            focus = self._focus()
            return focus and focus[0].window == target.window and focus[0].identity == target.identity

        def inserted(timeout):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and still_in_editor():
                caret = self._caret(element, text)
                if caret:
                    recent = _surrounding(caret, START, -len(replacement))
                    if normalized(recent).endswith(normalized(replacement)):
                        return True
                time.sleep(0.04)
            return False

        if inserted(1.0):
            return
        # Some chat editors cancel paste. Retry by typing only while the exact
        # original draft is still selected, to avoid duplicating a late paste.
        if (all(ord(ch) >= 32 for ch in replacement) and still_in_editor()
                and selection_matches() and still_in_editor() and not windows.active_modifiers()):
            windows.insert_text(replacement)
            if inserted(2.0):
                return
        raise EditorError("Could not confirm insertion. The rewrite is on your clipboard.")
