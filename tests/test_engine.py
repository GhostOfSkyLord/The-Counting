"""Tests that keep the local engine alive and shut it down at the right time."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

FAKE = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % FAKE.server_address[1]

from tally_app import main as appmain  # noqa: E402
from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service  # noqa: E402
from tally_app.tmdb import TMDB  # noqa: E402


class LifetimeRules(unittest.TestCase):
    f = staticmethod(appmain.fallback_should_exit)

    def test_keeps_running_while_pings_arrive(self):
        self.assertEqual(self.f(100, 0, None, False, 98, None), (False, False))

    def test_minimised_window_with_throttled_pings_is_not_killed(self):
        # 3 minutes without a ping (background throttling) must not stop the engine
        self.assertEqual(self.f(300, 0, None, False, 120, None)[0], False)

    def test_long_silence_eventually_stops(self):
        self.assertTrue(self.f(1000, 0, None, False, 100, None)[0])

    def test_window_process_exit_stops(self):
        self.assertTrue(self.f(60, 0, 0, False, 58, None)[0])

    def test_browser_handoff_is_not_mistaken_for_close(self):
        done, early = self.f(3, 0, 0, False, None, None)
        self.assertEqual((done, early), (False, True))
        self.assertFalse(self.f(60, 0, 0, early, 58, None)[0])

    def test_goodbye_stops_after_grace_unless_page_came_back(self):
        self.assertFalse(self.f(52, 0, None, False, 40, 50)[0])
        self.assertTrue(self.f(60, 0, None, False, 40, 50)[0])
        self.assertFalse(self.f(60, 0, None, False, 55, 50)[0])  # a reload pinged again

    def test_page_that_never_connects_gives_up(self):
        self.assertTrue(self.f(100, 0, None, False, None, None)[0])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        tmp = Path(self._t.name)
        self.db = Database(tmp / "t.db")
        svc = Service(self.db, TMDB(lambda: fake_tmdb.GOOD_KEY), BackupManager(self.db, tmp))
        self.srv = TallyServer(svc, tmp)
        self.srv.start()

    def tearDown(self):
        self.srv.shutdown()
        self.db.close()
        self._t.cleanup()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.srv.url.rstrip("/") + path, headers=headers or {"X-Tally-Token": self.srv.token})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status

    def test_large_backlog(self):
        self.assertGreaterEqual(TallyServer.request_queue_size, 64)

    def test_burst_of_simultaneous_requests_all_succeed(self):
        with ThreadPoolExecutor(60) as pool:
            results = list(pool.map(lambda _: self.get("/api/state"), range(300)))
        self.assertEqual(set(results), {200})

    def test_server_loop_restarts_after_a_crash(self):
        self.srv.shutdown()  # stop the normal loop first
        self.srv._stopping = False
        real = self.srv.serve_forever
        calls = {"n": 0}

        def flaky(poll_interval=0.5):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash in the server loop")
            return real(poll_interval)
        self.srv.serve_forever = flaky
        t = threading.Thread(target=self.srv._loop, daemon=True)
        t.start()
        time.sleep(1.0)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(self.get("/api/state"), 200)

    def test_goodbye_beacon_uses_query_token_only_for_bye(self):
        base = self.srv.url.rstrip("/")
        req = urllib.request.Request(base + "/api/bye?t=" + self.srv.token, method="POST", data=b"")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
        self.assertIsNotNone(self.srv.bye_at)
        bad = urllib.request.Request(base + "/api/state?t=" + self.srv.token)  # query token must not open other routes
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(bad)
        self.assertEqual(c.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
