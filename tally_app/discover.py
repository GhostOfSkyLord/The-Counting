"""Discover: candidates come from TMDB's recommendation links; the ORDER comes from your own ratings."""
import json
import time

RANK_UNLOCK = 3          # rated shows needed before The Counting ranks by your taste
LINK_REFRESH_S = 14 * 24 * 3600
SOURCE_WEIGHT, GENRE_WEIGHT = 0.7, 0.3
LINK_BONUS, LINK_BONUS_CAP = 0.04, 2
NO_LINK_PENALTY = 0.05
TIER_MARGIN = 0.04


class Discover:
    def __init__(self, db, tmdb, ratings):
        self.db, self.tmdb, self.ratings = db, tmdb, ratings

    # ------------------------------------------------------------------ fetching (TMDB)
    def seeds(self):
        """Shows whose recommendation links we use: everything you rated or completed."""
        rated = set(self.ratings.latest())
        done = {r["show_id"] for r in self.db.q("SELECT show_id FROM user_shows WHERE status='completed'")}
        return sorted(i for i in (rated | done) if self.db.q1("SELECT 1 FROM shows WHERE id=?", (i,)))

    def _ensure_genres(self):
        if self.db.q1("SELECT 1 FROM genres LIMIT 1"):
            return
        data = self.tmdb.get("/genre/tv/list", language="en-US")
        with self.db.tx():
            for g in data.get("genres", []):
                self.db.x("INSERT OR REPLACE INTO genres(id,name) VALUES(?,?)", (g["id"], g["name"]))

    def fetch_links(self, cap=6):
        """Fetches recommendation links for seeds that have none (or old ones). Returns how many seeds are still waiting."""
        now = time.time()
        fetched = {r["seed_id"]: r["fetched_at"] for r in self.db.q("SELECT * FROM rec_fetched")}
        waiting = [s for s in self.seeds() if now - fetched.get(s, 0) > LINK_REFRESH_S]
        if waiting:
            self._ensure_genres()
        for sid in waiting[:cap]:
            data = self.tmdb.get("/tv/%d/recommendations" % sid, language="en-US")
            with self.db.tx():
                self.db.x("DELETE FROM rec_links WHERE seed_id=?", (sid,))
                for r in (data.get("results") or [])[:20]:
                    self.db.x("""INSERT INTO candidates(id,name,overview,poster_path,first_air_date,genre_ids)
                                 VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                                 overview=excluded.overview, poster_path=excluded.poster_path,
                                 first_air_date=excluded.first_air_date, genre_ids=excluded.genre_ids""",
                              (r["id"], r.get("name"), r.get("overview"), r.get("poster_path"),
                               r.get("first_air_date"), json.dumps(r.get("genre_ids") or [])))
                    self.db.x("INSERT OR IGNORE INTO rec_links(seed_id,rec_id) VALUES(?,?)", (sid, r["id"]))
                self.db.x("INSERT OR REPLACE INTO rec_fetched(seed_id,fetched_at) VALUES(?,?)", (sid, time.time()))
        return max(0, len(waiting) - cap)

    # ------------------------------------------------------------------ ranking (ours)
    def dismiss(self, show_id):
        self.db.x("INSERT OR REPLACE INTO dismissed(show_id,dismissed_at) VALUES(?,?)", (int(show_id), time.time()))

    def _genre_names(self):
        return {r["id"]: r["name"] for r in self.db.q("SELECT * FROM genres")}

    def listing(self, mode="you"):
        R = self.ratings
        latest = R.latest()
        seeds = set(self.seeds())
        names = {r["id"]: r["name"] for r in self.db.q("SELECT id,name FROM shows")}
        show_genres = {r["id"]: json.loads(r["genres"] or "[]") for r in self.db.q("SELECT id,genres FROM shows")}
        unlocked = len(latest) >= RANK_UNLOCK
        if mode == "you" and not unlocked:
            mode = "tmdb"
        excluded = {r["show_id"] for r in self.db.q("SELECT show_id FROM user_shows")} | \
                   {r["show_id"] for r in self.db.q("SELECT show_id FROM dismissed")}
        gname = self._genre_names()
        links = {}
        for r in self.db.q("SELECT seed_id, rec_id FROM rec_links"):
            if r["seed_id"] in seeds and r["rec_id"] not in excluded:
                links.setdefault(r["rec_id"], []).append(r["seed_id"])
        cands = {r["id"]: r for r in self.db.q("SELECT * FROM candidates")}

        finals = {sid: R.final(r) for sid, r in latest.items()}
        mean = sum(finals.values()) / len(finals) if finals else 0.5
        # order of your rated shows, best first, including your arena answers
        rk = R.rankings("overall")["items"]
        pos = {x["id"]: i + 1 for i, x in enumerate(rk)}
        genre_scores = {}
        for sid, f in finals.items():
            for g in show_genres.get(sid, []):
                genre_scores.setdefault(g, []).append(f)
        gavg = {g: sum(v) / len(v) for g, v in genre_scores.items()}

        out = []
        for cid, seed_ids in links.items():
            c = cands.get(cid)
            if not c:
                continue
            genres = [gname.get(i) for i in json.loads(c["genre_ids"] or "[]") if gname.get(i)]
            rated_seeds = sorted((s for s in seed_ids if s in finals), key=lambda s: -finals[s])
            card = {"id": cid, "name": c["name"], "overview": c["overview"] or "", "poster_path": c["poster_path"],
                    "year": (c["first_air_date"] or "")[:4], "genres": genres, "links": len(seed_ids),
                    "from": [names.get(s, "a show you know") for s in seed_ids]}
            seed_part = sum(finals[s] for s in rated_seeds) / len(rated_seeds) if rated_seeds else mean
            ga = [(g, gavg[g]) for g in genres if g in gavg]
            genre_part = sum(v for _, v in ga) / len(ga) if ga else mean
            score = SOURCE_WEIGHT * seed_part + GENRE_WEIGHT * genre_part + (
                min(len(rated_seeds) - 1, LINK_BONUS_CAP) * LINK_BONUS if rated_seeds else -NO_LINK_PENALTY)
            card.update(score=score, seed_part=seed_part, n_rated=len(rated_seeds), ga=ga)
            if unlocked:
                card["tier"] = ("Strong match" if score >= mean + TIER_MARGIN
                                else "Good match" if score >= mean - TIER_MARGIN else "Worth a look")
                if rated_seeds:
                    parts = ["%s (%s, your #%d)" % (names[s], R.text(finals[s]), pos.get(s, 0)) for s in rated_seeds]
                    why = "Recommended from " + " and ".join(parts) + "."
                else:
                    why = "None of your rated shows point to this one, so it is placed using your genre tastes only."
                if ga:
                    why += " Your %s shows average %s." % (ga[0][0], R.text(ga[0][1]))
                card["why"] = why
            out.append(card)

        if mode == "you":
            out.sort(key=lambda c: -c["score"])
            for a, b in zip(out, out[1:]):
                if not b["n_rated"] and a["n_rated"]:
                    r = "none of your rated shows point to %s." % b["name"]
                elif a["n_rated"] and b["n_rated"] and abs(a["seed_part"] - b["seed_part"]) > 0.02:
                    r = "the shows that point to it average %s in your ratings, against %s for %s." % (
                        R.text(a["seed_part"]), R.text(b["seed_part"]), b["name"])
                elif a["n_rated"] > b["n_rated"]:
                    r = "more of your rated shows point to it."
                else:
                    r = "your ratings of similar genres are a little higher."
                a["vs_next"] = "Ranks above %s because %s" % (b["name"], r)
        else:
            out.sort(key=lambda c: (-c["links"], c["name"] or ""))
        for c in out:
            for k in ("score", "seed_part", "ga"):
                c.pop(k, None)
        return {"mode": mode, "unlocked": unlocked, "rated": len(latest), "need": RANK_UNLOCK, "cards": out}
