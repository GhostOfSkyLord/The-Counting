"""Starts The Counting: local server, background refresher, and the app window."""
import faulthandler
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from . import VERSION
from .backup import BackupManager
from .db import Database
from .lan import LanAccess
from .osutil import app_mode_browser, message_box
from .paths import data_dir
from .server import TallyServer
from .service import Service
from .sync import Refresher
from .tmdb import TMDB

log = logging.getLogger("tally")
LOCK_PORT = 47833


def setup_logging(folder):
    handler = RotatingFileHandler(folder / "thecounting.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def crash(exc_type, exc, tb):
        logging.getLogger("tally").critical("uncaught error", exc_info=(exc_type, exc, tb))
    sys.excepthook = crash
    threading.excepthook = lambda a: logging.getLogger("tally").critical(
        "uncaught error in thread %s", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    try:  # also records hard crashes inside native code (window component, database)
        faulthandler.enable(open(folder / "crash.log", "a"))
    except Exception:
        pass


def acquire_lock():
    if os.environ.get("TALLY_NO_LOCK"):
        return object()
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


EARLY_EXIT_S = 10      # a browser that exits this fast has handed the window to another process
SILENCE_LIMIT_S = 300  # hidden or minimised pages are throttled, so wait a long time before giving up
GOODBYE_GRACE_S = 4


def fallback_should_exit(now, started, proc_rc, early_exit, last_ping, bye_at):
    """Decides when to stop The Counting in browser mode. Returns (should_exit, early_exit)."""
    if proc_rc is not None:
        if now - started < EARLY_EXIT_S:
            early_exit = True
        elif not early_exit:
            return True, early_exit  # the app window's own process ended: the window was closed
    if bye_at and now - bye_at > GOODBYE_GRACE_S and (not last_ping or last_ping < bye_at):
        return True, early_exit  # the page said goodbye and nothing came back (a reload would have pinged)
    if last_ping and now - last_ping > SILENCE_LIMIT_S:
        return True, early_exit
    if not last_ping and now - started > 90:
        return True, early_exit  # the page never connected
    return False, early_exit


def run_window(server, folder):
    """Preferred: a native window through pywebview. Fallback: Edge/Chrome in app mode."""
    if os.environ.get("TALLY_HEADLESS"):
        while True:
            time.sleep(1)
    try:
        import webview

        class Bridge:
            def pick_folder(self):
                res = window.create_file_dialog(webview.FOLDER_DIALOG)
                return res[0] if res else None

        server.on_pick_folder = lambda: Bridge().pick_folder()
        window = webview.create_window("The Counting", server.url, width=1180, height=820, min_size=(420, 600), js_api=Bridge())
        log.info("opening the app window with pywebview")
        try:
            webview.start(storage_path=str(folder / "webview"))
        except TypeError:
            webview.start()
        log.info("app window closed")
        return
    except Exception:
        log.exception("pywebview unavailable, trying browser app mode")
    exe = app_mode_browser()
    proc = None
    if exe:
        log.info("opening the app window in browser app mode: %s", exe)
        proc = subprocess.Popen([exe, "--app=" + server.url, "--user-data-dir=" + str(folder / "browser-profile"),
                                 "--window-size=1180,820", "--no-first-run"])
    else:
        import webbrowser
        log.info("opening The Counting in the default browser")
        if not webbrowser.open(server.url):
            message_box("The Counting could not open a window. Install the pywebview package (see README) or open %s in a browser." % server.url)
            return
    started, early = time.time(), False
    while True:
        time.sleep(1)
        done, early = fallback_should_exit(time.time(), started, proc.poll() if proc else None, early, server.last_ping, server.bye_at)
        if done:
            log.info("browser-mode window finished (ping=%s bye=%s)", server.last_ping, server.bye_at)
            break


def main():
    # A windowed app has no console: stdout/stderr are None, which breaks anything that prints.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if "--selftest" in sys.argv:
        from .selftest import cli
        return cli(sys.argv)
    folder = data_dir()
    setup_logging(folder)
    log.info("The Counting %s starting", VERSION)
    lock = acquire_lock()
    if lock is None:
        message_box("The Counting is already running.")
        return 0
    try:
        db = Database(folder / "tally.db")
        backups = BackupManager(db, folder)
        tmdb = TMDB(lambda: db.get_setting("tmdb_key"), secure_dns=lambda: db.get_setting("secure_dns", "1") == "1")
        refresher = Refresher(db, tmdb, lambda: bool((db.get_setting("tmdb_key") or "").strip()))
        service = Service(db, tmdb, backups, refresher)
        backups.on_launch()
        server = TallyServer(service, folder)
        server.start()
        lan = LanAccess(service, folder)
        service.lan = lan
        if lan.enabled():
            lan.start()
        refresher.start()
        log.info("serving on %s", server.url)
        if os.environ.get("TALLY_PRINT_URL"):
            print(server.url, flush=True)
        try:
            run_window(server, folder)
        finally:
            refresher.stop()
            lan.stop()
            backups.on_exit()
            server.shutdown()
            db.close()
        log.info("The Counting closed cleanly")
        return 0
    except Exception as e:
        log.exception("fatal error")
        message_box("The Counting hit a problem and has to close.\n\n%s\n\nDetails: %s" % (e, folder / "thecounting.log"))
        return 1
    finally:
        try:
            lock.close()
        except Exception:
            pass
