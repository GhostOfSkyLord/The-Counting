import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

FAKE = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % FAKE.server_address[1]
os.environ["TALLY_IMG_BASE"] = "http://127.0.0.1:%d/t/p" % FAKE.server_address[1]

from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service, UserError  # noqa: E402
from tally_app.sync import Refresher, needs_refresh  # noqa: E402
from tally_app.tmdb import TMDB, TMDBError  # noqa: E402


def make_app(tmp):
    db = Database(Path(tmp) / "tally.db")
    backups = BackupManager(db, tmp)
    tmdb = TMDB(lambda: db.get_setting("tmdb_key"))
    svc = Service(db, tmdb, backups)
    svc.save_key(fake_tmdb.GOOD_KEY)
    return db, backups, tmdb, svc


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name
        self.db, self.backups, self.tmdb, self.svc = make_app(self.tmp)

    def tearDown(self):
        self.db.close()
        self._t.cleanup()

    def eps(self, sid, season=None):
        d = self.svc.detail(sid)
        out = [e for s in d["season_list"] for e in s["episodes"] if season in (None, s["number"])]
        return out


class TestTmdbAndSync(Base):
    def test_key_validation(self):
        with self.assertRaises(UserError) as c:
            self.svc.save_key("wrongkey")
        self.assertIn("rejected", str(c.exception))
        self.svc.save_key(fake_tmdb.GOOD_KEY)
        self.assertTrue(self.svc.has_key())

    def test_search_and_add(self):
        res = self.svc.search("harbour")
        self.assertEqual(res[0]["id"], 100)
        s = self.svc.add_show(100, "plan")
        self.assertEqual(s["episodes"], 8)
        self.assertEqual(self.svc.search("harbour")[0]["in_library"], "plan")
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM episodes WHERE show_id=100 AND season_number=0")["n"], 2)

    def test_many_seasons_are_chunked(self):
        self.svc.add_show(300, "plan")
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM episodes WHERE show_id=300")["n"], 40)
        appended = [c for c in fake_tmdb.CALLS if "/tv/300?" in c and "append_to_response" in c]
        self.assertGreaterEqual(len(appended), 2)

    def test_missing_key_and_network(self):
        db2 = Database(Path(self.tmp) / "other.db")
        t = TMDB(lambda: db2.get_setting("tmdb_key"))
        with self.assertRaises(TMDBError) as c:
            t.get("/configuration")
        self.assertEqual(c.exception.kind, "nokey")
        bad = TMDB(lambda: "k", base="http://127.0.0.1:9/3")
        with self.assertRaises(TMDBError) as c:
            bad.get("/configuration")
        self.assertEqual(c.exception.kind, "network")
        db2.close()

    def test_resync_keeps_history(self):
        self.svc.add_show(100, "watching")
        e = self.eps(100, 1)
        self.svc.mark(e[0]["id"])
        before = self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"]
        self.svc.refresh_show(100)
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], before)
        self.assertEqual(self.eps(100, 1)[0]["watched"], 1)

    def test_removed_episode_keeps_events(self):
        self.svc.add_show(100, "watching")
        e = self.eps(100, 1)
        self.svc.mark(e[0]["id"])
        fake_tmdb.SHOWS[100]["_eps"][1]["episodes"].pop(0)
        try:
            self.svc.refresh_show(100)
            self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], 1)
            self.assertIsNone(self.db.q1("SELECT 1 FROM episodes WHERE id=?", (e[0]["id"],)))
            self.assertEqual(self.svc.log()[0]["label"], "episode no longer listed")
        finally:
            fake_tmdb.SHOWS.update({100: fake_tmdb.make_show(100, "Harbour Lights", "Ended", [(4, 4), (4, 4)], specials=2, genres=("Drama", "Mystery"))})

    def test_refresher_policy(self):
        self.svc.add_show(200, "watching")
        row = dict(self.db.q1("SELECT * FROM shows WHERE id=200"))
        self.assertFalse(needs_refresh(row))
        self.assertTrue(needs_refresh(row, now=time.time() + 2 * 86400))
        ended = dict(self.db.q1("SELECT * FROM shows WHERE id=200"))
        ended.update(tmdb_status="Ended", in_production=0)
        self.assertFalse(needs_refresh(ended, now=time.time() + 2 * 86400))
        self.db.x("INSERT INTO user_shows VALUES(400,'plan','manual',0,0)")
        r = Refresher(self.db, self.tmdb, lambda: True)
        self.assertIn(400, r.work_list())


class TestConnectionHelp(Base):
    def test_reasons_are_plain_language(self):
        import socket
        import ssl
        from tally_app.tmdb import clean_key, describe
        self.assertIn("intercepting", describe(ssl.SSLCertVerificationError("bad")))
        self.assertIn("DNS", describe(socket.gaierror(11001, "no such host")))
        self.assertIn("timed out", describe(TimeoutError()))
        self.assertIn("firewall", describe(ConnectionRefusedError()))
        self.assertEqual(clean_key('  "abc123"  '), "abc123")

    def test_key_with_quotes_is_accepted(self):
        self.svc.save_key('"%s" ' % fake_tmdb.GOOD_KEY)
        self.assertEqual(self.db.get_setting("tmdb_key"), fake_tmdb.GOOD_KEY)

    def test_network_error_message_includes_reason(self):
        bad = TMDB(lambda: "k", base="http://127.0.0.1:9/3")
        with self.assertRaises(TMDBError) as c:
            bad.get("/configuration")
        self.assertTrue(c.exception.message.startswith("Could not reach TMDB: "))

    def test_diagnose_passes_and_pinpoints_failure(self):
        steps = self.svc.diagnose()
        self.assertTrue(all(s["ok"] for s in steps), steps)
        self.assertEqual(steps[-1]["detail"], "Your saved key works.")
        self.svc.tmdb.base = "http://127.0.0.1:9/3"
        steps = self.svc.diagnose()
        self.assertFalse(steps[-1]["ok"])
        self.assertTrue(steps[-1]["name"].startswith(("Ask ", "Secure connection", "Find ")))


class TestHostFallback(Base):
    def test_falls_back_to_second_hostname_and_remembers(self):
        dead = "http://127.0.0.1:9/3"
        live = os.environ["TALLY_TMDB_BASE"]
        client = TMDB(lambda: fake_tmdb.GOOD_KEY, base=dead)
        client.alt = live  # simulate: default host blocked, alternate host reachable
        self.assertEqual(client.get("/configuration"), {"images": {}})
        self.assertEqual((client.base, client.alt), (live, dead))
        self.assertEqual(client.get("/configuration"), {"images": {}})  # goes straight to the working host

    def test_both_hosts_down_reports_first_reason(self):
        client = TMDB(lambda: "k", base="http://127.0.0.1:9/3")
        client.alt = "http://127.0.0.1:8/3"
        with self.assertRaises(TMDBError) as c:
            client.get("/configuration")
        self.assertEqual(c.exception.kind, "network")

    def test_http_errors_do_not_trigger_fallback(self):
        client = TMDB(lambda: "wrongkey", base=os.environ["TALLY_TMDB_BASE"])
        client.alt = "http://127.0.0.1:9/3"
        with self.assertRaises(TMDBError) as c:
            client.get("/configuration")
        self.assertEqual(c.exception.kind, "auth")

    def test_diagnose_reports_working_second_host(self):
        self.svc.tmdb.alt = self.svc.tmdb.base
        self.svc.tmdb.base = "http://127.0.0.1:9/3"
        steps = self.svc.diagnose()
        self.assertTrue(any(s["name"] == "Result" for s in steps), steps)
        self.assertEqual(steps[-1]["detail"], "Your saved key works.")


class TestTracking(Base):
    def setUp(self):
        super().setUp()
        self.svc.add_show(100, "plan")
        self.e = self.eps(100, 1)

    def test_first_mark_starts_show(self):
        r = self.svc.mark(self.e[0]["id"])
        self.assertTrue(r["started"])
        self.assertEqual(self.svc.summary(100)["status"], "watching")

    def test_gap_prompt_and_resolutions(self):
        r = self.svc.mark(self.e[2]["id"])
        self.assertEqual(r, {"prompt": "gaps", "count": 2})
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], 0)
        self.svc.mark(self.e[2]["id"], "all")
        ev = self.db.q("SELECT source, ts FROM watch_events ORDER BY id")
        self.assertEqual([x["source"] for x in ev], ["bulk", "bulk", "single"])
        self.assertIsNone(ev[0]["ts"])
        self.assertIsNotNone(ev[2]["ts"])
        # "just this one"
        self.svc.mark(self.e[3]["id"], "one")
        self.assertEqual(self.eps(100, 1)[3]["watched"], 1)

    def test_rewatch_prompt_and_undo(self):
        self.svc.mark(self.e[0]["id"])
        self.assertEqual(self.svc.mark(self.e[0]["id"]), {"prompt": "rewatch"})
        self.svc.mark(self.e[0]["id"], "rewatch")
        self.assertEqual(self.eps(100, 1)[0]["watched"], 2)
        self.svc.mark(self.e[0]["id"], "undo")
        self.assertEqual(self.eps(100, 1)[0]["watched"], 1)
        n = self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"]
        self.svc.mark(self.e[0]["id"], "mistake")
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], n)
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events WHERE type='undo'")["n"], 1)

    def test_seen_up_to_fills_gaps_only(self):
        self.svc.mark(self.e[0]["id"])
        r = self.svc.seen_up_to(self.e[2]["id"])
        self.assertEqual((r["marked"], r["skipped"]), (2, 1))
        self.assertEqual(self.svc.seen_up_to(self.e[2]["id"])["marked"], 0)
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], 3)

    def test_unaired_cannot_be_marked(self):
        self.svc.add_show(200, "plan")
        s2 = self.eps(200, 2)
        with self.assertRaises(UserError):
            self.svc.mark(s2[3]["id"])

    def test_spoiler_curtain_server_side(self):
        eps = self.eps(100, 1)
        self.assertTrue(eps[0]["unlocked"])
        self.assertFalse(eps[1]["unlocked"])
        self.assertIsNone(eps[1]["overview"])
        self.assertIsNone(eps[1]["still_path"])
        self.svc.mark(eps[0]["id"])
        eps = self.eps(100, 1)
        self.assertTrue(eps[1]["unlocked"])
        self.assertIn("Synopsis", eps[1]["overview"])
        self.assertFalse(eps[2]["unlocked"])

    def test_hide_titles_override(self):
        d = self.svc.set_overrides(100, {"hide_titles": True})
        self.assertIsNone(d["season_list"][0]["episodes"][0]["name"])
        self.svc.mark(self.e[0]["id"])
        self.assertIsNone(self.svc.summary(100)["next"]["name"])
        d = self.svc.set_overrides(100, {"hide_titles": False})
        self.assertIsNotNone(d["season_list"][0]["episodes"][0]["name"])

    def test_absolute_numbering_and_specials(self):
        d = self.svc.set_overrides(100, {"absolute_numbering": True})
        self.assertEqual(d["season_list"][1]["episodes"][0]["label"], "S2E1 (#5)")
        self.assertEqual(len(d["specials"]), 2)
        # specials are excluded from progress by default
        self.assertEqual(d["progress"]["total"], 8)
        d = self.svc.set_overrides(100, {"include_specials": True})
        self.assertEqual(d["progress"]["total"], 10)

    def test_specials_can_be_marked_without_gap_prompt(self):
        sp = self.svc.detail(100)["specials"]
        r = self.svc.mark(sp[1]["id"])
        self.assertTrue(r["ok"])

    def test_all_watched_and_readiness(self):
        for e in self.eps(100):
            self.svc.mark(e["id"], "all")
        s = self.svc.summary(100)
        self.assertEqual(s["state"], "All watched")
        self.assertIsNone(s["next"])
        self.assertEqual(s["progress"]["percent"], 100)
        self.assertEqual(s["readiness"]["kind"], "ready")

    def test_returning_show_states(self):
        self.svc.add_show(200, "watching")
        self.assertEqual(self.svc.summary(200)["readiness"]["kind"], "wait")
        for e in self.eps(200):
            if e["aired"]:
                self.svc.mark(e["id"], "all")
        s = self.svc.summary(200)
        self.assertEqual(s["state"], "Up to date")
        self.assertEqual(s["progress"]["total"], 6)
        self.svc.add_show(400, "plan")
        self.assertEqual(self.svc.summary(400)["readiness"]["kind"], "wait")

    def test_maybe_ready_vs_finale(self):
        fake_tmdb.SHOWS[201] = fake_tmdb.make_show(201, "Done Airing", "Returning Series", [(3, 3)], finale=True)
        fake_tmdb.SHOWS[202] = fake_tmdb.make_show(202, "Unsure", "Returning Series", [(3, 3)], finale=False)
        self.assertEqual(self.svc.add_show(201)["readiness"]["text"], "Latest season ready")
        self.assertEqual(self.svc.add_show(202)["readiness"]["text"], "Probably ready")

    def test_lists_and_status(self):
        self.svc.mark(self.e[0]["id"])
        lib = self.svc.library("watching")
        self.assertEqual([s["id"] for s in lib["shows"]], [100])
        self.assertEqual(lib["shows"][0]["next"]["label"], "S1E2")
        self.svc.add_show(400, "plan")
        self.assertEqual([s["id"] for s in self.svc.to_watch()["shows"]], [400])
        with self.assertRaises(UserError):
            self.svc.set_status(100, "nonsense")

    def test_remove_show_keeps_history(self):
        self.svc.mark(self.e[0]["id"])
        self.svc.remove_show(100)
        self.assertEqual(self.svc.status_counts()["watching"], 0)
        self.svc.add_show(100, "watching")
        self.assertEqual(self.eps(100, 1)[0]["watched"], 1)

    def test_stats_and_log(self):
        self.svc.mark(self.eps(100, 1)[3]["id"], "all")  # 3 bulk (undated) + 1 dated
        self.svc.mark(self.e[0]["id"], "rewatch")
        st = self.svc.stats()
        self.assertEqual(st["episodes"], 4)
        self.assertEqual(st["rewatched"], 1)
        self.assertAlmostEqual(st["hours"], 5 * 45 / 60, places=1)
        self.assertEqual(st["undated"], 3)
        self.assertEqual({g for g, _ in st["by_genre"]}, {"Drama", "Mystery"})
        self.assertEqual(self.svc.log()[0]["source"], "rewatch")

    def test_seen_through_season(self):
        self.assertEqual(self.svc.mark_through_season(100, 1)["marked"], 4)


class TestBackups(Base):
    def setUp(self):
        super().setUp()
        self.svc.add_show(100, "watching")
        self.e = self.eps(100, 1)
        self.svc.mark(self.e[0]["id"])

    def test_snapshot_restore_roundtrip(self):
        snap = self.backups.snapshot("manual")
        self.assertTrue(snap.exists())
        self.svc.mark(self.e[1]["id"])
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], 2)
        self.backups.restore(snap.name)
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events")["n"], 1)
        self.assertTrue(self.svc.has_key())  # API key survives a restore
        self.assertTrue(any("before-restore" in b["name"] for b in self.backups.list()))

    def test_restore_rejects_bad_files(self):
        bad = self.backups.folder() / "tally-bad.db"
        c = sqlite3.connect(str(bad))
        c.execute("CREATE TABLE junk(a)")
        c.commit()
        c.close()
        with self.assertRaises(ValueError):
            self.backups.restore("tally-bad.db")
        with self.assertRaises(ValueError):
            self.backups.restore("../../etc/passwd")

    def test_prune_and_exit_logic(self):
        self.db.set_setting("backup_keep", "3")
        for _ in range(5):
            self.backups.snapshot("manual")
        self.assertEqual(len(self.backups.list()), 3)
        n = len(self.backups.list())
        self.backups.on_exit()  # nothing changed since last snapshot -> no new file
        self.assertEqual(len(self.backups.list()), n)
        self.svc.mark(self.e[1]["id"])
        self.backups.on_exit()
        self.assertTrue(any("exit" in b["name"] for b in self.backups.list()))

    def test_launch_backup_interval(self):
        self.backups.on_launch()
        self.assertEqual(len(self.backups.list()), 1)
        self.backups.on_launch()  # recent backup exists
        self.assertEqual(len(self.backups.list()), 1)

    def test_custom_folder(self):
        target = Path(self.tmp) / "cloud" / "tally"
        self.svc.save_backup_settings(folder=str(target))
        self.backups.snapshot("manual")
        self.assertEqual(len(list(target.glob("tally-*.db"))), 1)

    def test_export_import_roundtrip(self):
        path = self.backups.export_json()
        data = json.loads(path.read_text())
        self.assertNotIn("tmdb_key", json.dumps(data))
        self.svc.remove_show(100)
        self.db.x("DELETE FROM watch_events")
        res = self.backups.import_json(data)
        self.assertEqual(res["events"], 1)
        self.assertEqual(self.svc.status_counts()["watching"], 1)
        self.assertEqual(self.eps(100, 1)[0]["watched"], 1)
        with self.assertRaises(ValueError):
            self.backups.import_json({"format": "other"})

    def test_import_then_refresher_fetches_missing_shows(self):
        data = json.loads(self.backups.export_json().read_text())
        self.db.x("DELETE FROM shows")
        self.db.x("DELETE FROM episodes")
        s = self.svc.summary(100)
        self.assertTrue(s["loading"])
        Refresher(self.db, self.tmdb, lambda: True).work_list()
        from tally_app.sync import sync_show
        for sid in Refresher(self.db, self.tmdb, lambda: True).work_list():
            sync_show(self.db, self.tmdb, sid)
        self.assertFalse(self.svc.summary(100).get("loading"))
        self.assertEqual(self.eps(100, 1)[0]["watched"], 1)


class TestHttp(Base):
    def setUp(self):
        super().setUp()
        self.srv = TallyServer(self.svc, Path(self.tmp))
        self.srv.start()
        self.base = self.srv.url.rstrip("/")

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def call(self, method, path, body=None, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Tally-Token"] = self.srv.token
        if host:
            headers["Host"] = host
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_security(self):
        self.assertEqual(self.call("GET", "/api/state", token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/state", host="evil.example.com")[0], 403)
        self.assertEqual(self.call("GET", "/api/state")[0], 200)

    def test_index_gets_token_and_static(self):
        with urllib.request.urlopen(self.base + "/") as r:
            html = r.read().decode()
        self.assertIn(self.srv.token, html)
        self.assertNotIn("{{TOKEN}}", html)
        for f in ("/style.css", "/app.js"):
            with urllib.request.urlopen(self.base + f) as r:
                self.assertEqual(r.status, 200)

    def test_flow_over_http(self):
        code, res = self.call("GET", "/api/search?q=harbour")
        self.assertEqual(res["results"][0]["id"], 100)
        code, s = self.call("POST", "/api/shows", {"tmdb_id": 100, "status": "plan"})
        self.assertEqual(code, 200)
        code, d = self.call("GET", "/api/shows/100")
        eid = d["season_list"][0]["episodes"][0]["id"]
        code, r = self.call("POST", "/api/mark", {"episode_id": eid})
        self.assertTrue(r["started"])
        code, r = self.call("POST", "/api/mark", {"episode_id": eid})
        self.assertEqual(r["prompt"], "rewatch")
        code, r = self.call("POST", "/api/shows/100/status", {"status": "bogus"})
        self.assertEqual(code, 400)
        self.assertIn("Unknown", r["error"])
        self.assertEqual(self.call("GET", "/api/library?status=watching")[1]["shows"][0]["id"], 100)
        self.assertEqual(self.call("GET", "/api/stats")[1]["episodes"], 1)
        self.assertEqual(self.call("POST", "/api/backups/now", {})[0], 200)
        self.assertEqual(self.call("DELETE", "/api/shows/100", {})[0], 200)

    def test_tmdb_errors_become_messages(self):
        self.db.set_setting("tmdb_key", "wrong")
        code, r = self.call("GET", "/api/search?q=harbour")
        self.assertEqual(code, 502)
        self.assertEqual(r["kind"], "auth")

    def test_image_proxy_caches_and_validates(self):
        with urllib.request.urlopen(self.base + "/img/w185/poster100.jpg".replace("/poster", "/poster")) as r:
            self.assertEqual(r.status, 200)
        self.assertTrue((Path(self.tmp) / "imgcache" / "w185" / "poster100.jpg").exists())
        for bad in ("/img/w185/../../x.jpg", "/img/evil/poster.jpg", "/img/w185/a.exe"):
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(self.base + bad)

    def test_open_url_allowlist(self):
        self.assertEqual(self.call("POST", "/api/open-url", {"url": "https://evil.example.com"})[0], 400)


if __name__ == "__main__":
    unittest.main(verbosity=1)
