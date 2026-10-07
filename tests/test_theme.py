"""Theme, fonts, the rename, and the colour contrast of the palette."""
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

FAKE = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % FAKE.server_address[1]

from tally_app import paths  # noqa: E402
from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service  # noqa: E402
from tally_app.tmdb import TMDB  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "tally_app" / "web"


def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tokens(block):
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;", block))


class Palette(unittest.TestCase):
    css = (WEB / "style.css").read_text(encoding="utf-8")

    def block(self, opener):
        i = self.css.index(opener)
        return self.css[i:self.css.index("}", i)]

    def setUp(self):
        self.light = tokens(self.block(':root,[data-theme="light"]{'))
        self.dark = tokens(self.block('[data-theme="dark"]{'))
        self.system_dark = tokens(self.block(":root:not([data-theme]){"))

    def test_both_modes_define_the_same_colours(self):
        self.assertGreater(len(self.light), 20)
        self.assertEqual(set(self.light), set(self.dark))

    def test_system_dark_matches_explicit_dark(self):
        self.assertEqual(self.system_dark, self.dark)

    def test_text_is_readable_in_both_modes(self):
        pairs = [("ink", "bg"), ("ink", "surf"), ("ink", "soft"), ("mut", "bg"), ("mut", "surf"), ("mut", "soft"),
                 ("on-blue", "blue"), ("on-yellow", "yellow"), ("on-teal", "teal"), ("blue", "surf"), ("blue", "bg"),
                 ("mauve", "surf"), ("warn-ink", "warn-bg"), ("err-ink", "err-bg"), ("bg", "ink"), ("on-plum", "plum")]
        for name, t in (("light", self.light), ("dark", self.dark)):
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5, "%s: %s on %s = %.2f" % (name, fg, bg, contrast(t[fg], t[bg])))

    def test_focus_ring_and_outlines_are_visible(self):
        for name, t in (("light", self.light), ("dark", self.dark)):
            self.assertGreaterEqual(contrast(t["focus"], t["bg"]), 3, name + " focus ring")
            self.assertGreaterEqual(contrast(t["ink"], t["bg"]), 7, name + " outline colour")
            self.assertGreaterEqual(contrast(t["edge"], t["bg"]), 3, name + " border colour")

    def test_the_two_modes_really_differ(self):
        self.assertLess(luminance(self.dark["bg"]), 0.05)
        self.assertGreater(luminance(self.light["bg"]), 0.5)

    def test_fonts_are_bundled_not_downloaded(self):
        for f in ("jost-latin-500-normal.woff2", "jost-latin-700-normal.woff2", "Jost-OFL-LICENSE.txt"):
            self.assertTrue((WEB / "fonts" / f).is_file(), f)
        self.assertNotIn("googleapis", self.css)


class Rename(unittest.TestCase):
    def test_the_old_name_is_gone_from_what_people_read(self):
        allowed = ("X-Tally-Token", "tally-token", "tally_app", "tally.db", "tally-*", "tally-export")
        for f in (WEB / "index.html", WEB / "app.js", ROOT / "GETTING_STARTED.md"):
            text = f.read_text(encoding="utf-8")
            for a in allowed:
                text = text.replace(a, "")
            self.assertNotRegex(text, r"[Tt]ally", f.name)
        self.assertIn("The Counting", (WEB / "index.html").read_text())

    def test_data_folder_names(self):
        self.assertEqual(paths.default_base("win32", {"APPDATA": "C:/A"}, "C:/u").as_posix(), "C:/A/The Counting")
        self.assertTrue(paths.default_base("darwin", {}, "/Users/s").as_posix().endswith("Application Support/The Counting"))

    def test_old_folder_is_moved_once_with_everything_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "Tally", Path(tmp) / "The Counting"
            old.mkdir()
            (old / "tally.db").write_text("data")
            (old / "backups").mkdir()
            self.assertEqual(paths.migrate_legacy(new, old), new)
            self.assertEqual((new / "tally.db").read_text(), "data")
            self.assertTrue((new / "backups").is_dir())
            self.assertFalse(old.exists())

    def test_existing_new_folder_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "Tally", Path(tmp) / "The Counting"
            old.mkdir()
            new.mkdir()
            self.assertEqual(paths.migrate_legacy(new, old), new)
            self.assertTrue(old.exists())

    def test_if_the_move_fails_the_old_folder_keeps_being_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / "Tally", Path(tmp) / "The Counting"
            old.mkdir()
            with mock.patch.object(Path, "rename", side_effect=OSError("locked")):
                self.assertEqual(paths.migrate_legacy(new, old), old)
            self.assertTrue(old.exists())

    def test_nothing_to_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(paths.migrate_legacy(Path(tmp) / "The Counting", Path(tmp) / "Tally"), Path(tmp) / "The Counting")


class ThemeServer(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        tmp = Path(self._t.name)
        self.db = Database(tmp / "t.db")
        self.svc = Service(self.db, TMDB(lambda: fake_tmdb.GOOD_KEY), BackupManager(self.db, tmp))
        self.srv = TallyServer(self.svc, tmp)
        self.srv.start()
        self.base = self.srv.url.rstrip("/")

    def tearDown(self):
        self.srv.shutdown()
        self.db.close()
        self._t.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, headers={"X-Tally-Token": self.srv.token, "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def page(self):
        with urllib.request.urlopen(self.base + "/") as r:
            return r.read().decode()

    def test_default_follows_the_device(self):
        self.assertEqual(self.call("GET", "/api/state")[1]["theme"], "system")
        self.assertNotIn("data-theme", self.page())

    def test_choice_is_saved_and_applied_before_the_page_draws(self):
        self.assertEqual(self.call("POST", "/api/settings/theme", {"theme": "dark"})[1]["theme"], "dark")
        self.assertIn('<html lang="en" data-theme="dark">', self.page())
        self.call("POST", "/api/settings/theme", {"theme": "light"})
        self.assertIn('data-theme="light"', self.page())
        self.call("POST", "/api/settings/theme", {"theme": "system"})
        self.assertNotIn("data-theme", self.page())

    def test_bad_value_is_refused(self):
        code, r = self.call("POST", "/api/settings/theme", {"theme": "neon"})
        self.assertEqual(code, 400)
        self.assertIn("Unknown", r["error"])
        self.assertEqual(self.call("GET", "/api/state")[1]["theme"], "system")

    def test_a_backup_restore_keeps_the_current_theme(self):
        self.svc.add_show(100, "watching")
        snap = self.svc.backups.snapshot("manual")
        self.call("POST", "/api/settings/theme", {"theme": "dark"})
        self.svc.backups.restore(snap.name)
        self.assertEqual(self.call("GET", "/api/state")[1]["theme"], "dark")

    def test_fonts_are_served_and_nothing_else_under_fonts(self):
        with urllib.request.urlopen(self.base + "/fonts/jost-latin-700-normal.woff2") as r:
            self.assertEqual(r.headers["Content-Type"], "font/woff2")
            self.assertEqual(r.read(4), b"wOF2")
        for bad in ("/fonts/../app.js", "/fonts/nothing.woff2", "/fonts/Jost-OFL-LICENSE.txt", "/fonts/a/b.woff2"):
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(self.base + bad)
            self.assertEqual(c.exception.code, 404)

    def test_the_page_uses_the_new_name_and_no_external_resources(self):
        html = self.page()
        self.assertIn("<title>The Counting</title>", html)
        self.assertNotRegex(html, r'(src|href)="https?://')


if __name__ == "__main__":
    unittest.main()


class DesignRules(unittest.TestCase):
    """Guards for the design decisions: each colour has one job, and the wide layouts exist."""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    def rule(self, selector):
        i = self.css.index(selector + "{")
        return self.css[i:self.css.index("}", i)]

    def test_progress_is_teal_and_charts_are_blue(self):
        self.assertIn("background:var(--teal)", self.rule(".bar i"))
        self.assertIn("background:var(--blue)", self.rule(".bars .bar i"))

    def test_red_is_kept_for_the_next_episode_and_attention(self):
        self.assertIn("var(--red)", self.rule(".sq i.next,.sqi.next"))
        self.assertNotIn("var(--red)", self.rule(".avatar"))
        self.assertNotIn("var(--red)", self.rule(".kpi"))

    def test_placeholder_posters_use_four_calm_colours(self):
        for k in "0123":
            self.assertIn('.poster[data-k="%s"]' % k, self.css)
        self.assertNotIn('.poster[data-k="4"]', self.css)
        self.assertIn("% 4", self.js)

    def test_desktop_width_is_used(self):
        self.assertIn("max-width:1320px", self.rule("main"))
        self.assertIn("repeat(auto-fill,minmax(min(100%,230px)", self.rule(".pgrid"))
        self.assertIn("grid-template-columns:minmax(0,1fr) 380px", self.rule(".showcols"))

    def test_phone_layout_collapses_the_show_page_and_library(self):
        self.assertIn("@media (max-width:1000px){\n  .showcols{grid-template-columns:1fr}", self.css)
        self.assertIn(".pgrid{grid-template-columns:repeat(2,minmax(0,1fr))", self.css)

    def test_artwork_hero_has_a_fade_and_a_poster_fallback(self):
        self.assertIn("linear-gradient(to bottom", self.rule(".showhero .herofade"))
        self.assertIn("blur(", self.rule(".showhero.fromposter .heroimg"))
        self.assertIn('"/img/w1280"', self.js)
        self.assertIn("fromposter", self.js)

    def test_the_library_shows_one_square_per_episode_with_a_cap(self):
        self.assertIn("Math.min(total, 48)", self.js)
        self.assertIn("function countSquares", self.js)
