"""Use The Counting from a phone on the home network.

Off by default. When it is on, a second server listens on the computer's home-network address, and each phone has
to be paired once, either by scanning a QR code or by typing a six-digit code shown on the computer. A paired phone
can track, rate, search and browse, but cannot touch anything on the computer itself (folders, backups, exports,
the TMDB key). Only devices on the local network are accepted. The connection is plain HTTP, so use it on a network
you trust, such as your home Wi-Fi, and not on public Wi-Fi.
"""
import hashlib
import hmac
import http.cookies
import ipaddress
import logging
import os
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs

from .server import ICON, Handler, TallyServer

log = logging.getLogger("tally.lan")

COOKIE = "tcdev"
PAIR_TTL = 600           # a pairing code works for ten minutes, once
MAX_BAD_PINS = 5         # five wrong codes cancel every open pairing
CGNAT = ipaddress.ip_network("100.64.0.0/10")   # also used by some VPNs, for example Tailscale
DESKTOP_ONLY = ("/api/lan", "/api/open-folder", "/api/open-data-folder", "/api/open-url", "/api/pick-folder",
                "/api/export", "/api/import", "/api/backups", "/api/settings/key", "/api/settings/backup",
                "/api/settings/network", "/api/settings/theme", "/api/diagnose", "/api/selftest")


def is_local_client(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or a in CGNAT


def lan_ips():
    """This computer's home-network addresses, the main one first."""
    env = os.environ.get("TALLY_LAN_IPS")
    if env:
        return env.split(",")
    found = []
    try:  # the address the computer would use to reach the rest of the network (nothing is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if ip not in out and not ip.startswith("127.") and is_local_client(ip):
            out.append(ip)
    return out


def device_name(agent):
    a = (agent or "").lower()
    for key, name in (("iphone", "iPhone"), ("ipad", "iPad"), ("android", "Android phone"), ("windows", "Windows PC"),
                      ("macintosh", "Mac"), ("linux", "Linux PC")):
        if key in a:
            return name
    return "Browser"


class LanAccess:
    def __init__(self, service, data_dir):
        self.service, self.data_dir = service, data_dir
        self.db = service.db
        self.server = None
        self.error = None
        self.pairings = {}        # code -> {"pin": "123456", "expires": time}
        self.bad_pins = 0
        self.lock = threading.Lock()

    # ---- switching on and off ----
    def enabled(self):
        return self.db.get_setting("lan_enabled", "0") == "1"

    def set_enabled(self, on):
        self.db.set_setting("lan_enabled", "1" if on else "0")
        if on:
            self.start()
        else:
            self.stop()
            with self.lock:
                self.pairings.clear()
        return self.status()

    def start(self):
        if self.server:
            return
        host = os.environ.get("TALLY_LAN_BIND", "0.0.0.0")
        base = int(os.environ.get("TALLY_LAN_PORT", "47834"))
        ports = [0] if base == 0 else range(base, base + 16)
        for port in ports:
            try:
                srv = LanServer(self.service, self.data_dir, self, (host, port))
                break
            except OSError:
                continue
        else:
            self.error = "The Counting could not open a port for phones. Another program may be using them."
            log.warning(self.error)
            return
        srv.start()
        self.server, self.error = srv, None
        log.info("phone access is on, port %d", srv.port)

    def stop(self):
        srv, self.server = self.server, None
        if srv:
            srv.shutdown()
            srv.server_close()
            log.info("phone access is off")

    def status(self):
        port = self.server.port if self.server else None
        return {"enabled": self.enabled(), "running": bool(self.server), "port": port, "error": self.error,
                "urls": ["http://%s:%d/" % (ip, port) for ip in lan_ips()] if port else [],
                "devices": self.devices()}

    # ---- paired devices ----
    def devices(self):
        return [{"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_seen": r["last_seen"]}
                for r in self.db.q("SELECT * FROM paired_devices ORDER BY last_seen DESC")]

    def forget(self, device_id):
        self.db.x("DELETE FROM paired_devices WHERE id=?", (int(device_id),))

    def _create_device(self, agent):
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.x("INSERT INTO paired_devices(name,token_hash,created_at,last_seen) VALUES(?,?,?,?)",
                  (device_name(agent), hashlib.sha256(token.encode()).hexdigest(), now, now))
        return token

    def check_cookie(self, token):
        if not token:
            return None
        row = self.db.q1("SELECT id, last_seen FROM paired_devices WHERE token_hash=?",
                         (hashlib.sha256(token.encode()).hexdigest(),))
        if not row:
            return None
        if time.time() - row["last_seen"] > 60:
            self.db.x("UPDATE paired_devices SET last_seen=? WHERE id=?", (time.time(), row["id"]))
        return row["id"]

    # ---- pairing ----
    def new_pairing(self):
        st = self.status()
        if not st["running"]:
            raise RuntimeError("Phone access is off.")
        with self.lock:
            now = time.time()
            self.pairings = {c: p for c, p in self.pairings.items() if p["expires"] > now}
            self.bad_pins = 0
            code, pin = secrets.token_urlsafe(18), "%06d" % secrets.randbelow(10 ** 6)
            self.pairings[code] = {"pin": pin, "expires": now + PAIR_TTL}
        return {"links": [u + "pair?code=" + code for u in st["urls"]], "addresses": st["urls"], "pin": pin,
                "expires_in": PAIR_TTL}

    def use_code(self, code, agent):
        with self.lock:
            p = self.pairings.pop(code, None)
        if p and p["expires"] > time.time():
            return self._create_device(agent)
        return None

    def use_pin(self, pin, agent):
        pin = (pin or "").strip()
        with self.lock:
            now = time.time()
            for code, p in list(self.pairings.items()):
                if p["expires"] > now and hmac.compare_digest(p["pin"], pin):
                    del self.pairings[code]
                    return self._create_device(agent)
            self.bad_pins += 1
            if self.bad_pins >= MAX_BAD_PINS:      # someone is guessing: cancel everything open
                self.pairings.clear()
                self.bad_pins = 0
                log.warning("too many wrong pairing codes; open pairings were cancelled")
        return None


class LanServer(TallyServer):
    remote = True

    def __init__(self, service, data_dir, access, bind):
        super().__init__(service, data_dir, bind=bind, handler=LanHandler)
        self.access = access

    def verify_request(self, request, client_address):
        return is_local_client(client_address[0])        # nothing from outside the local network


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Counting</title><meta name="theme-color" content="#1C2140"><link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icons/icon-180.png">
<style>:root{color-scheme:light dark;--bg:#EEE8DA;--surf:#FAF7EF;--ink:#1C2140;--mut:#565873;--blue:#24409A;--on:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#11142A;--surf:#1B2040;--ink:#EDE7D6;--mut:#AAACC8;--blue:#7C99FF;--on:#0C1030}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;display:grid;min-height:100vh;place-items:center;padding:1rem}
main{max-width:420px;width:100%;background:var(--surf);border:2px solid var(--ink);padding:1.4rem;box-shadow:6px 6px 0 var(--ink)}
h1{margin:.2rem 0 .6rem;font-size:1.6rem}p{color:var(--mut);margin:.4rem 0}
input{width:100%;font:inherit;font-size:1.6rem;letter-spacing:.3em;text-align:center;padding:.6rem;border:2px solid var(--ink);background:var(--bg);color:var(--ink);border-radius:2px;margin:.6rem 0}
button{width:100%;font:inherit;font-weight:600;padding:.7rem;border:2px solid var(--ink);background:var(--blue);color:var(--on);border-radius:2px;box-shadow:3px 3px 0 var(--ink)}
.err{color:#B3261E;font-weight:600}</style></head><body><main><h1>The Counting</h1>%(body)s</main></body></html>"""


class LanHandler(Handler):
    def _host_ok(self):
        port = self.server.port
        allowed = {"localhost:%d" % port, "127.0.0.1:%d" % port} | {"%s:%d" % (ip, port) for ip in lan_ips()}
        return self.headers.get("Host", "") in allowed        # a made-up name that points here is refused

    def _cookie(self):
        try:
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            return c[COOKIE].value if COOKIE in c else None
        except http.cookies.CookieError:
            return None

    def _pair_page(self, message=None, code=403):
        body = ('<p>This is a private copy of The Counting. To use it on this device, pair it with the computer.</p>'
                '<p>On the computer, open <b>Settings, then Use on my phone, then Pair a phone</b>. Scan its QR code with this '
                'device, or type the six-digit code below.</p>' + ('<p class="err">%s</p>' % message if message else "") +
                '<form method="post" action="/pair"><input name="pin" inputmode="numeric" pattern="[0-9]*" maxlength="6" '
                'autocomplete="off" placeholder="000000" aria-label="Six-digit code"><button>Pair this device</button></form>')
        self._send(code, PAGE.replace("%(body)s", body), "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def _pair_done(self, token):
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000" % (COOKIE, token))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _pre(self, method, path, url):
        access = self.server.access
        agent = self.headers.get("User-Agent", "")
        if method == "GET" and (path == "/manifest.webmanifest" or ICON.match(path)):
            return False                                     # public: contains nothing private
        if path == "/pair":
            token = None
            if method == "GET":
                token = access.use_code(parse_qs(url.query).get("code", [""])[0], agent)
            elif method == "POST":
                n = min(int(self.headers.get("Content-Length") or 0), 200)
                form = parse_qs(self.rfile.read(n).decode("utf-8", "ignore")) if n else {}
                token = access.use_pin(form.get("pin", [""])[0], agent)
            if token:
                self._pair_done(token)
            else:
                self._pair_page("That code is wrong or has expired. Show a new one on the computer.", 403)
            return True
        if access.check_cookie(self._cookie()) is None:
            if method == "GET" and path == "/":
                self._pair_page()
            else:
                self._send(403, {"error": "This device is not paired."})
            return True
        if path.startswith(DESKTOP_ONLY):
            self._send(403, {"error": "That can only be done on the computer."})
            return True
        return False
