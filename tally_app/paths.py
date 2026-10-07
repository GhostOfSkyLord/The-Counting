"""Where The Counting keeps its files."""
import os
import sys
from pathlib import Path

APP_NAME = "The Counting"
LEGACY_NAME = "Tally"  # the folder used before the app was renamed


def default_base(platform, environ, home, name=None):
    """Where the data lives on each system. Windows: %APPDATA%\\The Counting.
    Mac: ~/Library/Application Support/The Counting. Anything else: ~/.local/share/the-counting."""
    home, name = Path(home), name or APP_NAME
    if platform.startswith("win"):
        return Path(environ.get("APPDATA") or home / "AppData" / "Roaming") / name
    if platform == "darwin":
        return home / "Library" / "Application Support" / name
    return home / ".local" / "share" / name.lower().replace(" ", "-")


def migrate_legacy(new, old):
    """Moves the folder used before the rename, once. If anything goes wrong the old folder keeps being used,
    so nothing is ever lost. Returns the folder to use."""
    if new.exists() or not old.exists():
        return new
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        return new
    except OSError:
        return old


def data_dir() -> Path:
    """User data folder. THECOUNTING_HOME (or the older TALLY_HOME) overrides it; the tests use that."""
    env = os.environ.get("THECOUNTING_HOME") or os.environ.get("TALLY_HOME")
    if env:
        p = Path(env)
    else:
        new = default_base(sys.platform, os.environ, Path.home())
        p = migrate_legacy(new, default_base(sys.platform, os.environ, Path.home(), LEGACY_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def web_dir() -> Path:
    """Folder holding the UI files, both from source and from a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "tally_app" / "web"
    return Path(__file__).resolve().parent / "web"
