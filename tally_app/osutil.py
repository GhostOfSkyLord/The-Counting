"""The few things that differ between Windows, macOS and Linux."""
import os
import subprocess
import sys


def open_folder(path, platform=None):
    """Shows a folder in Explorer, Finder, or the default file manager."""
    platform, path = platform or sys.platform, str(path)
    if platform.startswith("win"):
        os.startfile(path)  # noqa: opens Explorer
    elif platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def applescript_dialog(text, title):
    esc = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')
    return 'display dialog "%s" with title "%s" buttons {"OK"} default button "OK" with icon stop' % (esc(text), esc(title))


def message_box(text, title="The Counting", platform=None):
    """There is no console window, so problems have to be shown in a dialog."""
    platform = platform or sys.platform
    try:
        if platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        if platform == "darwin":
            subprocess.run(["osascript", "-e", applescript_dialog(text, title)], timeout=120)
            return
    except Exception:
        pass
    print(title + ": " + text, file=sys.stderr)


def app_mode_browser(platform=None):
    """Path to a browser that can show The Counting as a chromeless app window, or None (Windows only)."""
    if not (platform or sys.platform).startswith("win"):
        return None
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(base or "", rel)
            if base and os.path.exists(p):
                return p
    return None
