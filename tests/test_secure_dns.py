"""Tests the secure-DNS fallback against a real local HTTPS server with a throwaway certificate."""
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tally_app import netfix  # noqa: E402
from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.service import Service  # noqa: E402
from tally_app.tmdb import TMDB, TMDBError  # noqa: E402

HOST = "blocked.example.test"  # cannot be resolved by normal DNS, like a host the local network refuses to answer for


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        code, body = (200, b'{"images": {}}') if "api_key=goodkey" in self.path else (401, b"{}")
        if self.path.startswith("/img"):
            code, body = 200, b"IMAGEBYTES"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Doh(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"Answer": [{"type": 1, "data": "127.0.0.1"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to make a test certificate")
class SecureDnsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "k.pem"),
                        "-out", str(d / "c.pem"), "-days", "2", "-subj", "/CN=" + HOST,
                        "-addext", "subjectAltName=DNS:%s,IP:127.0.0.1" % HOST], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(d / "c.pem"), str(d / "k.pem"))
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), Api)
        cls.api.socket = ctx.wrap_socket(cls.api.socket, server_side=True)
        cls.doh = HTTPServer(("127.0.0.1", 0), Doh)
        for s in (cls.api, cls.doh):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        os.environ["TALLY_CA_FILE"] = str(d / "c.pem")
        os.environ["TALLY_DOH_URLS"] = "http://127.0.0.1:%d/dns" % cls.doh.server_address[1]
        cls.base = "https://%s:%d/3" % (HOST, cls.api.server_address[1])

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("TALLY_CA_FILE", None)
        os.environ.pop("TALLY_DOH_URLS", None)
        cls.api.shutdown()
        cls.doh.shutdown()
        cls.tmp.cleanup()

    def test_falls_back_to_secure_dns_and_remembers(self):
        t = TMDB(lambda: "goodkey", base=self.base)
        self.assertEqual(t.get("/configuration"), {"images": {}})
        self.assertIn(HOST, t.pins)
        self.assertEqual(t.get("/configuration"), {"images": {}})  # second call uses the remembered address

    def test_wrong_key_still_reports_auth_error_through_fallback(self):
        t = TMDB(lambda: "nope", base=self.base)
        with self.assertRaises(TMDBError) as c:
            t.get("/configuration")
        self.assertEqual(c.exception.kind, "auth")

    def test_switch_off_means_no_fallback(self):
        t = TMDB(lambda: "goodkey", base=self.base, secure_dns=lambda: False)
        with self.assertRaises(TMDBError) as c:
            t.get("/configuration")
        self.assertEqual(c.exception.kind, "network")

    def test_certificate_is_still_checked(self):
        os.environ["TALLY_CA_FILE"], keep = "", os.environ["TALLY_CA_FILE"]
        try:
            other = Path(self.tmp.name) / "other.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(other) + ".k",
                            "-out", str(other), "-days", "2", "-subj", "/CN=other"], check=True, capture_output=True)
            os.environ["TALLY_CA_FILE"] = str(other)  # trusts a different certificate than the server presents
            t = TMDB(lambda: "goodkey", base=self.base)
            with self.assertRaises(TMDBError):
                t.get("/configuration")
            self.assertNotIn(HOST, t.pins)
        finally:
            os.environ["TALLY_CA_FILE"] = keep

    def test_artwork_download_uses_the_same_fallback(self):
        t = TMDB(lambda: "goodkey", base=self.base)
        self.assertEqual(t.fetch("https://%s:%d/img/x.jpg" % (HOST, self.api.server_address[1])), b"IMAGEBYTES")

    def test_diagnose_reports_secure_dns_rescue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            svc = Service(db, TMDB(lambda: db.get_setting("tmdb_key"), base=self.base), BackupManager(db, tmp))
            db.set_setting("tmdb_key", "goodkey")
            steps = svc.diagnose()
            names = [s["name"] for s in steps]
            self.assertTrue(any(n.startswith("Look up") for n in names), names)
            self.assertTrue(any(s["name"] == "Result" and "secure DNS" in s["detail"] for s in steps), steps)
            self.assertEqual(steps[-1]["detail"], "Your saved key works.")
            db.close()

    def test_no_secure_dns_service_reachable(self):
        keep = os.environ["TALLY_DOH_URLS"]
        os.environ["TALLY_DOH_URLS"] = "http://127.0.0.1:9/dns"
        try:
            self.assertEqual(netfix.doh_lookup(HOST, timeout=2), [])
        finally:
            os.environ["TALLY_DOH_URLS"] = keep


if __name__ == "__main__":
    unittest.main()
