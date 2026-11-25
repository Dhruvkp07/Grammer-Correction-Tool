"""Native, cross-process editor used by the Windows integration test."""

import ctypes as c
import json
import sys
import threading
from ctypes import wintypes as w

from writing_assistant import windows

user = windows.user
bind = windows.bind
create = bind(user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR,
              w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p)
focus = bind(user, "SetFocus", w.HWND, w.HWND)
send = bind(user, "SendMessageW", w.LPARAM, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
post = bind(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
get_message = bind(user, "GetMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
translate = bind(user, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))
dispatch = bind(user, "DispatchMessageW", w.LPARAM, c.POINTER(w.MSG))
get_text = bind(user, "GetWindowTextW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
set_text = bind(user, "SetWindowTextW", w.BOOL, w.HWND, w.LPCWSTR)
quit_loop = bind(user, "PostQuitMessage", None, c.c_int)
FOCUS_MESSAGE = 0x8003


def main():
    hwnd = create(0, "STATIC", "Writing Assistant test editor", 0x10CF0000,
                  80, 80, 450, 180, None, None, None, None)
    style = 0x50810080
    editor = create(0, "EDIT", "I am writng now.", style, 20, 20, 370, 30, hwnd, None, None, None)
    password = create(0, "EDIT", "fixture-password", style | 0x20, 20, 65, 370, 30, hwnd, None, None, None)
    if not all((hwnd, editor, password)):
        raise c.WinError(c.get_last_error())

    @windows.subclass_proc
    def message_handler(window, message, action, data, _subclass, _reference):
        if message == FOCUS_MESSAGE:
            if action == 3:
                buffer = c.create_unicode_buffer(200)
                get_text(editor, buffer, len(buffer))
                print(json.dumps(buffer.value), flush=True)
            else:
                windows.restore_foreground(hwnd)
                if action == 2:
                    focus(password)
                else:
                    focus(editor)
                    set_text(editor, "I am writng now.")
                    send(editor, 0x00B1, 5 if action == 1 else 11, 11)  # EM_SETSEL
                print(json.dumps(windows.foreground() == hwnd), flush=True)
            return 0
        if message == 0x0010:
            quit_loop(0)
            return 0
        return windows.next_subclass(window, message, action, data)

    if not windows.set_subclass(hwnd, message_handler, 5, 0):
        raise c.WinError(c.get_last_error())

    def commands():
        for line in sys.stdin:
            post(hwnd, FOCUS_MESSAGE, int(line), 0)
        post(hwnd, 0x0010, 0, 0)

    print(json.dumps(hwnd), flush=True)
    threading.Thread(target=commands, daemon=True).start()
    native_message = w.MSG()
    while get_message(c.byref(native_message), None, 0, 0) > 0:
        translate(c.byref(native_message))
        dispatch(c.byref(native_message))


if __name__ == "__main__":
    main()
