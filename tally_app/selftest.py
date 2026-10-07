"""A self-check: does this copy of The Counting have everything it needs? Used by the cloud build to test the apps it
makes, by "Run a self-check" in Settings, and by `The Counting --selftest`. It never touches your own data."""
import json
import os
import platform
import socket
import sqlite3
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import VERSION, netfix
from .paths import data_dir, web_dir

NEEDED = ["index.html", "app.js", "style.css", "qr.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png",
          "fonts"]


def _check(out, name, fn, required=True):
    try:
        detail = fn()
        out.append({"name": name, "ok": True, "detail": detail or "", "required": required})
    except Exception as e:
        out.append({"name": name, "ok": False, "detail": "%s: %s" % (e.__class__.__name__, e), "required": required})


def run(network=True):
    info = {"app": VERSION, "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable}
    if sys.platform == "darwin":
        info["macos"] = platform.mac_ver()[0]
    checks = []

    def data_folder():
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix="selftest-", delete=True):
            pass
        return "%s is writable" % d

    def web_files():
        w = web_dir()
        missing = [n for n in NEEDED if not (w / n).exists()]
        if missing:
            raise RuntimeError("missing from the app: " + ", ".join(missing))
        fonts = len(list((w / "fonts").glob("*.woff2")))
        return "all present (%d font files) in %s" % (fonts, w)

    def database():
        from .db import MIGRATIONS, Database
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t) / "check.db")
            version = db.conn.execute("PRAGMA user_version").fetchone()[0]
            mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
            db.close()
        if version != len(MIGRATIONS):
            raise RuntimeError("database version %s, expected %s" % (version, len(MIGRATIONS)))
        return "SQLite %s, journal mode %s, database version %d" % (sqlite3.sqlite_version, mode, version)

    def local_server():
        from .backup import BackupManager
        from .db import Database
        from .server import TallyServer
        from .service import Service
        from .tmdb import TMDB
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t) / "check.db")
            service = Service(db, TMDB(lambda: ""), BackupManager(db, t))
            server = TallyServer(service, Path(t))
            server.start()
            try:
                html = urllib.request.urlopen(server.url, timeout=10).read().decode()
                urllib.request.urlopen(server.url + "app.js", timeout=10).read()
                urllib.request.urlopen(server.url + "qr.js", timeout=10).read()
                urllib.request.urlopen(server.url + "manifest.webmanifest", timeout=10).read()
            finally:
                server.shutdown()
                db.close()
        if "The Counting" not in html or "tally-token" not in html:
            raise RuntimeError("the page did not look right")
        return "served the page and its files on a temporary port"

    def certificates():
        ctx = netfix.context()
        stats = ctx.cert_store_stats()
        n = stats.get("x509_ca", 0)
        if n == 0:
            raise RuntimeError("no trusted certificates were found, so secure connections will fail")
        return "%s; %d trusted certificate authorities" % (ssl.OPENSSL_VERSION, n)

    def phone_access():
        from . import lan  # noqa: F401  (also checks the QR code library file is shipped, above)
        ips = lan.lan_ips()
        return "home-network address%s: %s" % ("es" if len(ips) != 1 else "", ", ".join(ips) or "none found (no network?)")

    def window():
        import webview
        v = getattr(webview, "__version__", None) or "installed"
        extra = ""
        if sys.platform == "darwin":
            import objc  # noqa: F401
            extra = ", pyobjc present"
        return "pywebview %s%s" % (v, extra)

    def tmdb_reachable():
        host = "api.themoviedb.org"
        addr = socket.getaddrinfo(host, 443)[0][4][0]
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=netfix.context()))
        try:
            with opener.open("https://%s/3/configuration" % host, timeout=15) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code        # an answer of any kind, even "no key", proves the secure connection works
        if code not in (200, 401):
            raise RuntimeError("unexpected answer %s" % code)
        return "%s (%s) answered over a verified secure connection" % (host, addr)

    _check(checks, "Data folder", data_folder)
    _check(checks, "App files", web_files)
    _check(checks, "Database", database)
    _check(checks, "Local server", local_server)
    _check(checks, "Trusted certificates", certificates)
    _check(checks, "Phone access", phone_access, required=False)
    _check(checks, "Window component", window, required=info["frozen"])    # a built app must have it; from source it is optional
    if network:
        _check(checks, "Reaching TMDB", tmdb_reachable, required=False)
    ok = all(c["ok"] for c in checks if c["required"])
    lines = ["The Counting self-check: %s" % ("ALL REQUIRED CHECKS PASSED" if ok else "PROBLEMS FOUND"), ""]
    lines += ["%-10s %s" % (k, v) for k, v in info.items()] + [""]
    lines += ["%-5s %-22s %s" % ("PASS" if c["ok"] else ("FAIL" if c["required"] else "WARN"), c["name"], c["detail"]) for c in checks]
    return {"ok": ok, "info": info, "checks": checks, "text": "\n".join(lines)}


def cli(argv):
    """`The Counting --selftest [file]`: writes the result as JSON to the file (a windowed app has no console)."""
    i = argv.index("--selftest")
    path = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") else None
    result = run(network="--offline" not in argv)
    if path:
        Path(path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    try:
        print(result["text"], flush=True)
    except Exception:
        pass
    return 0 if result["ok"] else 1
