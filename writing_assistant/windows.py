"""Small Win32 wrappers used by the interface and automation worker."""

import ctypes as c
import os
import secrets
import subprocess
import sys
from ctypes import wintypes as w

user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
crypto = c.WinDLL("crypt32", use_last_error=True)
controls = c.WinDLL("comctl32", use_last_error=True)


def bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


class LastInput(c.Structure):
    _fields_ = [("size", w.UINT), ("time", w.DWORD)]


class KeyboardInput(c.Structure):
    _fields_ = [
        ("key", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
        ("time", w.DWORD), ("extra", c.c_size_t),
    ]


class MouseInput(c.Structure):
    _fields_ = [
        ("x", w.LONG), ("y", w.LONG), ("data", w.DWORD), ("flags", w.DWORD),
        ("time", w.DWORD), ("extra", c.c_size_t),
    ]


class InputValue(c.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(c.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("kind", w.DWORD), ("value", InputValue)]


class MonitorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("screen", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


class Blob(c.Structure):
    _fields_ = [("size", w.DWORD), ("data", c.POINTER(c.c_ubyte))]


foreground = bind(user, "GetForegroundWindow", w.HWND)
restore_foreground = bind(user, "SetForegroundWindow", w.BOOL, w.HWND)
get_window_process = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
get_ancestor = bind(user, "GetAncestor", w.HWND, w.HWND, w.UINT)
get_style = bind(user, "GetWindowLongW", w.LONG, w.HWND, c.c_int)
set_style = bind(user, "SetWindowLongW", w.LONG, w.HWND, c.c_int, w.LONG)
set_pos = bind(user, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int,
               c.c_int, c.c_int, w.UINT)
register_hotkey = bind(user, "RegisterHotKey", w.BOOL, w.HWND, c.c_int, w.UINT, w.UINT)
unregister_hotkey = bind(user, "UnregisterHotKey", w.BOOL, w.HWND, c.c_int)
get_class = bind(user, "GetClassNameW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
subclass_proc = c.WINFUNCTYPE(w.LPARAM, w.HWND, w.UINT, w.WPARAM, w.LPARAM, c.c_size_t, c.c_size_t)
set_subclass = bind(controls, "SetWindowSubclass", w.BOOL, w.HWND, subclass_proc, c.c_size_t, c.c_size_t)
remove_subclass = bind(controls, "RemoveWindowSubclass", w.BOOL, w.HWND, subclass_proc, c.c_size_t)
next_subclass = bind(controls, "DefSubclassProc", w.LPARAM, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
monitor_from_point = bind(user, "MonitorFromPoint", w.HMONITOR, w.POINT, w.DWORD)
get_monitor_info = bind(user, "GetMonitorInfoW", w.BOOL, w.HMONITOR, c.POINTER(MonitorInfo))
get_input = bind(user, "GetLastInputInfo", w.BOOL, c.POINTER(LastInput))
ticks = bind(kernel, "GetTickCount", w.DWORD)
send_input = bind(user, "SendInput", w.UINT, w.UINT, c.POINTER(Input), c.c_int)
get_key_state = bind(user, "GetAsyncKeyState", c.c_short, c.c_int)
open_clipboard = bind(user, "OpenClipboard", w.BOOL, w.HWND)
close_clipboard = bind(user, "CloseClipboard", w.BOOL)
empty_clipboard = bind(user, "EmptyClipboard", w.BOOL)
set_clipboard = bind(user, "SetClipboardData", w.HANDLE, w.UINT, w.HANDLE)
clipboard_format = bind(user, "RegisterClipboardFormatW", w.UINT, w.LPCWSTR)
get_clipboard = bind(user, "GetClipboardData", w.HANDLE, w.UINT)
global_alloc = bind(kernel, "GlobalAlloc", w.HGLOBAL, w.UINT, c.c_size_t)
global_lock = bind(kernel, "GlobalLock", c.c_void_p, w.HGLOBAL)
global_unlock = bind(kernel, "GlobalUnlock", w.BOOL, w.HGLOBAL)
global_free = bind(kernel, "GlobalFree", w.HGLOBAL, w.HGLOBAL)
global_size = bind(kernel, "GlobalSize", c.c_size_t, w.HGLOBAL)
local_free = bind(kernel, "LocalFree", w.HLOCAL, w.HLOCAL)
create_mutex = bind(kernel, "CreateMutexW", w.HANDLE, c.c_void_p, w.BOOL, w.LPCWSTR)
close_handle = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
protect = bind(crypto, "CryptProtectData", w.BOOL, c.POINTER(Blob), w.LPCWSTR,
               c.c_void_p, c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob))
unprotect = bind(crypto, "CryptUnprotectData", w.BOOL, c.POINTER(Blob), c.c_void_p,
                 c.c_void_p, c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob))


def own_window(window):
    return get_ancestor(window.winfo_id(), 2) or window.winfo_id()


def process_id(hwnd):
    pid = w.DWORD()
    if hwnd:
        get_window_process(hwnd, c.byref(pid))
    return pid.value


def last_input():
    info = LastInput(c.sizeof(LastInput), 0)
    if not get_input(c.byref(info)):
        return 0, 0
    return info.time, (ticks() - info.time) & 0xFFFFFFFF


def place_popup(window, anchor):
    x, y, right, bottom = map(round, anchor)
    info = MonitorInfo(c.sizeof(MonitorInfo))
    monitor = monitor_from_point(w.POINT(x, bottom), 2)
    if not get_monitor_info(monitor, c.byref(info)):
        return
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    hwnd = own_window(window)
    work = info.work
    above = y - height - 6
    top = above if above >= work.top else min(bottom + 6, work.bottom - height)
    left = max(work.left, min(right - width, work.right - width))
    set_style(hwnd, -20, get_style(hwnd, -20) | 0x08000000 | 0x80)
    # SWP_NOACTIVATE keeps the editor's caret and selection in place.
    set_pos(hwnd, -1, left, top, width, height, 0x10)
    if window.state() == "withdrawn":
        window.deiconify()
    set_pos(hwnd, -1, left, top, width, height, 0x10 | 0x40)


class NoActivate:
    """Allow mouse clicks on the popup without transferring the editor's input focus."""

    def __init__(self, overlay):
        self.hwnd = own_window(overlay)
        self.callback = subclass_proc(self._message)
        self.installed = set_subclass(self.hwnd, self.callback, 3, 0)

    def _message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == 0x0021:  # WM_MOUSEACTIVATE
            return 3  # MA_NOACTIVATE still delivers the click.
        return next_subclass(hwnd, message, wparam, lparam)

    def close(self):
        if self.installed:
            remove_subclass(self.hwnd, self.callback, 3)


def native_password(hwnd):
    if not hwnd:
        return False
    name = c.create_unicode_buffer(64)
    get_class(hwnd, name, len(name))
    kind = name.value.lower()
    return (kind == "edit" or kind.startswith("richedit")) and bool(get_style(hwnd, -16) & 0x20)


class Hotkey:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.pressed = False
        self.shortcut = None
        self.callback = subclass_proc(self._message)
        if not set_subclass(hwnd, self.callback, 1, 0):
            raise OSError("Windows could not initialize the writing shortcut.")

    def _message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == 0x0312 and wparam == 1:
            self.pressed = True
            return 0
        return next_subclass(hwnd, message, wparam, lparam)

    def set(self, shortcut):
        previous = self.shortcut
        if previous == shortcut:
            return
        unregister_hotkey(self.hwnd, 1)
        if self._register(shortcut):
            self.shortcut = shortcut
            return
        self.shortcut = previous if previous and self._register(previous) else None
        raise ValueError(f"{shortcut.label} is unavailable. Try another shortcut.")

    def _register(self, shortcut):
        return register_hotkey(self.hwnd, 1, shortcut.modifiers | 0x4000, shortcut.key)

    def take(self):
        pressed, self.pressed = self.pressed, False
        return pressed

    def close(self):
        unregister_hotkey(self.hwnd, 1)
        remove_subclass(self.hwnd, self.callback, 1)


def active_modifiers():
    return any(get_key_state(key) < 0 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))


def _clipboard_data(format_id, data):
    handle = global_alloc(0x0002, len(data))
    if not handle:
        raise c.WinError(c.get_last_error())
    try:
        pointer = global_lock(handle)
        if not pointer:
            raise c.WinError(c.get_last_error())
        try:
            c.memmove(pointer, data, len(data))
        finally:
            global_unlock(handle)
        if not set_clipboard(format_id, handle):
            raise c.WinError(c.get_last_error())
        handle = None  # Windows owns the allocation after SetClipboardData succeeds.
    finally:
        if handle:
            global_free(handle)


CLIPBOARD_MARKER = "WritingAssistant.ReplacementMarker"


def copy_text(owner, text):
    if "\0" in text:
        raise ValueError("The text contains an unsupported character.")
    data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
    if not open_clipboard(owner):
        raise c.WinError(c.get_last_error())
    try:
        formats = [clipboard_format(name) for name in (
            "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"
        )]
        if not all(formats) or not empty_clipboard():
            raise c.WinError(c.get_last_error())
        marker_format = clipboard_format(CLIPBOARD_MARKER)
        if not marker_format:
            raise c.WinError(c.get_last_error())
        marker = secrets.token_bytes(16)
        for format_id in formats:
            _clipboard_data(format_id, bytes(4))
        _clipboard_data(marker_format, marker)
        _clipboard_data(13, data)  # CF_UNICODETEXT
        return marker
    finally:
        close_clipboard()


def clipboard_still_matches(owner, marker):
    # Windows may generate additional text formats on close, changing the sequence number.
    # Read only our private write marker, never the contents of an unrelated clipboard entry.
    format_id = clipboard_format(CLIPBOARD_MARKER)
    if not format_id or not open_clipboard(owner):
        return False
    try:
        handle = get_clipboard(format_id)
        if not handle or global_size(handle) < len(marker):
            return False
        pointer = global_lock(handle)
        if not pointer:
            return False
        try:
            return c.string_at(pointer, len(marker)) == marker
        finally:
            global_unlock(handle)
    finally:
        close_clipboard()


def _send_keys(events):
    keys = (Input * len(events))()
    for index, (key, flags) in enumerate(events):
        keys[index].kind = 1
        keys[index].keyboard = KeyboardInput(key, 0, flags, 0, 0)
    if send_input(len(keys), keys, c.sizeof(Input)) != len(keys):
        releases = list(dict.fromkeys(key for key, _ in reversed(events)))
        release = (Input * len(releases))()
        for index, key in enumerate(releases):
            release[index].kind = 1
            release[index].keyboard = KeyboardInput(key, 0, 2, 0, 0)
        send_input(len(release), release, c.sizeof(Input))
        raise OSError("Windows blocked the editor shortcut.")


def select_word_left(length, trailing_space):
    events = [(0x25, 0), (0x25, 2)] if trailing_space else []
    events += [(0x10, 0)] + [(0x25, 0), (0x25, 2)] * length + [(0x10, 2)]
    _send_keys(events)


def select_paragraph(characters_to_end, length):
    # The caller checks the resulting range before inserting any text.
    events = [(0x27, 0), (0x27, 2)] * characters_to_end
    events += [(0x10, 0)] + [(0x25, 0), (0x25, 2)] * length + [(0x10, 2)]
    _send_keys(events)


def insert_text(text):
    """Insert printable Unicode into a verified selection as one Windows input batch."""
    encoded = text.encode("utf-16-le")
    events = (Input * len(encoded))()
    for index in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[index:index + 2], "little")
        for offset, flags in ((0, 4), (1, 6)):  # KEYEVENTF_UNICODE, then KEYUP
            events[index + offset].kind = 1
            events[index + offset].keyboard = KeyboardInput(0, unit, flags, 0, 0)
    if send_input(len(events), events, c.sizeof(Input)) != len(events):
        raise OSError("Windows interrupted insertion. Check the draft before trying again.")


def select_all():
    _send_keys([(0x11, 0), (0x41, 0), (0x41, 2), (0x11, 2)])


def paste():
    _send_keys([(0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)])


def dpapi(data, encrypt):
    storage = (c.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), storage)
    result = Blob()
    try:
        if encrypt:
            ok = protect(c.byref(source), "Writing Assistant Gemini key", None, None, None, 1, c.byref(result))
        else:
            ok = unprotect(c.byref(source), None, None, None, None, 1, c.byref(result))
        if not ok:
            raise c.WinError(c.get_last_error())
        return c.string_at(result.data, result.size)
    finally:
        c.memset(storage, 0, len(data))
        if result.data:
            c.memset(result.data, 0, result.size)
            local_free(c.cast(result.data, w.HLOCAL))


def startup_command():
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(os.path.abspath(sys.argv[0]))
    return subprocess.list2cmdline([*args, "--background"])


class NotificationData(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("hwnd", w.HWND), ("id", w.UINT), ("flags", w.UINT),
        ("callback", w.UINT), ("icon", w.HICON), ("tip", w.WCHAR * 128),
        ("state", w.DWORD), ("state_mask", w.DWORD), ("info", w.WCHAR * 256),
        ("version", w.UINT), ("info_title", w.WCHAR * 64), ("info_flags", w.DWORD),
        ("guid", c.c_byte * 16), ("balloon_icon", w.HICON),
    ]


shell = c.WinDLL("shell32", use_last_error=True)
notify = bind(shell, "Shell_NotifyIconW", w.BOOL, w.DWORD, c.POINTER(NotificationData))
load_icon = bind(user, "LoadIconW", w.HICON, w.HINSTANCE, c.c_void_p)
register_message = bind(user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)


class Tray:
    MESSAGE = 0x8001

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.restart_message = register_message("TaskbarCreated")
        self.clicked = False
        self.data = NotificationData()
        self.data.size = c.sizeof(NotificationData)
        self.data.hwnd = hwnd
        self.data.id = 1
        self.data.flags = 1 | 2 | 4  # Callback, icon, tooltip.
        self.data.callback = self.MESSAGE
        self.data.icon = load_icon(None, 32512)
        self.data.tip = "Writing Assistant · Click to open"
        self.callback = subclass_proc(self._message)
        self.installed = bool(set_subclass(hwnd, self.callback, 2, 0))
        self.visible = self.installed and bool(notify(0, c.byref(self.data)))

    def _message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == self.MESSAGE and lparam in (0x0202, 0x0205):
            self.clicked = True
            return 0
        if self.restart_message and message == self.restart_message:
            self.visible = bool(notify(0, c.byref(self.data)))
        return next_subclass(hwnd, message, wparam, lparam)

    def take(self):
        clicked, self.clicked = self.clicked, False
        return clicked

    def close(self):
        if self.installed:
            notify(2, c.byref(self.data))
            remove_subclass(self.hwnd, self.callback, 2)
