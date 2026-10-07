"""Small TMDB v3 client using only the standard library."""
import json
import logging
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from . import netfix

DEFAULT_BASE = "https://api.themoviedb.org/3"
ALT_BASE = "https://api.tmdb.org/3"  # second hostname, tried automatically if the first cannot be reached
log = logging.getLogger("tally.tmdb")


def clean_key(key):
    """Trim spaces and any quote marks picked up when copying the key."""
    return (key or "").strip().strip("\"'").strip()


def describe(reason):
    """A plain-language reason for a failed connection."""
    if isinstance(reason, ssl.SSLError):
        return ("the secure connection could not be verified. Antivirus, a firewall, a VPN or a proxy "
                "may be intercepting it.")
    if isinstance(reason, socket.gaierror):
        return "the address api.themoviedb.org could not be looked up (DNS). Check your internet connection."
    if isinstance(reason, TimeoutError):
        return "the connection timed out. Check your internet connection, VPN or firewall."
    if isinstance(reason, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)):
        return ("the connection was refused or reset. A firewall, antivirus, proxy, or your internet provider "
                "may be blocking it.")
    return str(reason) or reason.__class__.__name__


class TMDBError(Exception):
    """kind is one of: nokey, auth, notfound, rate, network, other."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


class TMDB:
    def __init__(self, get_key, base=None, secure_dns=None):
        self.get_key = get_key
        self.secure_dns = secure_dns or (lambda: True)
        self.pins = {}  # host -> IP that worked through secure DNS
        custom = base or os.environ.get("TALLY_TMDB_BASE")
        self.base = (custom or DEFAULT_BASE).rstrip("/")
        self.alt = None if custom else ALT_BASE
        self._lock = threading.Lock()
        self._last = 0.0

    @staticmethod
    def _is_bearer(key):
        # v4 "Read Access Token" is a long JWT; the v3 key is 32 hex characters.
        return key.startswith("eyJ") or len(key) > 60

    def _pace(self):
        with self._lock:  # stay well under TMDB's limit (roughly 40-50 requests per second)
            wait = 0.06 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def get(self, path, key=None, **params):
        key = clean_key(key if key is not None else self.get_key())
        if not key:
            raise TMDBError("nokey", "Add your TMDB API key in Settings first.")
        headers = {"Accept": "application/json", "User-Agent": "TheCounting/0.3"}
        params = {k: v for k, v in params.items() if v is not None}
        if self._is_bearer(key):
            headers["Authorization"] = "Bearer " + key
        else:
            params["api_key"] = key
        try:
            return self._request(self.base, path, params, headers)
        except TMDBError as first:
            if first.kind != "network" or not self.alt:
                raise
            try:  # the first hostname is unreachable: try the second, and remember which one works
                out = self._request(self.alt, path, params, headers)
            except TMDBError as second:
                if second.kind == "network":
                    raise first
                raise
            log.info("switching to %s", self.alt)
            self.base, self.alt = self.alt, self.base
            return out

    def _request(self, base, path, params, headers):
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(4):
            self._pace()
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._open(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    try:
                        delay = float(e.headers.get("Retry-After", "2"))
                    except ValueError:
                        delay = 2.0
                    time.sleep(min(delay, 10))
                    continue
                if e.code == 401:
                    raise TMDBError("auth", "TMDB rejected the API key. Check it in Settings.")
                if e.code == 404:
                    raise TMDBError("notfound", "TMDB does not have that page.")
                if e.code == 429:
                    raise TMDBError("rate", "TMDB is busy. Try again in a moment.")
                log.warning("TMDB returned %d for %s", e.code, path)
                raise TMDBError("other", "TMDB returned an error (%d)." % e.code)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                reason = getattr(e, "reason", e)
                log.warning("TMDB request to %s failed: %r", path, reason)
                raise TMDBError("network", "Could not reach TMDB: " + describe(reason))
            except ValueError:
                raise TMDBError("other", "TMDB sent a response The Counting could not read.")
        raise TMDBError("other", "TMDB did not respond.")

    def _open(self, req, timeout=20):
        """Normal request first. If the connection itself fails, retry the way a browser with secure DNS would."""
        host = urlparse(req.full_url).hostname
        secure = req.full_url.startswith("https://")
        ip = self.pins.get(host)
        if ip:
            try:
                return netfix.open_pinned(req, ip, timeout)
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, OSError):
                self.pins.pop(host, None)
        try:
            ctx = netfix.context() if os.environ.get("TALLY_CA_FILE") else None
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as first:
            if not secure or not self.secure_dns():
                raise
            for ip in netfix.doh_lookup(host):
                try:
                    resp = netfix.open_pinned(req, ip, timeout)
                    self.pins[host] = ip
                    log.info("connected to %s through secure DNS (%s)", host, ip)
                    return resp
                except urllib.error.HTTPError:
                    raise
                except (urllib.error.URLError, OSError):
                    continue
            raise first

    def fetch(self, url, timeout=20):
        """Downloads a URL (used for artwork) with the same fallbacks. Returns bytes."""
        req = urllib.request.Request(url, headers={"User-Agent": "TheCounting/0.3"})
        with self._open(req, timeout) as r:
            return r.read()

    def check_key(self, key):
        self.get("/configuration", key=key)
