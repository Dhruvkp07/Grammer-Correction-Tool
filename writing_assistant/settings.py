import json
import os
import tempfile
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

from . import windows
from .core import DEFAULT_MODEL, parse_shortcut

DIRECTORY = Path(os.environ["LOCALAPPDATA"]) / "Writing Assistant"
PREFERENCES = DIRECTORY / "settings.json"
CREDENTIAL = DIRECTORY / "gemini-key.dpapi"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "WritingAssistant"


@dataclass
class Settings:
    shortcut: str = "Ctrl+Alt+G"
    spelling: bool = True
    overlay: bool = True
    model: str = DEFAULT_MODEL
    automatic: bool = False

    @classmethod
    def load(cls):
        try:
            values = json.loads(PREFERENCES.read_text(encoding="utf-8"))
            return cls(
                parse_shortcut(values["shortcut"]).label,
                values["spelling"] is True,
                values["overlay"] is True,
                str(values["model"]),
                values.get("automatic") is True,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return cls()

    def save(self):
        write_file(PREFERENCES, json.dumps(asdict(self), indent=2).encode("utf-8"))


def write_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(data)
            file.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def save_key(key):
    write_file(CREDENTIAL, windows.dpapi(key.encode("utf-8"), True))


def load_key():
    try:
        encrypted = CREDENTIAL.read_bytes()
    except FileNotFoundError:
        return ""
    try:
        return windows.dpapi(encrypted, False).decode("utf-8")
    except (OSError, ValueError) as exc:
        raise OSError("The saved API key is unreadable. Replace or remove it in Settings.") from exc


def remove_key():
    CREDENTIAL.unlink(missing_ok=True)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, windows.startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
