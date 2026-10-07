"""The self-check, and the certificate safety net that keeps a packaged Mac app able to reach TMDB."""
import json
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tally_app import netfix, selftest  # noqa: E402


class SelfCheck(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"THECOUNTING_HOME": self._t.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._t.cleanup()

    def test_all_required_checks_pass_from_source(self):
        r = selftest.run(network=False)
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["Data folder", "App files", "Database", "Local server", "Trusted certificates", "Phone access", "Window component"])
        self.assertTrue(r["ok"], r["text"])
        self.assertIn("ALL REQUIRED CHECKS PASSED", r["text"])
        self.assertEqual(r["info"]["frozen"], False)

    def test_the_window_component_is_only_required_in_a_built_app(self):
        with mock.patch.dict(sys.modules, {"webview": None}):
            r = selftest.run(network=False)
            win = next(c for c in r["checks"] if c["name"] == "Window component")
            self.assertFalse(win["ok"])
            self.assertFalse(win["required"])
            self.assertTrue(r["ok"])                                # from source it is optional
            with mock.patch.object(sys, "frozen", True, create=True):
                r = selftest.run(network=False)
            self.assertFalse(r["ok"])                               # in a built app it is not
            self.assertIn("PROBLEMS FOUND", r["text"])

    def test_missing_app_files_are_named(self):
        with mock.patch.object(selftest, "NEEDED", selftest.NEEDED + ["nothing-here.js"]):
            r = selftest.run(network=False)
        web = next(c for c in r["checks"] if c["name"] == "App files")
        self.assertFalse(web["ok"])
        self.assertIn("nothing-here.js", web["detail"])
        self.assertFalse(r["ok"])

    def test_it_never_touches_the_real_database(self):
        selftest.run(network=False)
        self.assertEqual([p.name for p in Path(self._t.name).iterdir() if p.name.startswith("tally.db")], [])

    def test_a_failing_check_does_not_stop_the_others(self):
        with mock.patch.object(selftest, "NEEDED", ["missing.file"]):
            r = selftest.run(network=False)
        self.assertEqual(len(r["checks"]), 7)
        self.assertTrue(next(c for c in r["checks"] if c["name"] == "Database")["ok"])

    def test_the_command_line_writes_a_json_file_and_sets_the_exit_code(self):
        out = Path(self._t.name) / "result.json"
        env = dict(os.environ, THECOUNTING_HOME=self._t.name)
        p = subprocess.run([sys.executable, str(ROOT / "run_thecounting.py"), "--selftest", str(out), "--offline"],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        data = json.loads(out.read_text())
        self.assertTrue(data["ok"])
        self.assertIn("The Counting self-check", p.stdout)

    def test_the_command_line_runs_while_the_app_is_open(self):
        # it must not take the "already running" lock, so it can be run on a machine where the app is open
        env = dict(os.environ, THECOUNTING_HOME=self._t.name)
        p = subprocess.run([sys.executable, str(ROOT / "run_thecounting.py"), "--selftest", "--offline"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0)
        self.assertFalse((Path(self._t.name) / "thecounting.log").exists())     # and it starts nothing else


class Certificates(unittest.TestCase):
    """A packaged Mac app often finds no certificates at all. The bundled set must then be used."""

    def fake_context(self, count):
        ctx = mock.MagicMock()
        ctx.cert_store_stats.return_value = {"x509_ca": count, "x509": count, "crl": 0}
        return ctx

    def test_a_computer_with_no_certificates_gets_the_bundled_set(self):
        ctx = self.fake_context(0)
        with mock.patch.object(ssl, "create_default_context", return_value=ctx), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TALLY_CA_FILE", None)
            out = netfix.context()
        self.assertIs(out, ctx)
        ctx.load_verify_locations.assert_called_once()
        import certifi
        self.assertEqual(ctx.load_verify_locations.call_args.kwargs["cafile"], certifi.where())
        self.assertTrue(Path(certifi.where()).is_file())

    def test_a_computer_with_certificates_keeps_its_own(self):
        ctx = self.fake_context(140)
        with mock.patch.object(ssl, "create_default_context", return_value=ctx):
            os.environ.pop("TALLY_CA_FILE", None)
            netfix.context()
        ctx.load_verify_locations.assert_not_called()

    def test_a_missing_bundle_does_not_crash_the_app(self):
        ctx = self.fake_context(0)
        with mock.patch.object(ssl, "create_default_context", return_value=ctx), mock.patch.dict(sys.modules, {"certifi": None}):
            os.environ.pop("TALLY_CA_FILE", None)
            self.assertIs(netfix.context(), ctx)

    def test_the_test_override_still_wins(self):
        with mock.patch.dict(os.environ, {"TALLY_CA_FILE": str(Path(__file__).parent / "ca.pem")}):
            with mock.patch.object(ssl, "create_default_context", return_value=self.fake_context(0)) as m:
                netfix.context()
        self.assertEqual(m.call_args.kwargs["cafile"], str(Path(__file__).parent / "ca.pem"))

    def test_certifi_is_listed_for_the_builds(self):
        self.assertIn("certifi", (ROOT / "requirements.txt").read_text())
        for f in ("build.bat", "build.sh", ".github/workflows/build.yml"):
            self.assertIn("--collect-data certifi", (ROOT / f).read_text(), f)


if __name__ == "__main__":
    unittest.main()
