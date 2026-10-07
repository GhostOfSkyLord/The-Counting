"""Local web server. Listens only on 127.0.0.1 and serves the UI plus a small JSON API."""
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import VERSION
from .osutil import open_folder
from .paths import web_dir
from .ratings import RatingError
from .service import UserError
from .tmdb import TMDBError

log = logging.getLogger("tally.server")

IMG_SIZES = {"w92", "w154", "w185", "w300", "w342", "w500", "w780", "w1280", "original"}
IMG_PATH = re.compile(r"^/[A-Za-z0-9_\-]+\.(jpg|jpeg|png|webp)$")
STATIC = {"/style.css", "/app.js", "/qr.js"}
ICON = re.compile(r"^/icons/[A-Za-z0-9_\-]+\.png$")
FONT = re.compile(r"^/fonts/[A-Za-z0-9_\-]+\.woff2$")


class TallyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # the default of 5 can refuse connections when a page loads many images at once

    remote = False   # True on the home-network server used by phones

    def __init__(self, service, data_dir, on_pick_folder=None, bind=("127.0.0.1", 0), handler=None):
        super().__init__(bind, handler or Handler)
        self.service = service
        self.token = secrets.token_urlsafe(24)
        self.img_dir = data_dir / "imgcache"
        self.last_ping = None
        self.bye_at = None
        self.data_dir = data_dir
        self._stopping = False
        self.port = self.server_address[1]
        self.on_pick_folder = on_pick_folder
        self.routes = build_routes()

    def handle_error(self, request, client_address):
        log.exception("unhandled server error from %s", client_address)

    @property
    def url(self):
        return "http://127.0.0.1:%d/" % self.port

    def _loop(self):
        """Keeps the server answering. If the loop ever crashes, log why and start it again."""
        while not self._stopping:
            try:
                self.serve_forever(poll_interval=0.25)
                return
            except Exception:
                log.exception("server loop crashed; restarting it")
                time.sleep(0.3)

    def shutdown(self):
        self._stopping = True
        super().shutdown()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="tally-http").start()


class Handler(BaseHTTPRequestHandler):
    server_version = "TheCounting"

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    # ---- plumbing ----
    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % self.server.port, "localhost:%d" % self.server.port)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        if n > 50_000_000:
            raise UserError("That file is too large.")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _pre(self, method, path, url):
        """Extra rules for subclasses. Return True if the request has been answered."""
        return False

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        try:
            if not self._host_ok():
                return self._send(403, {"error": "Forbidden"})
            url = urlparse(self.path)
            path = url.path
            if self._pre(method, path, url):
                return
            if method == "GET" and path == "/manifest.webmanifest":
                return self._send(200, (web_dir() / "manifest.webmanifest").read_bytes(), "application/manifest+json", {"Cache-Control": "max-age=3600"})
            if method == "GET" and ICON.match(path):
                f = web_dir() / path.lstrip("/")
                if f.is_file():
                    return self._send(200, f.read_bytes(), "image/png", {"Cache-Control": "max-age=86400"})
                return self._send(404, {"error": "Not found"})
            if method == "GET" and path == "/":
                html = (web_dir() / "index.html").read_text(encoding="utf-8")
                theme = self.server.service.db.get_setting("theme", "system")
                attr = ' data-theme="%s"' % theme if theme in ("light", "dark") else ""
                html = html.replace("{{TOKEN}}", self.server.token).replace("{{VERSION}}", VERSION).replace("{{THEME_ATTR}}", attr)
                return self._send(200, html, "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            if method == "GET" and path in STATIC:
                f = web_dir() / path.lstrip("/")
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype + "; charset=utf-8", {"Cache-Control": "no-store"})
            if method == "GET" and FONT.match(path):
                f = web_dir() / path.lstrip("/")
                if f.is_file():
                    return self._send(200, f.read_bytes(), "font/woff2", {"Cache-Control": "max-age=31536000"})
                return self._send(404, {"error": "Not found"})
            if method == "GET" and path.startswith("/img/"):
                return self._image(path)
            if path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                token = self.headers.get("X-Tally-Token") or (query.get("t") if path == "/api/bye" else None)
                if token != self.server.token:
                    return self._send(403, {"error": "Forbidden"})
                for m, rx, fn in self.server.routes:
                    mo = rx.fullmatch(path)
                    if m == method and mo:
                        body = self._body() if method in ("POST", "DELETE") else {}
                        return self._send(200, fn(self.server, mo, query, body))
            self._send(404, {"error": "Not found"})
        except (UserError, RatingError) as e:
            self._send(400, {"error": str(e)})
        except TMDBError as e:
            self._send(502, {"error": e.message, "kind": e.kind})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("request failed: %s %s", method, self.path)
            self._send(500, {"error": "Something went wrong inside The Counting. Details are in thecounting.log."})

    def _image(self, path):
        m = re.fullmatch(r"/img/([a-z0-9]+)(/[^/]+)", path)
        if not m or m.group(1) not in IMG_SIZES or not IMG_PATH.match(m.group(2)):
            return self._send(404, {"error": "Not found"})
        size, name = m.group(1), m.group(2)
        f = self.server.img_dir / size / name.lstrip("/")
        if not f.exists():
            try:
                data = self.server.service.tmdb.fetch("%s/%s%s" % (os.environ.get("TALLY_IMG_BASE", "https://image.tmdb.org/t/p"), size, name))
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
            except Exception:
                return self._send(404, {"error": "Image unavailable"})
        ctype = mimetypes.guess_type(f.name)[0] or "image/jpeg"
        return self._send(200, f.read_bytes(), ctype, {"Cache-Control": "max-age=604800"})


# ---------------------------------------------------------------------- routes
def build_routes():
    R = []

    def route(method, pattern):
        rx = re.compile(pattern)

        def deco(fn):
            R.append((method, rx, fn))
            return fn
        return deco

    @route("POST", "/api/ping")
    def ping(srv, m, q, b):
        srv.last_ping = time.time()
        return {"ok": True}

    @route("POST", "/api/bye")
    def bye(srv, m, q, b):
        srv.bye_at = time.time()
        return {"ok": True}

    @route("POST", "/api/open-data-folder")
    def open_data_folder(srv, m, q, b):
        open_folder(srv.data_dir)
        return {"folder": str(srv.data_dir)}

    @route("GET", "/api/state")
    def state(srv, m, q, b):
        s = srv.service.state()
        s["version"] = VERSION
        s["remote"] = srv.remote
        if srv.remote:           # a phone is told nothing about folders on the computer
            s.pop("backup_folder", None)
        return s

    @route("POST", "/api/settings/key")
    def save_key(srv, m, q, b):
        srv.service.save_key(b.get("key"))
        return {"ok": True}

    @route("POST", "/api/settings/network")
    def save_network(srv, m, q, b):
        srv.service.db.set_setting("secure_dns", "1" if b.get("secure_dns") else "0")
        return srv.service.state()

    @route("POST", "/api/settings/theme")
    def save_theme(srv, m, q, b):
        if b.get("theme") not in ("system", "light", "dark"):
            raise UserError("Unknown colour mode.")
        srv.service.db.set_setting("theme", b["theme"])
        return srv.service.state()

    @route("POST", "/api/settings/backup")
    def save_backup(srv, m, q, b):
        srv.service.save_backup_settings(b.get("folder"), b.get("keep"))
        return srv.service.state()

    @route("POST", "/api/pick-folder")
    def pick_folder(srv, m, q, b):
        return {"folder": srv.on_pick_folder() if srv.on_pick_folder else None}

    @route("POST", "/api/open-url")
    def open_url(srv, m, q, b):
        host = (urlparse(b.get("url", "")).hostname or "")
        if host not in ("www.themoviedb.org", "themoviedb.org"):
            raise UserError("That link is not allowed.")
        webbrowser.open(b["url"])
        return {"ok": True}

    @route("POST", "/api/diagnose")
    def diagnose(srv, m, q, b):
        return {"steps": srv.service.diagnose()}

    @route("POST", "/api/selftest")
    def selftest(srv, m, q, b):
        from . import selftest as st
        return st.run(network=bool(b.get("network", True)))

    @route("GET", "/api/guide")
    def guide_get(srv, m, q, b):
        return srv.service.guide.get()

    @route("POST", "/api/guide")
    def guide_save(srv, m, q, b):
        if srv.remote:        # a phone keeps its own guide state in the browser, and never changes the computer's
            return srv.service.guide.get()
        return srv.service.guide.save(b)

    # ---- phone access (only the computer itself can use these)
    def _lan(srv):
        lan = getattr(srv.service, "lan", None)
        if lan is None:
            raise UserError("Phone access is not available.")
        return lan

    @route("GET", "/api/lan")
    def lan_status(srv, m, q, b):
        return _lan(srv).status()

    @route("POST", "/api/lan/enable")
    def lan_enable(srv, m, q, b):
        return _lan(srv).set_enabled(bool(b.get("on")))

    @route("POST", "/api/lan/pair")
    def lan_pair(srv, m, q, b):
        try:
            return _lan(srv).new_pairing()
        except RuntimeError as e:
            raise UserError(str(e))

    @route("POST", "/api/lan/forget")
    def lan_forget(srv, m, q, b):
        _lan(srv).forget(b.get("id"))
        return _lan(srv).status()

    @route("GET", "/api/search")
    def search(srv, m, q, b):
        return {"results": srv.service.search(q.get("q", ""))}

    @route("POST", "/api/shows")
    def add(srv, m, q, b):
        return srv.service.add_show(b.get("tmdb_id"), b.get("status", "plan"), b.get("source", "manual"))

    @route("POST", "/api/shows/seen")
    def add_seen(srv, m, q, b):
        return srv.service.add_seen_show(b.get("tmdb_id"), b.get("through", "all"))

    @route("GET", "/api/library")
    def library(srv, m, q, b):
        return srv.service.library(q.get("status", "watching"))

    @route("GET", "/api/towatch")
    def towatch(srv, m, q, b):
        return srv.service.to_watch()

    @route("GET", r"/api/shows/(\d+)")
    def detail(srv, m, q, b):
        return srv.service.detail(m.group(1))

    @route("DELETE", r"/api/shows/(\d+)")
    def remove(srv, m, q, b):
        srv.service.remove_show(m.group(1))
        return {"ok": True}

    @route("POST", r"/api/shows/(\d+)/status")
    def status(srv, m, q, b):
        return srv.service.set_status(m.group(1), b.get("status"))

    @route("POST", r"/api/shows/(\d+)/overrides")
    def overrides(srv, m, q, b):
        return srv.service.set_overrides(m.group(1), b)

    @route("POST", r"/api/shows/(\d+)/refresh")
    def refresh(srv, m, q, b):
        return srv.service.refresh_show(m.group(1))

    @route("POST", "/api/mark")
    def mark(srv, m, q, b):
        return srv.service.mark(b.get("episode_id"), b.get("resolve"))

    @route("POST", "/api/seen-up-to")
    def seen_up_to(srv, m, q, b):
        return srv.service.seen_up_to(b.get("episode_id"))

    @route("POST", r"/api/shows/(\d+)/seen-through")
    def seen_through(srv, m, q, b):
        return srv.service.mark_through_season(m.group(1), b.get("season"))

    # ---- ratings, arena, favourites, discover
    @route("GET", "/api/ratings/profile")
    def rating_profile(srv, m, q, b):
        return srv.service.ratings.profile()

    @route("POST", "/api/ratings/profile")
    def save_rating_profile(srv, m, q, b):
        return srv.service.ratings.save_profile(b.get("mode"), b.get("weights"), b.get("preset"), b.get("same_genre"), b.get("top_only"))

    @route("POST", "/api/ratings")
    def rate(srv, m, q, b):
        return srv.service.ratings.rate(b.get("show_id"), b.get("mode"), b.get("scores"), b.get("overall"), b.get("gut"))

    @route("GET", "/api/ratings/rankings")
    def rankings(srv, m, q, b):
        return srv.service.ratings.rankings(q.get("scope", "overall"))

    @route("GET", "/api/ratings/arena")
    def arena(srv, m, q, b):
        return srv.service.ratings.arena(q.get("scope"))

    @route("POST", "/api/ratings/compare")
    def compare(srv, m, q, b):
        return srv.service.ratings.compare(b.get("scope"), b.get("a"), b.get("b"), b.get("result"), b.get("view"))

    @route("GET", r"/api/shows/(\d+)/seasons")
    def season_info(srv, m, q, b):
        return srv.service.ratings.season_info(m.group(1))

    @route("POST", r"/api/shows/(\d+)/seasons/rate")
    def rate_seasons(srv, m, q, b):
        return srv.service.ratings.rate_seasons(m.group(1), b.get("scores"))

    @route("POST", r"/api/shows/(\d+)/seasons/prefs")
    def season_prefs(srv, m, q, b):
        return srv.service.ratings.save_season_prefs(m.group(1), b.get("mode"), b.get("mix"))

    @route("POST", r"/api/shows/(\d+)/seasons/compare")
    def compare_seasons(srv, m, q, b):
        return srv.service.ratings.compare_seasons(m.group(1), b.get("a"), b.get("b"), b.get("result"))

    @route("GET", "/api/favourites")
    def favourites(srv, m, q, b):
        return {"favourites": srv.service.favourites()}

    @route("POST", "/api/favourites/toggle")
    def toggle_fav(srv, m, q, b):
        return srv.service.toggle_favourite(b.get("episode_id"))

    @route("GET", "/api/discover")
    def discover(srv, m, q, b):
        pending = srv.service.discover.fetch_links(cap=6)
        out = srv.service.discover.listing(q.get("mode", "you"))
        out["pending"] = pending
        return out

    @route("POST", "/api/discover/dismiss")
    def dismiss(srv, m, q, b):
        srv.service.discover.dismiss(b.get("show_id"))
        return {"ok": True}

    @route("GET", "/api/stats")
    def stats(srv, m, q, b):
        return srv.service.stats()

    @route("GET", "/api/log")
    def log_(srv, m, q, b):
        return {"events": srv.service.log(int(q.get("limit", 100)))}

    @route("GET", "/api/backups")
    def backups(srv, m, q, b):
        return {"folder": str(srv.service.backups.folder()), "backups": srv.service.backups.list()}

    @route("POST", "/api/backups/now")
    def backup_now(srv, m, q, b):
        srv.service.backups.snapshot("manual")
        return {"folder": str(srv.service.backups.folder()), "backups": srv.service.backups.list()}

    @route("POST", "/api/backups/restore")
    def restore(srv, m, q, b):
        try:
            srv.service.backups.restore(b.get("name", ""))
        except ValueError as e:
            raise UserError(str(e))
        return {"ok": True}

    @route("POST", "/api/backups/open-folder")
    def open_folder(srv, m, q, b):
        folder = str(srv.service.backups.folder())
        open_folder(folder)
        return {"folder": folder}

    @route("POST", "/api/export")
    def export(srv, m, q, b):
        path = srv.service.backups.export_json()
        open_folder(path.parent)
        return {"path": str(path)}

    @route("POST", "/api/import")
    def import_(srv, m, q, b):
        try:
            return srv.service.backups.import_json(b)
        except (ValueError, KeyError, TypeError):
            raise UserError("The Counting could not read that file. Is it an export from The Counting?")

    return R
