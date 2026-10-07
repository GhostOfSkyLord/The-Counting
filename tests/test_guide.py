"""First-time guidance: what is remembered, who counts as new, and what the checklist measures."""
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

FAKE = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % FAKE.server_address[1]
os.environ["TALLY_LAN_BIND"] = "127.0.0.1"
os.environ["TALLY_LAN_PORT"] = "0"
os.environ["TALLY_LAN_IPS"] = "127.0.0.1"

from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.guide import TIPS, VISITS  # noqa: E402
from tally_app.lan import LanAccess  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service, UserError  # noqa: E402
from tally_app.tmdb import TMDB  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.db = Database(self.tmp / "t.db")
        self.svc = Service(self.db, TMDB(lambda: self.db.get_setting("tmdb_key")), BackupManager(self.db, self.tmp))
        self.svc.save_key(fake_tmdb.GOOD_KEY)
        self.g = self.svc.guide

    def tearDown(self):
        self.db.close()
        self._t.cleanup()


class NewcomersAndVeterans(Base):
    def test_a_new_install_starts_with_everything_still_to_show(self):
        s = self.g.state()
        self.assertEqual((s["tour"], s["checklist"], s["tips"], s["visited"]), ("", "", [], []))

    def test_someone_with_shows_is_not_treated_as_new(self):
        self.svc.add_show(100, "watching")
        s = self.g.state()
        self.assertEqual((s["tour"], s["checklist"]), ("skipped", "dismissed"))
        self.assertEqual(set(s["tips"]), set(TIPS))
        self.assertEqual(set(s["visited"]), set(VISITS))

    def test_the_decision_is_made_once_and_kept(self):
        self.g.state()                             # a newcomer: saved as fresh
        self.svc.add_show(100, "watching")         # shows arrive later
        self.assertEqual(self.g.state()["tour"], "")   # still a newcomer: the tour is still on offer

    def test_ratings_alone_also_count_as_existing_data(self):
        self.svc.add_show(100, "watching")
        self.svc.ratings.rate(100, "5", overall=4)
        self.assertTrue(self.g.existing_data())

    def test_a_damaged_setting_falls_back_safely(self):
        self.db.set_setting("guide", "{not json")
        self.assertEqual(self.g.state()["tour"], "")


class Saving(Base):
    def test_tour_checklist_tips_and_visits_are_remembered(self):
        self.g.save({"tour": "done"})
        self.g.save({"checklist": "dismissed"})
        self.g.save({"tip": "ratings"})
        self.g.save({"tip": "ratings"})                        # twice changes nothing
        self.g.save({"visit": "arena"})
        s = Service(self.db, self.svc.tmdb, self.svc.backups).guide.state()      # as after a restart
        self.assertEqual((s["tour"], s["checklist"], s["tips"], s["visited"]), ("done", "dismissed", ["ratings"], ["arena"]))

    def test_reset_brings_everything_back(self):
        for p in ({"tour": "skipped"}, {"checklist": "dismissed"}, {"tip": "stats"}, {"visit": "discover"}):
            self.g.save(p)
        s = self.g.save({"reset": True})["state"]
        self.assertEqual((s["tour"], s["checklist"], s["tips"], s["visited"]), ("", "", [], []))

    def test_unknown_values_are_refused(self):
        for bad in ({"tour": "maybe"}, {"checklist": "x"}, {"tip": "nonsense"}, {"visit": "nowhere"}):
            with self.assertRaises(UserError):
                self.g.save(bad)

    def test_every_tip_and_visit_the_screens_use_is_known(self):
        self.assertEqual(set(TIPS), {"ratings", "arena", "discover", "stats", "show"})
        self.assertEqual(set(VISITS), {"arena", "discover"})


class Progress(Base):
    def test_the_checklist_follows_what_you_actually_do(self):
        p = self.g.progress()
        self.assertFalse(any(p.values()))
        self.svc.add_show(100, "watching")
        self.assertTrue(self.g.progress()["added"])
        eid = self.svc.detail(100)["season_list"][0]["episodes"][0]["id"]
        self.assertFalse(self.g.progress()["marked"])
        self.svc.mark(eid)
        self.assertTrue(self.g.progress()["marked"])
        self.svc.ratings.rate(100, "5", overall=4)
        self.assertTrue(self.g.progress()["rated"])
        self.svc.ratings.toggle_favourite(eid, 100)
        self.assertTrue(self.g.progress()["favourite"])
        self.assertFalse(self.g.progress()["phone"])
        self.db.x("INSERT INTO paired_devices(name,token_hash,created_at,last_seen) VALUES('iPhone','h',1,1)")
        self.assertTrue(self.g.progress()["phone"])

    def test_visiting_the_arena_and_discover_ticks_their_items(self):
        self.g.save({"visit": "arena"})
        p = self.g.progress()
        self.assertTrue(p["arena"] and not p["discover"])
        self.g.save({"visit": "discover"})
        self.assertTrue(self.g.progress()["discover"])


class Api(Base):
    def setUp(self):
        super().setUp()
        self.desktop = TallyServer(self.svc, self.tmp)
        self.desktop.start()
        self.svc.lan = LanAccess(self.svc, self.tmp)

    def tearDown(self):
        self.svc.lan.stop()
        self.desktop.shutdown()
        super().tearDown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.desktop.url.rstrip("/") + path, method=method,
                                     headers={"X-Tally-Token": self.desktop.token, "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_get_and_save_over_http(self):
        code, r = self.call("GET", "/api/guide")
        self.assertEqual((code, r["state"]["tour"], r["existing"]), (200, "", False))
        self.assertEqual(self.call("POST", "/api/guide", {"tour": "done"})[1]["state"]["tour"], "done")
        self.assertEqual(self.call("POST", "/api/guide", {"tip": "nope"})[0], 400)
        self.assertEqual(self.call("GET", "/api/guide")[1]["state"]["tour"], "done")

    def test_a_phone_cannot_change_the_computers_guide_state(self):
        from http.client import HTTPConnection
        self.svc.lan.set_enabled(True)
        link = self.svc.lan.new_pairing()["links"][0]
        port = self.svc.lan.server.port
        host = {"Host": "127.0.0.1:%d" % port}
        c = HTTPConnection("127.0.0.1", port)
        c.request("GET", "/pair?code=" + link.split("code=")[1], headers=host)
        cookie = c.getresponse().getheader("Set-Cookie").split(";")[0]
        c.close()
        c = HTTPConnection("127.0.0.1", port)
        c.request("GET", "/", headers={**host, "Cookie": cookie})
        html = c.getresponse().read().decode()
        token = html.split('name="tally-token" content="')[1].split('"')[0]
        c.close()
        hdr = {**host, "Cookie": cookie, "X-Tally-Token": token, "Content-Type": "application/json"}
        c = HTTPConnection("127.0.0.1", port)
        c.request("POST", "/api/guide", body=json.dumps({"tour": "done", "checklist": "dismissed"}), headers=hdr)
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        self.assertEqual(self.g.state()["tour"], "")             # untouched
        c = HTTPConnection("127.0.0.1", port)
        c.request("GET", "/api/guide", headers=hdr)
        r = c.getresponse()
        self.assertEqual(r.status, 200)                           # but the phone can read the progress it needs
        self.assertIn("progress", json.loads(r.read()))
        c.close()


if __name__ == "__main__":
    unittest.main()
