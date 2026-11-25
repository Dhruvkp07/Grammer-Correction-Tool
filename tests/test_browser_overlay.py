import sys
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Requires Windows")
class BrowserOverlayTests(unittest.TestCase):
    def test_edge_contenteditable_clicks(self):
        import tkinter as tk
        from writing_assistant.app import WritingAssistant
        from writing_assistant import windows
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Install playwright to run the Edge integration test")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=False,
                                                args=["--force-renderer-accessibility", "--enable-features=UiaProvider", "--window-position=0,0"])
            page = browser.new_page()
            page.set_content('<div role="textbox" aria-label="Message" contenteditable="true" '
                             'style="margin:100px;padding:20px;border:1px solid"></div>')
            field = page.get_by_role("textbox")
            root = tk.Tk()
            app = WritingAssistant(root, background=True)
            try:
                root.withdraw()
                app.settings.automatic = True
                app.settings.spelling = True

                def wait_for(predicate, description):
                    deadline = time.monotonic() + 14
                    while time.monotonic() < deadline:
                        root.update()
                        if predicate():
                            return
                        page.wait_for_timeout(40)
                    from writing_assistant.editor import Editor
                    editor = Editor()
                    element = editor.uia.GetFocusedElement()
                    self.fail(f"{description}. Focus type={element.CurrentControlType}, "
                              f"class={element.CurrentClassName}, keyboard={element.CurrentHasKeyboardFocus}, "
                              f"password flag type={type(element.GetCurrentPropertyValueEx(30019, True))}, "
                              f"status={app.ui_fault} {app.inline_notice}")

                def click(button):
                    x = button.winfo_rootx() + button.winfo_width() // 2
                    y = button.winfo_rooty() + button.winfo_height() // 2
                    windows.user.SetCursorPos(x, y)
                    windows.user.mouse_event(2, 0, 0, 0, 0)
                    windows.user.mouse_event(4, 0, 0, 0, 0)

                def rewrites(source, _key, _model, alternatives=False):
                    if alternatives:
                        return [(tone, f"{tone} message.") for tone in ("Professional", "Casual", "Concise")]
                    return [("Polished", source.replace("i am", "I am") + ".")]

                with patch("writing_assistant.app.settings.load_key", return_value="test"), \
                     patch("writing_assistant.app.request_rewrites", side_effect=rewrites):
                    page.bring_to_front()
                    field.click()
                    # CDP can focus a DOM node without putting the native window in
                    # front. A real click in the editor establishes desktop focus.
                    x, y = field.evaluate("""el => {
                        const r = el.getBoundingClientRect();
                        return [(screenX + (outerWidth - innerWidth) / 2 + r.x + 20) * devicePixelRatio,
                                (screenY + outerHeight - innerHeight + r.y + 15) * devicePixelRatio];
                    }""")
                    windows.user.SetCursorPos(round(x), round(y))
                    windows.user.mouse_event(2, 0, 0, 0, 0)
                    windows.user.mouse_event(4, 0, 0, 0, 0)
                    wait_for(lambda: app.target is not None, "Browser editor was not recognized")
                    field.press_sequentially("i am happpi", delay=60)
                    # Playwright's input is delivered by DevTools. Send a physical
                    # Shift tap so GetLastInputInfo observes the typing pause.
                    windows.user.keybd_event(0x10, 0, 0, 0)
                    windows.user.keybd_event(0x10, 0, 2, 0)
                    wait_for(lambda: app.word_button.winfo_ismapped() and app.word_button["text"] == "happy",
                             "Local word suggestion missing")
                    click(app.word_button)
                    wait_for(lambda: field.inner_text() == "i am happy", "Word click failed")
                    wait_for(lambda: not app.pending_apply, "Word insertion still pending")
                    # Make a new edit so auto-polish observes a changed paragraph.
                    field.press("End")
                    field.press_sequentially(" today", delay=70)
                    wait_for(lambda: app.preview.winfo_ismapped() and "today" in app.preview["text"],
                             "Polished paragraph missing")
                    click(app.preview)
                    wait_for(lambda: field.inner_text() == "I am happy today.", "Paragraph click failed")
                    self.assertEqual(app.review.state(), "withdrawn")
            finally:
                app.exit()
                browser.close()
