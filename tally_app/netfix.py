"""Browser-style fallback for networks where the normal address lookup leads to a blocked server.

Edge and Chrome can look addresses up over an encrypted "secure DNS" service. Programs that ask Windows
directly get whatever the local network's DNS says. When that answer leads to a connection that is reset,
The Counting asks a public secure DNS service instead and connects to that address, with the same certificate checks.
"""
import http.client
import json
import logging
import os
import socket
import ssl
import urllib.error
import urllib.request

log = logging.getLogger("tally.net")

# Both accept HTTPS requests addressed by IP, so this does not depend on the local DNS.
DOH_URLS = ["https://1.1.1.1/dns-query", "https://8.8.8.8/resolve"]


def context():
    """Certificate rules. TALLY_CA_FILE is only used by the tests.

    The computer's own trusted certificates are used. A packaged app on a Mac often finds none (the Python it was built
    with has not had its certificates installed), which would stop every secure connection, so in that case a bundled
    set of trusted certificates (certifi) is added.
    """
    ca = os.environ.get("TALLY_CA_FILE")
    if ca:
        return ssl.create_default_context(cafile=ca)
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
            log.info("no system certificates found; using the bundled set")
        except Exception as e:  # pragma: no cover - only reached on an unusual install
            log.warning("no certificates available: %r", e)
    return ctx


def doh_urls():
    env = os.environ.get("TALLY_DOH_URLS")
    return env.split(",") if env else DOH_URLS


def doh_lookup(host, timeout=8):
    """Returns a list of IPv4 addresses for host, or an empty list."""
    for base in doh_urls():
        try:
            req = urllib.request.Request("%s?name=%s&type=A" % (base, host),
                                         headers={"Accept": "application/dns-json", "User-Agent": "TheCounting/0.3"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context()))
            with opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception as e:
            log.info("secure DNS %s failed: %r", base, e)
    return []


class _PinnedConnection(http.client.HTTPSConnection):
    """Connects to a chosen IP address but still checks the certificate for the real host name."""
    pin_ip = None

    def connect(self):
        sock = socket.create_connection((self.pin_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def open_pinned(req, ip, timeout=20):
    ctx = context()

    class Conn(_PinnedConnection):
        pin_ip = ip

    class Handler(urllib.request.HTTPSHandler):
        def https_open(self, r):
            return self.do_open(Conn, r, context=ctx)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Handler(context=ctx))
    return opener.open(req, timeout=timeout)


def tls_check(ip, host, port=443, timeout=10):
    """Opens a secure connection to ip, presenting host as the name. Raises on failure."""
    with socket.create_connection((ip, port), timeout=timeout) as raw:
        with context().wrap_socket(raw, server_hostname=host):
            return True
