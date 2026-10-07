"""Phone access: off by default, paired devices only, nothing destructive, local network only."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

FAKE = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % FAKE.server_address[1]
os.environ["TALLY_LAN_BIND"] = "127.0.0.1"      # tests stay on this machine
os.environ["TALLY_LAN_PORT"] = "0"
os.environ["TALLY_LAN_IPS"] = "127.0.0.1"

from tally_app import db as dbmod  # noqa: E402
from tally_app import lan as lanmod  # noqa: E402
from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.lan import LanAccess, is_local_client  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service  # noqa: E402
from tally_app.tmdb import TMDB  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.db = Database(self.tmp / "t.db")
        self.svc = Service(self.db, TMDB(lambda: self.db.get_setting("tmdb_key")), BackupManager(self.db, self.tmp))
        self.svc.save_key(fake_tmdb.GOOD_KEY)
        self.lan = LanAccess(self.svc, self.tmp)
        self.svc.lan = self.lan
        self.desktop = TallyServer(self.svc, self.tmp)
        self.desktop.start()

    def tearDown(self):
        self.lan.stop()
        self.desktop.shutdown()
        self.db.close()
        self._t.cleanup()

    # a request to the home-network server
    def phone(self, method, path, headers=None, body=None, host=None):
        port = self.lan.server.port
        c = HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": host or "127.0.0.1:%d" % port, "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        out = (r.status, dict(r.getheaders()), data)
        c.close()
        return out

    def desk(self, method, path, body=None):
        req = urllib.request.Request(self.desktop.url.rstrip("/") + path, method=method,
                                     headers={"X-Tally-Token": self.desktop.token, "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def pair(self):
        """Pairs a phone with the QR link and returns its cookie."""
        self.lan.set_enabled(True)
        link = self.lan.new_pairing()["links"][0]
        code = link.split("code=")[1]
        status, headers, _ = self.phone("GET", "/pair?code=" + code)
        self.assertEqual(status, 302)
        return headers["Set-Cookie"].split(";")[0]

    def authed(self, method, path, cookie, body=None):
        html = self.phone("GET", "/", {"Cookie": cookie})[2].decode()
        token = html.split('name="tally-token" content="')[1].split('"')[0]
        h = {"Cookie": cookie, "X-Tally-Token": token, "Content-Type": "application/json"}
        status, headers, data = self.phone(method, path, h, json.dumps(body).encode() if body is not None else None)
        try:
            return status, json.loads(data)
        except ValueError:
            return status, data


class Migration(unittest.TestCase):
    def test_version_3_database_upgrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "v3.db"
            c = sqlite3.connect(str(p))
            c.executescript("".join(dbmod.MIGRATIONS[:3]) + "PRAGMA user_version=3;")
            c.execute("INSERT INTO settings VALUES('tmdb_key','kept')")
            c.commit()
            c.close()
            d = Database(p)
            self.assertEqual(d.conn.execute("PRAGMA user_version").fetchone()[0], len(dbmod.MIGRATIONS))
            self.assertEqual(d.get_setting("tmdb_key"), "kept")
            d.q("SELECT * FROM paired_devices")
            d.close()


class Basics(Base):
    def test_off_by_default_and_nothing_listens(self):
        s = self.desk("GET", "/api/lan")[1]
        self.assertEqual((s["enabled"], s["running"]), (False, False))
        self.assertIsNone(self.lan.server)

    def test_turning_it_on_and_off(self):
        s = self.desk("POST", "/api/lan/enable", {"on": True})[1]
        self.assertTrue(s["running"] and s["enabled"])
        self.assertTrue(s["urls"][0].startswith("http://127.0.0.1:"))
        status, _, page = self.phone("GET", "/")
        self.assertEqual(status, 403)                       # listening, but only to show the pairing page
        self.assertIn(b"Pair this device", page)
        s = self.desk("POST", "/api/lan/enable", {"on": False})[1]
        self.assertFalse(s["running"])
        self.assertEqual(self.db.get_setting("lan_enabled"), "0")

    def test_the_setting_is_remembered_across_restarts(self):
        self.lan.set_enabled(True)
        self.lan.stop()
        fresh = LanAccess(self.svc, self.tmp)
        self.assertTrue(fresh.enabled())
        fresh.start()
        self.assertIsNotNone(fresh.server)
        fresh.stop()

    def test_pairing_needs_phone_access_on(self):
        code, r = self.desk("POST", "/api/lan/pair", {})
        self.assertEqual(code, 400)
        self.assertIn("off", r["error"])

    def test_local_network_check(self):
        for ok in ("192.168.1.20", "10.0.0.5", "172.16.4.4", "127.0.0.1", "169.254.1.1", "100.100.1.2", "::1", "fe80::1%eth0"):
            self.assertTrue(is_local_client(ok), ok)
        for bad in ("8.8.8.8", "93.184.216.34", "2606:4700:4700::1111", "not an address"):
            self.assertFalse(is_local_client(bad), bad)


class Pairing(Base):
    def test_an_unpaired_device_sees_only_the_pairing_page(self):
        self.lan.set_enabled(True)
        status, _, data = self.phone("GET", "/")
        self.assertEqual(status, 403)
        page = data.decode()
        self.assertIn("pair", page.lower())
        self.assertNotIn("tally-token", page)                 # no key to the API
        for path in ("/api/state", "/api/library", "/style.css", "/app.js", "/img/w185/x.jpg"):
            self.assertEqual(self.phone("GET", path)[0], 403, path)

    def test_the_qr_link_pairs_once(self):
        self.lan.set_enabled(True)
        link = self.lan.new_pairing()["links"][0]
        code = link.split("code=")[1]
        status, headers, _ = self.phone("GET", "/pair?code=" + code)
        self.assertEqual(status, 302)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(self.phone("GET", "/pair?code=" + code)[0], 403)    # the same link cannot be used twice
        self.assertEqual(self.phone("GET", "/", {"Cookie": cookie.split(";")[0]})[0], 200)

    def test_the_six_digit_code_pairs_too(self):
        self.lan.set_enabled(True)
        pin = self.lan.new_pairing()["pin"]
        self.assertRegex(pin, r"^\d{6}$")
        status, headers, _ = self.phone("POST", "/pair", {"Content-Type": "application/x-www-form-urlencoded"}, ("pin=" + pin).encode())
        self.assertEqual(status, 302)
        self.assertIn(lanmod.COOKIE + "=", headers["Set-Cookie"])

    def test_wrong_codes_are_refused_and_guessing_cancels_pairings(self):
        self.lan.set_enabled(True)
        info = self.lan.new_pairing()
        wrong = "000000" if info["pin"] != "000000" else "111111"
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        for _ in range(lanmod.MAX_BAD_PINS):
            self.assertEqual(self.phone("POST", "/pair", form, ("pin=" + wrong).encode())[0], 403)
        # five wrong guesses: even the right code no longer works
        self.assertEqual(self.phone("POST", "/pair", form, ("pin=" + info["pin"]).encode())[0], 403)
        self.assertEqual(self.phone("GET", "/pair?code=" + info["links"][0].split("code=")[1])[0], 403)

    def test_expired_codes_do_not_work(self):
        self.lan.set_enabled(True)
        info = self.lan.new_pairing()
        for p in self.lan.pairings.values():
            p["expires"] = 0
        self.assertEqual(self.phone("GET", "/pair?code=" + info["links"][0].split("code=")[1])[0], 403)
        self.assertEqual(self.phone("POST", "/pair", {"Content-Type": "application/x-www-form-urlencoded"}, ("pin=" + info["pin"]).encode())[0], 403)

    def test_only_a_hash_of_the_device_secret_is_stored(self):
        cookie = self.pair()
        secret = cookie.split("=", 1)[1]
        stored = self.db.q1("SELECT token_hash FROM paired_devices")["token_hash"]
        self.assertNotEqual(stored, secret)
        self.assertEqual(len(stored), 64)

    def test_devices_are_named_listed_and_can_be_forgotten(self):
        cookie = self.pair()
        devs = self.desk("GET", "/api/lan")[1]["devices"]
        self.assertEqual([d["name"] for d in devs], ["iPhone"])
        self.assertEqual(self.phone("GET", "/", {"Cookie": cookie})[0], 200)
        self.desk("POST", "/api/lan/forget", {"id": devs[0]["id"]})
        self.assertEqual(self.phone("GET", "/", {"Cookie": cookie})[0], 403)     # revoked at once
        self.assertEqual(self.desk("GET", "/api/lan")[1]["devices"], [])

    def test_pairing_is_cancelled_when_phone_access_is_switched_off(self):
        self.lan.set_enabled(True)
        info = self.lan.new_pairing()
        self.lan.set_enabled(False)
        self.lan.set_enabled(True)
        self.assertEqual(self.phone("GET", "/pair?code=" + info["links"][0].split("code=")[1])[0], 403)


class WhatAPhoneCanDo(Base):
    def test_a_paired_phone_can_use_the_app(self):
        cookie = self.pair()
        self.assertEqual(self.authed("POST", "/api/shows", cookie, {"tmdb_id": 100, "status": "watching"})[0], 200)
        status, d = self.authed("GET", "/api/shows/100", cookie)
        self.assertEqual(status, 200)
        eid = d["season_list"][0]["episodes"][0]["id"]
        self.assertEqual(self.authed("POST", "/api/mark", cookie, {"episode_id": eid})[0], 200)
        self.assertEqual(self.authed("GET", "/api/library?status=watching", cookie)[1]["shows"][0]["progress"]["watched"], 1)
        self.assertEqual(self.authed("POST", "/api/ratings", cookie, {"show_id": 100, "mode": "5", "overall": 4})[0], 200)
        self.assertEqual(self.authed("GET", "/api/stats", cookie)[0], 200)
        self.assertEqual(self.authed("GET", "/api/search?q=harbour", cookie)[0], 200)

    def test_what_the_phone_does_shows_on_the_computer(self):
        cookie = self.pair()
        self.authed("POST", "/api/shows", cookie, {"tmdb_id": 100, "status": "plan"})
        self.assertEqual(self.desk("GET", "/api/library?status=plan")[1]["shows"][0]["id"], 100)

    def test_nothing_that_touches_the_computer_is_allowed(self):
        cookie = self.pair()
        for method, path, body in (("POST", "/api/open-folder", {}), ("POST", "/api/open-data-folder", {}), ("POST", "/api/open-url", {"url": "https://www.themoviedb.org"}),
                                   ("POST", "/api/pick-folder", {}), ("POST", "/api/export", {}), ("POST", "/api/import", {"format": "tally-export"}),
                                   ("GET", "/api/backups", None), ("POST", "/api/backups/now", {}), ("POST", "/api/backups/restore", {"name": "x"}),
                                   ("POST", "/api/settings/key", {"key": "abc"}), ("POST", "/api/settings/backup", {"folder": "C:/x"}),
                                   ("POST", "/api/settings/network", {"secure_dns": False}), ("POST", "/api/settings/theme", {"theme": "dark"}),
                                   ("POST", "/api/diagnose", {}), ("POST", "/api/selftest", {}), ("GET", "/api/lan", None), ("POST", "/api/lan/enable", {"on": False}),
                                   ("POST", "/api/lan/pair", {}), ("POST", "/api/lan/forget", {"id": 1})):
            status, r = self.authed(method, path, cookie, body)
            self.assertEqual(status, 403, path)
            self.assertIn("computer", r["error"], path)
        self.assertTrue(self.lan.status()["running"])              # and it did not switch itself off
        self.assertEqual(self.db.get_setting("theme", "system"), "system")
        self.assertEqual(self.db.get_setting("tmdb_key"), fake_tmdb.GOOD_KEY)

    def test_the_phone_is_told_it_is_remote_and_not_where_files_live(self):
        cookie = self.pair()
        s = self.authed("GET", "/api/state", cookie)[1]
        self.assertTrue(s["remote"])
        self.assertNotIn("backup_folder", s)
        self.assertFalse(self.desk("GET", "/api/state")[1]["remote"])
        self.assertIn("backup_folder", self.desk("GET", "/api/state")[1])

    def test_a_cookie_alone_is_not_enough(self):
        cookie = self.pair()
        self.assertEqual(self.phone("GET", "/api/state", {"Cookie": cookie})[0], 403)                 # no header token
        self.assertEqual(self.phone("GET", "/api/state", {"Cookie": cookie, "X-Tally-Token": "guess"})[0], 403)

    def test_the_desktop_token_does_not_work_on_the_phone_server(self):
        cookie = self.pair()
        self.assertEqual(self.phone("GET", "/api/state", {"Cookie": cookie, "X-Tally-Token": self.desktop.token})[0], 403)

    def test_a_made_up_host_name_is_refused(self):
        cookie = self.pair()
        self.assertEqual(self.phone("GET", "/", {"Cookie": cookie}, host="evil.example.com:80")[0], 403)
        self.assertEqual(self.phone("GET", "/pair?code=x", host="rebind.example:1234")[0], 403)

    def test_the_install_files_are_public_but_hold_nothing_private(self):
        self.lan.set_enabled(True)
        status, headers, data = self.phone("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200)
        m = json.loads(data)
        self.assertEqual((m["name"], m["display"]), ("The Counting", "standalone"))
        self.assertEqual(self.phone("GET", "/icons/icon-192.png")[0], 200)
        self.assertNotIn(b"token", data.lower())

    def test_requests_from_outside_the_local_network_are_dropped(self):
        self.lan.set_enabled(True)
        self.assertFalse(self.lan.server.verify_request(None, ("8.8.8.8", 4000)))
        self.assertFalse(self.lan.server.verify_request(None, ("2606:4700:4700::1111", 4000, 0, 0)))
        self.assertTrue(self.lan.server.verify_request(None, ("192.168.1.9", 4000)))

    def test_the_computers_own_window_is_not_affected(self):
        self.lan.set_enabled(True)
        self.assertEqual(self.desk("GET", "/api/library?status=watching")[0], 200)
        with urllib.request.urlopen(self.desktop.url) as r:
            self.assertIn("tally-token", r.read().decode())


if __name__ == "__main__":
    unittest.main()
