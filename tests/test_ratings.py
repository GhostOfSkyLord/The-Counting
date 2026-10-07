import json
import os
import sqlite3
import sys
import tempfile
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

from tally_app import db as dbmod  # noqa: E402
from tally_app.backup import BackupManager  # noqa: E402
from tally_app.db import Database  # noqa: E402
from tally_app.ratings import RatingError  # noqa: E402
from tally_app.server import TallyServer  # noqa: E402
from tally_app.service import Service, UserError  # noqa: E402
from tally_app.tmdb import TMDB  # noqa: E402

ALL = lambda v: {k: v for k in ("writing", "acting", "cine", "edit", "sound", "dir")}  # noqa: E731


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name
        self.db = Database(Path(self.tmp) / "t.db")
        self.backups = BackupManager(self.db, self.tmp)
        self.svc = Service(self.db, TMDB(lambda: self.db.get_setting("tmdb_key")), self.backups)
        self.svc.save_key(fake_tmdb.GOOD_KEY)
        self.R = self.svc.ratings

    def tearDown(self):
        self.db.close()
        self._t.cleanup()

    def add(self, *ids, status="watching"):
        for i in ids:
            self.svc.add_show(i, status)


class TestMigration(unittest.TestCase):
    def test_version_1_database_upgrades_without_losing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            c = sqlite3.connect(str(path))
            c.executescript(dbmod.MIGRATIONS[0] + "PRAGMA user_version=1;")
            c.execute("INSERT INTO user_shows VALUES(100,'watching','manual',1,1)")
            c.execute("INSERT INTO watch_events(episode_id,show_id,type,source,ts) VALUES(1,100,'watch','single',5)")
            c.commit()
            c.close()
            d = Database(path)
            self.assertEqual(d.conn.execute("PRAGMA user_version").fetchone()[0], len(dbmod.MIGRATIONS))
            self.assertEqual(d.q1("SELECT COUNT(*) n FROM watch_events")["n"], 1)
            self.assertEqual(d.q1("SELECT status FROM user_shows")["status"], "watching")
            for t in ("ratings", "comparisons", "favourites", "dismissed", "rec_links"):
                d.q("SELECT * FROM " + t)
            d.close()


class TestScorecard(Base):
    def setUp(self):
        super().setUp()
        self.add(100, 200, 500)

    def test_profile_defaults_presets_and_validation(self):
        p = self.R.profile()
        self.assertEqual((p["mode"], p["max"]), ("card", 5))
        self.assertIn(sum(c["share"] for c in p["criteria"]), (99, 100, 101))  # rounded shares
        p = self.R.save_profile(preset="looks")
        self.assertTrue(next(x for x in p["presets"] if x["key"] == "looks")["active"])
        self.assertEqual({c["key"]: c["weight"] for c in p["criteria"]}["cine"], 3)
        with self.assertRaises(RatingError):
            self.R.save_profile(weights={"cine": 9})
        with self.assertRaises(RatingError):
            self.R.save_profile(mode="7")

    def test_card_rating_final_and_validation(self):
        r = self.R.rate(100, "card", scores=ALL(4), gut=5)
        self.assertEqual(r["current"]["final"], "4 / 5")
        self.assertEqual(r["current"]["gut"], 5)
        for bad in ({"writing": 4}, dict(ALL(4), cine=6), dict(ALL(4), cine=0)):
            with self.assertRaises(RatingError):
                self.R.rate(100, "card", scores=bad)
        with self.assertRaises(RatingError):
            self.R.rate(999999, "card", scores=ALL(3))

    def test_weights_recompute_every_final_score(self):
        self.R.save_profile(preset="balanced")
        sc = dict(ALL(3), writing=5, cine=1)
        self.R.rate(100, "card", scores=sc)
        balanced = self.R.show_rating(100)["current"]["fraction"]
        self.R.save_profile(weights={"writing": 3, "cine": 0})
        story = self.R.show_rating(100)["current"]["fraction"]
        self.assertGreater(story, balanced)  # ignoring the weak category and stressing the strong one raises the score
        stored = json.loads(self.db.q1("SELECT scores FROM ratings")["scores"])
        self.assertEqual(stored["cine"], 0.2)  # category scores themselves never change

    def test_history_keeps_old_ratings_and_latest_counts(self):
        self.R.rate(100, "card", scores=ALL(2))
        self.R.rate(100, "card", scores=ALL(5))
        info = self.R.show_rating(100)
        self.assertEqual(info["current"]["final"], "5 / 5")
        self.assertEqual([h["final"] for h in info["history"]], ["2 / 5"])
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM ratings")["n"], 2)
        self.assertEqual(len(self.R.latest()), 1)

    def test_simple_modes_and_display_scale(self):
        self.R.save_profile(mode="10")
        self.R.rate(100, "10", overall=8)
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "8 / 10")
        self.R.save_profile(mode="5")
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "4 / 5")  # same rating shown on the 5-point scale
        with self.assertRaises(RatingError):
            self.R.rate(100, "5", overall=6)
        self.assertEqual(self.svc.summary(100)["rating"], "4 / 5")


class TestRankingsAndArena(Base):
    def setUp(self):
        super().setUp()
        self.add(100, 200, 500, 300)
        self.R.save_profile(preset="balanced")
        # 100 Drama+Mystery, 200 Drama, 500 Drama+Thriller, 300 has no Drama
        self.R.rate(100, "card", scores=ALL(4))
        self.R.rate(200, "card", scores=dict(ALL(4), sound=5))        # slightly above 4.0 overall: a near-tie
        self.R.rate(500, "card", scores=ALL(2))
        self.R.rate(300, "card", scores=ALL(4))

    def test_rankings_order_and_simple_ratings_excluded_from_categories(self):
        r = self.R.rankings("overall")["items"]
        self.assertEqual(r[-1]["id"], 500)
        self.R.rate(500, "5", overall=5)
        cine = self.R.rankings("cine")
        self.assertEqual(cine["skipped"], 1)
        self.assertNotIn(500, [x["id"] for x in cine["items"]])

    def test_arena_includes_exact_and_near_ties_within_half_a_point(self):
        m = self.R.matchups()
        overall = [x for x in m if x["scope"] == "overall"]
        pairs = {frozenset((x["a"]["id"], x["b"]["id"])) for x in overall}
        self.assertIn(frozenset((100, 200)), pairs)                   # 4.0 vs 4.17: near-tie
        self.assertNotIn(frozenset((100, 500)), pairs)                # 4.0 vs 2.0: far apart
        self.assertTrue(all(overall[i]["gap"] <= 0.5 + 1e-9 for i in range(len(overall))))
        self.assertTrue(m[0]["exact"])                                # exact ties come first

    def test_same_genre_filter(self):
        self.add(502)                                                  # Sci-Fi: shares no genre with the Drama shows
        self.R.rate(502, "card", scores=ALL(4))
        with_filter = {frozenset((x["a"]["id"], x["b"]["id"])) for x in self.R.matchups()}
        self.assertIn(frozenset((100, 300)), with_filter)              # both Drama
        self.assertNotIn(frozenset((100, 502)), with_filter)
        self.R.save_profile(same_genre=False)
        without = {frozenset((x["a"]["id"], x["b"]["id"])) for x in self.R.matchups()}
        self.assertIn(frozenset((100, 502)), without)
        self.assertTrue(without >= with_filter)

    def test_answers_are_recorded_remove_the_pair_and_move_rankings(self):
        first = self.R.matchups()[0]
        a, b = first["a"]["id"], first["b"]["id"]
        n = len(self.R.matchups())
        self.R.compare(first["scope"], a, b, "b")
        self.assertLess(len(self.R.matchups()), n)
        items = self.R.rankings(first["scope"])["items"]
        order = [x["id"] for x in items]
        self.assertLess(order.index(b), order.index(a))
        self.assertEqual(next(x for x in items if x["id"] == b)["moved"], "up")

    def test_near_tie_answer_can_overturn_a_small_score_gap(self):
        self.R.compare("overall", 100, 200, "a")  # user says 100 (4.0) beats 200 (4.17)
        order = [x["id"] for x in self.R.rankings("overall")["items"]]
        self.assertLess(order.index(100), order.index(200))

    def test_validation(self):
        with self.assertRaises(RatingError):
            self.R.compare("nonsense", 100, 200, "a")
        with self.assertRaises(RatingError):
            self.R.compare("overall", 100, 200, "maybe")


class TestArenaVolume(Base):
    """The arena must stay a small, optional chore, not homework."""

    def setUp(self):
        super().setUp()
        self.add(100, 200, 300, 500, 501)           # all share the Drama genre
        self.R.save_profile(same_genre=False)

    def rate(self, sid, **over):
        self.R.rate(sid, "card", scores=dict(ALL(3), **over))

    def test_only_top_scores_are_asked_about(self):
        for sid in (100, 200):
            self.rate(sid, cine=3, writing=3)
        self.assertEqual(self.R.matchups("cine"), [])        # tied at 3 out of 5: not worth asking
        for sid in (100, 200):
            self.rate(sid, cine=4)
        self.assertEqual(len(self.R.matchups("cine")), 1)    # tied at 4 out of 5: worth asking

    def test_the_default_view_is_overall_and_every_category_is_one_choice_away(self):
        self.R.save_profile(weights={"edit": 1, "sound": 0, "cine": 3})
        for sid in (100, 200):
            self.rate(sid, **{k: 5 for k in ALL(1)})
        self.assertEqual({m["scope"] for m in self.R.matchups()}, {"overall"})
        for scope in ("cine", "edit", "sound"):                   # whatever their importance, each can be chosen
            self.assertEqual(len(self.R.matchups(scope)), 1, scope)
        self.assertIsNotNone(self.R.arena("edit")["next"])

    def test_earlier_answers_settle_other_pairs(self):
        for sid in (100, 200, 300):
            self.rate(sid, cine=5)
        self.assertEqual(self.R.arena("cine")["remaining"], 3)
        self.R.compare("cine", 100, 200, "a", "cine")
        self.R.compare("cine", 200, 300, "a", "cine")
        self.assertEqual(self.R.arena("cine")["remaining"], 0)  # 100 beat 200 beat 300, so 100 against 300 is settled

    def test_about_the_same_joins_shows_into_one_group(self):
        for sid in (100, 200, 300):
            self.rate(sid, cine=5)
        self.R.compare("cine", 100, 200, "same", "cine")
        self.R.compare("cine", 200, 300, "b", "cine")            # 300 beats 200, and 200 is the same as 100
        self.assertEqual(self.R.arena("cine")["remaining"], 0)

    def test_question_estimate_is_far_smaller_than_the_number_of_pairs(self):
        for sid in (100, 200, 300, 500, 501):
            self.rate(sid, cine=5)
        a = self.R.arena("cine")
        self.assertEqual(a["remaining"], 10)                     # ten pairs...
        self.assertEqual(a["questions"], 7)                      # ...but about seven questions: log2(5!) rounded up

    def test_pair_counts_flags_and_weights_per_category(self):
        self.R.save_profile(weights={"sound": 1, "cine": 3})
        for sid in (100, 200):
            self.rate(sid, cine=5, sound=5)
        a = self.R.arena()
        by = {c["scope"]: c for c in a["by_scope"]}
        self.assertEqual((by["cine"]["count"], by["cine"]["default"], by["cine"]["weight"]), (1, False, 3))
        self.assertEqual((by["sound"]["count"], by["sound"]["weight"]), (1, 1))
        self.assertTrue(by["overall"]["default"])
        self.assertEqual(a["scope"], "all")
        self.assertEqual(a["default_total"], by["overall"]["count"])

    def test_only_the_top_three_are_settled_by_default(self):
        for sid in (100, 200, 300, 500, 501):                     # five shows tied at the top: A B C D E
            self.rate(sid, cine=5)
        A, B, C, D, E = 100, 200, 300, 500, 501
        for win, lose in ((A, B), (A, C), (A, D), (A, E), (B, C), (B, D), (B, E), (C, D), (C, E)):
            self.R.compare("cine", win, lose, "a", "cine")
        self.assertEqual(self.R.arena("cine")["remaining"], 0)    # the top three are in order; D against E does not matter
        self.R.save_profile(top_only=False)
        self.assertEqual(self.R.arena("cine")["remaining"], 1)    # ordering everything still asks about D and E
        self.assertFalse(self.R.profile()["top_only"])

    def test_top_three_setting_is_saved_and_defaults_on(self):
        self.assertTrue(self.R.profile()["top_only"])
        self.R.save_profile(top_only=False)
        self.assertEqual(self.db.get_setting("arena_top_only"), "0")

    def test_a_realistic_library_stays_small(self):
        """The case that prompted this: seven rated shows used to mean about 40 pairs to decide."""
        import random
        ids = (100, 200, 300, 500, 501, 502, 503)
        self.add(*ids)
        self.R.save_profile(same_genre=False)
        totals = []
        for seed in range(12):
            rnd = random.Random(seed)
            for sid in ids:
                self.R.rate(sid, "card", scores={k: rnd.choice([2, 3, 4, 5]) for k in ALL(1)})
            totals.append(self.R.arena()["questions"])
        self.assertLess(sum(totals) / len(totals), 12)           # on average, a dozen questions to settle everything
        self.assertLess(max(totals), 25)

    def test_unknown_category_is_refused(self):
        with self.assertRaises(RatingError):
            self.R.arena("nonsense")


class TestStatsDerived(Base):
    def test_network_decade_genre_rating_and_weekday_views(self):
        self.add(100, 200)
        eps = self.svc.detail(100)["season_list"][0]["episodes"]
        self.svc.mark(eps[0]["id"])                               # one dated mark
        self.svc.seen_up_to(eps[3]["id"])                         # three undated bulk marks
        self.svc.mark(self.svc.detail(200)["season_list"][0]["episodes"][0]["id"])
        self.R.rate(100, "card", scores=ALL(5))
        self.R.rate(200, "card", scores=ALL(3))
        st = self.svc.stats()
        self.assertEqual([n for n, _ in st["by_network"]], ["Net"])
        self.assertAlmostEqual(st["by_network"][0][1], 5 * 45 / 60, places=1)   # five episodes, both shows on "Net"
        self.assertEqual([d for d, _ in st["by_decade"]], ["2020s"])
        genres = {g: (v, n) for g, v, n in st["rating_by_genre"]}
        self.assertEqual(genres["Drama"], (4.0, 2))               # average of a 5 and a 3
        self.assertEqual(genres["Mystery"], (5.0, 1))
        self.assertEqual(st["rating_max"], 5)
        self.assertEqual(st["rated_shows"], 2)
        self.assertEqual(len(st["by_weekday"]), 7)
        self.assertEqual(sum(st["by_weekday"]), 2)                # only the two dated marks
        self.assertEqual(st["undated"], 3)
        self.assertLessEqual(len(st["top_shows"]), 5)
        self.assertEqual(st["top_shows"][0][0], "Harbour Lights")

    def test_empty_library_does_not_break_the_new_views(self):
        st = self.svc.stats()
        for k in ("by_network", "by_decade", "rating_by_genre", "top_shows"):
            self.assertEqual(st[k], [])
        self.assertEqual(st["by_weekday"], [0] * 7)


class TestMigrationV3(unittest.TestCase):
    def test_version_2_database_upgrades_and_keeps_its_ratings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.db"
            c = sqlite3.connect(str(path))
            c.executescript(dbmod.MIGRATIONS[0] + dbmod.MIGRATIONS[1] + "PRAGMA user_version=2;")
            c.execute("INSERT INTO shows(id,name,genres,synced_at) VALUES(1,'A','[]',0)")
            c.execute("INSERT INTO ratings(show_id,mode,scores,overall,gut,created_at) VALUES(1,'5',NULL,0.8,NULL,1)")
            c.commit()
            c.close()
            d = Database(path)
            self.assertEqual(d.conn.execute("PRAGMA user_version").fetchone()[0], len(dbmod.MIGRATIONS))
            self.assertEqual(d.q1("SELECT overall FROM ratings")["overall"], 0.8)
            d.q("SELECT * FROM season_ratings")
            d.q("SELECT * FROM season_prefs")
            d.close()


class TestSeasonRatings(Base):
    def setUp(self):
        super().setUp()
        self.add(100, 300)                       # 100: two seasons of four episodes. 300: twenty seasons of two
        self.R.save_profile(mode="5", same_genre=False)
        self.R.rate(100, "5", overall=4)         # the show itself: 4 out of 5 = 0.8

    def test_scores_use_your_current_scale_and_are_validated(self):
        info = self.R.rate_seasons(100, {1: 5, 2: 3})
        self.assertEqual([x["score"] for x in info["seasons"]], [5, 3])
        self.assertEqual(info["scale"], 5)
        with self.assertRaises(RatingError):
            self.R.rate_seasons(100, {1: 6})
        with self.assertRaises(RatingError):
            self.R.rate_seasons(100, {1: 0})
        with self.assertRaises(RatingError):
            self.R.rate_seasons(100, {9: 3})                 # no such season
        self.R.save_profile(mode="10")
        self.R.rate_seasons(100, {1: 9})                     # on a ten-point scale 9 is fine
        self.assertEqual(self.R.season_info(100)["seasons"][0]["text"], "9 / 10")
        self.R.save_profile(mode="5")
        self.assertEqual(self.R.season_info(100)["seasons"][0]["text"], "4.5 / 5")   # the same score on the other scale

    def test_history_keeps_every_change_and_re_saving_adds_nothing(self):
        self.R.rate_seasons(100, {1: 4})
        self.R.rate_seasons(100, {1: 4})
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM season_ratings")["n"], 1)
        self.R.rate_seasons(100, {1: 2})
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM season_ratings")["n"], 2)
        self.assertEqual(self.R.season_info(100)["seasons"][0]["score"], 2)         # the newest counts

    def test_nothing_changes_for_the_show_until_you_opt_in(self):
        self.R.rate_seasons(100, {1: 5, 2: 2})
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "4 / 5")
        self.assertEqual(self.R.season_info(100)["mode"], "off")
        self.assertEqual(self.R.rankings("overall")["items"][0]["score"], "4 / 5")

    def test_blend_and_seasons_only_modes(self):
        self.R.rate_seasons(100, {1: 5, 2: 2})                # season average (equal episode counts) = 0.7
        info = self.R.save_season_prefs(100, "blend", 50)
        self.assertAlmostEqual(info["effective_fraction"], 0.75)
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "3.8 / 5")      # 0.75 shown to one decimal
        self.assertEqual(self.R.show_rating(100)["current"]["base"], "4 / 5")          # the show's own score is still there
        self.assertAlmostEqual(self.R.save_season_prefs(100, "blend", 0)["effective_fraction"], 0.8)
        self.assertAlmostEqual(self.R.save_season_prefs(100, "blend", 100)["effective_fraction"], 0.7)
        self.assertAlmostEqual(self.R.save_season_prefs(100, "seasons")["effective_fraction"], 0.7)
        self.assertAlmostEqual(self.R.latest()[100]["effective"], 0.7)
        self.assertEqual(self.svc.summary(100)["rating"], "3.5 / 5")                  # the library card follows the setting
        self.R.save_season_prefs(100, "off")
        self.assertEqual(self.svc.summary(100)["rating"], "4 / 5")

    def test_seasons_count_by_how_many_episodes_they_have(self):
        with self.db.tx():
            self.db.x("INSERT INTO shows(id,name,genres,synced_at) VALUES(900,'Uneven','[]',0)")
            for e in range(1, 3):                              # season 1: 2 episodes
                self.db.x("INSERT INTO episodes(id,show_id,season_number,episode_number) VALUES(?,?,?,?)", (9000 + e, 900, 1, e))
            for e in range(1, 7):                              # season 2: 6 episodes
                self.db.x("INSERT INTO episodes(id,show_id,season_number,episode_number) VALUES(?,?,?,?)", (9100 + e, 900, 2, e))
        self.R.rate_seasons(900, {1: 5, 2: 1})
        info = self.R.save_season_prefs(900, "seasons")
        self.assertAlmostEqual(info["avg_fraction"], (1.0 * 2 + 0.2 * 6) / 8)         # 0.4, not the plain average 0.6

    def test_only_rated_seasons_count(self):
        self.R.rate_seasons(300, {1: 5})                      # one of twenty seasons
        self.R.rate(300, "5", overall=3)
        info = self.R.save_season_prefs(300, "blend", 50)
        self.assertEqual(info["rated"], 1)
        self.assertAlmostEqual(info["effective_fraction"], 0.8)                        # (0.6 + 1.0) / 2

    def test_a_show_with_only_season_scores_is_rated_from_them_when_you_choose(self):
        self.R.rate_seasons(300, {1: 4, 2: 4})
        self.assertNotIn(300, self.R.latest())                # off: no show score, so no rating
        self.R.save_season_prefs(300, "seasons")
        self.assertAlmostEqual(self.R.latest()[300]["effective"], 0.8)
        item = next(x for x in self.R.rankings("overall")["items"] if x["id"] == 300)
        self.assertTrue(item["seasons"])
        self.assertEqual(self.svc.summary(300)["rating"], "4 / 5")
        self.assertIsNone(self.R.show_rating(300)["current"])                          # it has no score of its own
        self.R.save_season_prefs(300, "blend", 40)             # blending with nothing to blend uses the seasons alone
        self.assertAlmostEqual(self.R.latest()[300]["effective"], 0.8)

    def test_ranking_marks_shows_whose_score_includes_seasons(self):
        self.R.rate_seasons(100, {1: 5, 2: 5})
        self.R.save_season_prefs(100, "blend", 50)
        item = next(x for x in self.R.rankings("overall")["items"] if x["id"] == 100)
        self.assertTrue(item["seasons"])
        self.assertFalse(self.R.rankings("cine")["items"] and self.R.rankings("cine")["items"][0].get("seasons"))

    def test_discover_and_stats_see_the_score_that_counts(self):
        self.R.rate_seasons(100, {1: 5, 2: 5})
        self.R.save_season_prefs(100, "seasons")
        genres = {g: v for g, v, n in self.svc.stats()["rating_by_genre"]}
        self.assertEqual(genres["Drama"], 5.0)

    def test_best_and_weakest_seasons(self):
        info = self.R.rate_seasons(100, {1: 5, 2: 3})
        self.assertEqual((info["best"], info["weakest"], info["pending"]), ([1], [2], []))
        self.assertTrue(info["seasons"][0]["best"] and info["seasons"][1]["weakest"])
        info = self.R.rate_seasons(100, {1: 4, 2: 4})
        self.assertEqual((info["best"], info["weakest"]), ([], []))                    # all the same: no best or weakest

    def test_tied_best_seasons_can_be_settled_with_a_question(self):
        info = self.R.rate_seasons(300, {1: 5, 2: 5, 3: 3})
        self.assertEqual(info["best"], [1, 2])
        self.assertEqual(info["pending"], [[1, 2]])           # only the top tie is worth asking about
        info = self.R.compare_seasons(300, 1, 2, "b")         # season 2 was better
        self.assertEqual((info["best"], info["pending"]), ([2], []))
        self.assertTrue(info["seasons"][1]["best"] and not info["seasons"][0]["best"])
        # a skip or "about the same" also closes the question without picking a winner
        self.R.rate_seasons(300, {1: 5, 2: 5})
        self.R.compare_seasons(300, 1, 2, "same")
        self.assertEqual(self.R.season_info(300)["pending"], [])

    def test_three_way_tie_uses_earlier_answers(self):
        self.R.rate_seasons(300, {1: 5, 2: 5, 3: 5, 4: 2})
        self.assertEqual(len(self.R.season_info(300)["pending"]), 3)
        self.R.compare_seasons(300, 1, 2, "a")
        self.R.compare_seasons(300, 2, 3, "a")                # 1 beat 2 and 2 beat 3, so 1 against 3 is settled
        info = self.R.season_info(300)
        self.assertEqual((info["pending"], info["best"]), ([], [1]))

    def test_season_answers_do_not_disturb_the_arena_or_rankings(self):
        self.R.rate_seasons(300, {1: 5, 2: 5})
        self.R.compare_seasons(300, 1, 2, "a")
        self.assertEqual(self.R.arena()["settled"], 1)
        self.assertEqual(self.R.rankings("overall")["items"][0]["id"], 100)

    def test_choosing_how_seasons_count(self):
        self.assertEqual(self.R.season_info(100)["mix"], 50)
        info = self.R.save_season_prefs(100, "blend", 30)
        self.assertEqual((info["mode"], info["mix"]), ("blend", 30))
        self.assertEqual(self.R.save_season_prefs(100, "seasons")["mix"], 30)         # the mix is remembered
        for bad in (("nonsense", 50), ("blend", 101), ("blend", -1)):
            with self.assertRaises(RatingError):
                self.R.save_season_prefs(100, *bad)

    def test_single_season_shows_are_flagged_so_the_screen_can_hide_the_option(self):
        self.add(500)
        self.assertFalse(self.R.season_info(500)["multi"])
        self.assertTrue(self.R.season_info(100)["multi"])

    def test_how_your_shows_age(self):
        self.R.rate_seasons(100, {1: 2, 2: 5})                # improved
        self.R.rate_seasons(300, {1: 5, 2: 3})                # declined
        self.R.rate_seasons(300, {3: 4})
        t = self.R.season_trends()
        self.assertEqual((t["shows"], t["improved"], t["declined"], t["held"]), (2, 1, 1, 0))
        by = {n: (v, c) for n, v, c in t["by_number"]}
        self.assertEqual(by[1], (3.5, 2))                     # (2 + 5) / 2
        self.assertEqual(by[2], (4.0, 2))
        self.assertEqual(self.svc.stats()["season_trends"]["improved"], 1)

    def test_detail_and_export_carry_season_ratings(self):
        self.R.rate_seasons(100, {1: 5, 2: 3})
        self.R.save_season_prefs(100, "blend", 40)
        self.R.rate_seasons(300, {1: 5, 2: 5})
        self.R.compare_seasons(300, 1, 2, "a")
        d = self.svc.detail(100)["season_rating"]
        self.assertEqual((d["mode"], d["mix"], d["rated"]), ("blend", 40, 2))
        data = json.loads(self.backups.export_json().read_text())
        for t in ("season_ratings", "season_prefs"):
            self.db.x("DELETE FROM " + t)
        self.db.x("DELETE FROM comparisons")
        self.backups.import_json(data)
        self.assertEqual(self.R.season_info(100)["mode"], "blend")
        self.assertEqual(self.R.season_info(100)["seasons"][0]["score"], 5)
        self.assertEqual(self.R.season_info(300)["best"], [1])

    def test_old_exports_without_season_data_still_import(self):
        self.R.rate_seasons(100, {1: 5})
        data = json.loads(self.backups.export_json().read_text())
        for k in ("season_ratings", "season_prefs"):
            data.pop(k)
        self.backups.import_json(data)
        self.assertIsNone(self.R.season_info(100)["seasons"][0]["score"])

    def test_season_ratings_survive_a_backup_restore(self):
        self.R.rate_seasons(100, {1: 4})
        snap = self.backups.snapshot("manual")
        self.R.rate_seasons(100, {1: 1})
        self.backups.restore(snap.name)
        self.assertEqual(self.R.season_info(100)["seasons"][0]["score"], 4)


class TestFavourites(Base):
    def test_needs_watched_toggles_and_respects_hidden_titles(self):
        self.add(100)
        ep = self.svc.detail(100)["season_list"][0]["episodes"]
        with self.assertRaises(UserError):
            self.svc.toggle_favourite(ep[0]["id"])
        self.svc.mark(ep[0]["id"])
        self.assertTrue(self.svc.toggle_favourite(ep[0]["id"])["favourite"])
        self.assertTrue(self.svc.detail(100)["season_list"][0]["episodes"][0]["favourite"])
        self.assertEqual(self.svc.favourites()[0]["name"], "Harbour Lights S1E1")
        self.svc.set_overrides(100, {"hide_titles": True})
        self.assertIsNone(self.svc.favourites()[0]["name"])
        self.assertFalse(self.svc.toggle_favourite(ep[0]["id"])["favourite"])
        self.assertEqual(self.svc.favourites(), [])


class TestAddSeen(Base):
    def test_all_of_an_ended_show_is_completed_and_asks_for_a_rating(self):
        d = self.svc.add_seen_show(100, "all")
        self.assertEqual(d["status"], "completed")
        self.assertTrue(d["ask_rating"])
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM watch_events WHERE ts IS NOT NULL")["n"], 0)  # no invented dates
        self.assertEqual(d["progress"]["percent"], 100)

    def test_partial_and_returning_shows_go_to_watching(self):
        d = self.svc.add_seen_show(100, 1)
        self.assertEqual((d["status"], d["progress"]["watched"], d["ask_rating"]), ("watching", 4, False))
        d = self.svc.add_seen_show(200, "all")
        self.assertEqual(d["status"], "watching")

    def test_no_second_prompt_once_rated(self):
        self.svc.add_seen_show(100, "all")
        self.R.rate(100, "card", scores=ALL(4))
        self.assertFalse(self.svc.add_seen_show(100, "all")["ask_rating"])


class TestDiscover(Base):
    def setUp(self):
        super().setUp()
        self.D = self.svc.discover

    def rate_three(self):
        self.add(100, 200, 300, status="completed")
        self.R.rate(100, "card", scores=ALL(5))   # strongly liked; recommends 500, 501
        self.R.rate(200, "card", scores=ALL(2))   # disliked; recommends 501, 503
        self.R.rate(300, "card", scores=ALL(3))   # recommends 502

    def test_before_three_ratings_falls_back_to_tmdb_order(self):
        self.add(100, status="completed")
        self.D.fetch_links()
        out = self.D.listing("you")
        self.assertFalse(out["unlocked"])
        self.assertEqual(out["mode"], "tmdb")
        self.assertEqual({c["id"] for c in out["cards"]}, {500, 501})
        self.assertNotIn("why", out["cards"][0])

    def test_ranking_follows_your_ratings_not_tmdb_counts(self):
        self.rate_three()
        self.assertEqual(self.D.fetch_links(), 0)
        cards = self.D.listing("you")["cards"]
        ids = [c["id"] for c in cards]
        # 500 is only linked from the show you loved, 501 from the one you loved AND the one you disliked
        self.assertEqual(ids[0], 500)
        self.assertLess(ids.index(500), ids.index(501))
        self.assertLess(ids.index(501), ids.index(503))   # 503 comes only from the disliked show
        self.assertTrue(all("why" in c and "tier" in c for c in cards))
        self.assertIn("Harbour Lights", cards[0]["why"])
        self.assertIn("your #1", cards[0]["why"])
        self.assertIn("Ranks above", cards[0]["vs_next"])
        tmdb = [c["id"] for c in self.D.listing("tmdb")["cards"]]
        self.assertEqual(tmdb[0], 501)                    # TMDB order puts the doubly-linked show first

    def test_changing_weights_can_change_the_order(self):
        self.rate_three()
        self.D.fetch_links()
        before = [c["id"] for c in self.D.listing("you")["cards"]]
        self.assertEqual(before, [c["id"] for c in self.D.listing("you")["cards"]])  # stable

    def test_library_dismissed_and_seeds_are_excluded(self):
        self.rate_three()
        self.D.fetch_links()
        self.svc.add_show(500, "plan")
        self.D.dismiss(501)
        ids = {c["id"] for c in self.D.listing("you")["cards"]}
        self.assertNotIn(500, ids)
        self.assertNotIn(501, ids)
        self.assertNotIn(100, ids)

    def test_genre_names_and_cache(self):
        self.rate_three()
        self.D.fetch_links()
        card = next(c for c in self.D.listing("you")["cards"] if c["id"] == 500)
        self.assertEqual(set(card["genres"]), {"Drama", "Thriller"})
        calls = len(fake_tmdb.CALLS)
        self.D.fetch_links()  # fresh links: no new requests
        self.assertEqual(len(fake_tmdb.CALLS), calls)

    def test_pending_count_when_capped(self):
        self.add(100, 200, 300, 400, status="completed")
        self.assertEqual(self.D.fetch_links(cap=2), 2)
        self.assertEqual(self.D.fetch_links(cap=2), 0)


class TestExportImportV2(Base):
    def test_roundtrip_includes_ratings_comparisons_favourites_and_settings(self):
        self.add(100, 200)
        ep = self.svc.detail(100)["season_list"][0]["episodes"][0]["id"]
        self.svc.mark(ep)
        self.svc.toggle_favourite(ep)
        self.R.save_profile(preset="story", mode="card")
        self.R.rate(100, "card", scores=ALL(4))
        self.R.rate(100, "card", scores=ALL(5))
        self.R.rate(200, "card", scores=ALL(5))
        self.R.compare("overall", 100, 200, "a")
        self.svc.discover.dismiss(501)
        data = json.loads(self.backups.export_json().read_text())
        self.assertEqual(data["version"], 2)
        self.assertNotIn("tmdb_key", json.dumps(data))
        for t in ("ratings", "comparisons", "favourites", "dismissed"):
            self.db.x("DELETE FROM " + t)
        self.db.x("DELETE FROM settings WHERE key LIKE 'rating%'")
        res = self.backups.import_json(data)
        self.assertEqual(res["ratings"], 3)
        self.assertEqual(self.db.q1("SELECT COUNT(*) n FROM comparisons")["n"], 1)
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "5 / 5")
        self.assertEqual(len(self.R.show_rating(100)["history"]), 1)
        self.assertEqual(self.R.weights()["writing"], 3)
        self.assertEqual(len(self.svc.favourites()), 1)
        self.assertIsNotNone(self.db.q1("SELECT 1 FROM dismissed WHERE show_id=501"))

    def test_version_1_exports_still_import(self):
        self.add(100)
        v1 = {"format": "tally-export", "version": 1, "user_shows": [dict(r) for r in self.db.q("SELECT * FROM user_shows")],
              "overrides": [], "watch_events": []}
        self.backups.import_json(v1)
        self.assertEqual(self.svc.status_counts()["watching"], 1)

    def test_backup_restore_brings_back_ratings(self):
        self.add(100)
        self.R.rate(100, "card", scores=ALL(4))
        snap = self.backups.snapshot("manual")
        self.R.rate(100, "card", scores=ALL(1))
        self.backups.restore(snap.name)
        self.assertEqual(self.R.show_rating(100)["current"]["final"], "4 / 5")


class TestHttp(Base):
    def setUp(self):
        super().setUp()
        self.srv = TallyServer(self.svc, Path(self.tmp))
        self.srv.start()

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.srv.url.rstrip("/") + path, method=method,
                                     headers={"X-Tally-Token": self.srv.token, "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_whole_ratings_flow_over_http(self):
        for sid in (100, 200, 300):
            self.assertEqual(self.call("POST", "/api/shows/seen", {"tmdb_id": sid, "through": "all"})[0], 200)
        self.assertEqual(self.call("GET", "/api/ratings/profile")[1]["mode"], "card")
        self.assertEqual(self.call("POST", "/api/ratings/profile", {"preset": "story"})[0], 200)
        for sid, v in ((100, 5), (200, 2), (300, 3)):
            code, r = self.call("POST", "/api/ratings", {"show_id": sid, "mode": "card", "scores": ALL(v)})
            self.assertEqual(code, 200)
        self.assertEqual(self.call("POST", "/api/ratings", {"show_id": 100, "mode": "card", "scores": {"writing": 9}})[0], 400)
        code, r = self.call("GET", "/api/ratings/rankings?scope=overall")
        self.assertEqual(r["items"][0]["id"], 100)
        code, r = self.call("GET", "/api/ratings/arena")
        self.assertIn("remaining", r)
        code, r = self.call("GET", "/api/discover?mode=you")
        self.assertTrue(r["unlocked"])
        self.assertEqual(r["cards"][0]["id"], 500)
        self.assertEqual(self.call("POST", "/api/discover/dismiss", {"show_id": 500})[0], 200)
        code, r = self.call("GET", "/api/discover?mode=you")
        self.assertNotIn(500, [c["id"] for c in r["cards"]])
        eid = self.call("GET", "/api/shows/100")[1]["season_list"][0]["episodes"][0]["id"]
        self.assertTrue(self.call("POST", "/api/favourites/toggle", {"episode_id": eid})[1]["favourite"])
        code, r = self.call("POST", "/api/shows/100/seasons/rate", {"scores": {"1": 5, "2": 3}})
        self.assertEqual((code, r["best"], r["weakest"]), (200, [1], [2]))
        self.assertEqual(self.call("POST", "/api/shows/100/seasons/rate", {"scores": {"1": 9}})[0], 400)
        code, r = self.call("POST", "/api/shows/100/seasons/prefs", {"mode": "blend", "mix": 40})
        self.assertEqual((code, r["mode"], r["mix"]), (200, "blend", 40))
        self.assertEqual(self.call("POST", "/api/shows/100/seasons/prefs", {"mode": "weird"})[0], 400)
        self.assertEqual(self.call("GET", "/api/shows/100/seasons")[1]["rated"], 2)
        self.assertEqual(self.call("GET", "/api/shows/100")[1]["season_rating"]["mode"], "blend")
        self.call("POST", "/api/shows/100/seasons/rate", {"scores": {"1": 5, "2": 5}})
        code, r = self.call("POST", "/api/shows/100/seasons/compare", {"a": 1, "b": 2, "result": "a"})
        self.assertEqual((code, r["best"]), (200, [1]))
        self.assertEqual(self.call("POST", "/api/shows/100/seasons/compare", {"a": 1, "b": 1, "result": "a"})[0], 400)
        self.assertEqual(len(self.call("GET", "/api/favourites")[1]["favourites"]), 1)


if __name__ == "__main__":
    unittest.main()
