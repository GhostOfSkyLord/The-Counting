"""The Counting's rules: tracking, spoilers, progress, readiness and statistics."""
import json
import time
from collections import defaultdict
from datetime import date, datetime

from . import sync as syncmod
from . import netfix
from .discover import Discover
from .ratings import Ratings, RatingError
from .tmdb import TMDBError, clean_key, describe

STATUSES = ("plan", "watching", "hold", "dropped", "completed")


class UserError(RatingError):
    """A problem the person can understand and fix. The message is shown as is."""


def _json(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


class Service:
    def __init__(self, db, tmdb, backups, refresher=None, today=None):
        self.db, self.tmdb, self.backups, self.refresher = db, tmdb, backups, refresher
        self.today = today or (lambda: date.today().isoformat())
        self.ratings = Ratings(db)
        self.discover = Discover(db, tmdb, self.ratings)
        from .guide import Guide  # here, not at the top: the guide uses this module's UserError
        self.guide = Guide(db)

    # ------------------------------------------------------------------ settings
    def has_key(self):
        return bool((self.db.get_setting("tmdb_key") or "").strip())

    def state(self):
        b = self.backups.list()
        return {
            "has_key": self.has_key(),
            "secure_dns": self.db.get_setting("secure_dns", "1") == "1",
            "theme": self.db.get_setting("theme", "system"),
            "pending_sync": self.refresher.pending if self.refresher else 0,
            "backup_folder": str(self.backups.folder()),
            "backup_keep": self.backups.keep(),
            "last_backup": b[0]["modified"] if b else None,
            "counts": self.status_counts(),
        }

    def save_key(self, key):
        key = clean_key(key)
        if not key:
            raise UserError("Paste your TMDB API key first.")
        try:
            self.tmdb.check_key(key)
        except TMDBError as e:
            raise UserError(e.message)
        self.db.set_setting("tmdb_key", key)

    def diagnose(self):
        """Step-by-step check of the connection to TMDB, so a failure can be pinned to one step."""
        import urllib.request
        steps = [{"name": "The Counting's engine", "ok": True, "detail": "Running."}]
        proxies = urllib.request.getproxies()
        steps.append({"name": "Proxy settings", "ok": True,
                      "detail": ("A proxy is set: " + ", ".join("%s=%s" % kv for kv in proxies.items()))
                      if proxies else "No proxy is set on this PC."})
        first, how = self._check_host(self.tmdb.base)
        steps.extend(first)
        if how:
            if how == "secure_dns":
                steps.append({"name": "Result", "ok": True, "detail":
                              "The normal connection is blocked, but a browser-style secure DNS lookup works. "
                              "The Counting uses it automatically when \"Use secure DNS if needed\" is on in Settings."})
            return self._check_key(steps)
        if self.tmdb.alt:
            second, how2 = self._check_host(self.tmdb.alt)
            steps.extend(second)
            if how2:
                steps.append({"name": "Result", "ok": True,
                              "detail": "The first address is blocked but the second works. The Counting uses the second automatically."})
                return self._check_key(steps)
        return steps

    def _check_host(self, base_url):
        """Returns (steps, how) where how is 'plain', 'secure_dns', or None if nothing worked."""
        import socket
        import urllib.error
        import urllib.request
        from urllib.parse import urlparse
        base = urlparse(base_url)
        host, secure = base.hostname, base.scheme == "https"
        port = base.port or (443 if secure else 80)
        steps = []

        def step(name, fn):
            try:
                detail = fn()
                steps.append({"name": name, "ok": True, "detail": detail})
                return True
            except Exception as e:  # each step reports its own failure
                steps.append({"name": name, "ok": False, "detail": describe(getattr(e, "reason", e))})
                return False

        def ask(opener):
            try:
                opener()
                return "TMDB answered."
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return "TMDB answered and asked for a key, as expected."
                raise

        ok = step("Find " + host, lambda: "Found " + socket.getaddrinfo(host, port)[0][4][0] + ".")
        if ok and secure:
            ok = step("Secure connection to " + host, lambda: (netfix_tls(host, port), "Secure connection established.")[1])
        if ok:
            ok = step("Ask " + host, lambda: ask(lambda: urllib.request.urlopen(base_url + "/configuration", timeout=15)))
            if ok:
                return steps, "plain"
        if not secure:
            return steps, None
        ips = []

        def lookup():
            ips.extend(netfix.doh_lookup(host))
            if not ips:
                raise OSError("The Counting could not reach the secure DNS services (Cloudflare 1.1.1.1 or Google 8.8.8.8).")
            return "Found " + ips[0] + "."
        if not step("Look up " + host + " with secure DNS", lookup):
            return steps, None
        if not step("Secure connection using that address", lambda: (netfix.tls_check(ips[0], host, port), "Secure connection established.")[1]):
            return steps, None
        req = urllib.request.Request(base_url + "/configuration")
        if step("Ask " + host + " using that address", lambda: ask(lambda: netfix.open_pinned(req, ips[0], 15))):
            return steps, "secure_dns"
        return steps, None

    def _check_key(self, steps):
        key = (self.db.get_setting("tmdb_key") or "").strip()
        if key:
            def keycheck():
                self.tmdb.check_key(key)
                return "Your saved key works."
            try:
                steps.append({"name": "Your API key", "ok": True, "detail": keycheck()})
            except TMDBError as e:
                steps.append({"name": "Your API key", "ok": False, "detail": e.message})
        else:
            steps.append({"name": "Your API key", "ok": True, "detail": "No key saved yet."})
        return steps

    def save_backup_settings(self, folder=None, keep=None):
        if folder:
            try:
                self.backups.set_folder(folder)
            except OSError:
                raise UserError("The Counting cannot write to that folder. Pick another one.")
        if keep is not None:
            try:
                self.db.set_setting("backup_keep", str(max(3, min(100, int(keep)))))
            except (TypeError, ValueError):
                raise UserError("Enter a number of backups to keep.")

    # ------------------------------------------------------------------ search / add
    def search(self, query):
        query = (query or "").strip()
        if len(query) < 2:
            return []
        data = self.tmdb.get("/search/tv", query=query, include_adult="false", language="en-US")
        have = {r["show_id"]: r["status"] for r in self.db.q("SELECT show_id,status FROM user_shows")}
        out = []
        for r in (data.get("results") or [])[:20]:
            out.append({"id": r["id"], "name": r.get("name"), "year": (r.get("first_air_date") or "")[:4],
                        "overview": r.get("overview") or "", "poster_path": r.get("poster_path"),
                        "in_library": have.get(r["id"])})
        return out

    def add_show(self, tmdb_id, status="plan", source="manual"):
        if status not in STATUSES:
            raise UserError("Unknown status.")
        tmdb_id = int(tmdb_id)
        if not self.db.q1("SELECT 1 FROM shows WHERE id=?", (tmdb_id,)):
            syncmod.sync_show(self.db, self.tmdb, tmdb_id)
        now = time.time()
        if not self.db.q1("SELECT 1 FROM user_shows WHERE show_id=?", (tmdb_id,)):
            self.db.x("INSERT INTO user_shows(show_id,status,source,added_at,updated_at) VALUES(?,?,?,?,?)",
                      (tmdb_id, status, source, now, now))
        return self.summary(tmdb_id)

    def add_seen_show(self, tmdb_id, through="all"):
        """Adds a show you watched before The Counting. Marks episodes without dates, then decides its status."""
        s = self.add_show(tmdb_id, "plan", source="seen before")
        sid = int(tmdb_id)
        seasons = self.db.q("SELECT DISTINCT season_number n FROM episodes WHERE show_id=? AND season_number>=1 ORDER BY n", (sid,))
        last = seasons[-1]["n"] if seasons else 0
        upto = last if through in (None, "all") else int(through)
        self.mark_through_season(sid, upto)
        d = self._build(sid)
        finished = d["state"] == "All watched"
        self.set_status(sid, "completed" if finished else "watching")
        d = self._build(sid)
        d["ask_rating"] = finished and not self.ratings.current_text(sid)
        return d

    def refresh_show(self, show_id):
        syncmod.sync_show(self.db, self.tmdb, int(show_id))
        return self.detail(show_id)

    def remove_show(self, show_id):
        """Removes the show from your lists. Your watch history is kept, so re-adding restores it."""
        self.db.x("DELETE FROM user_shows WHERE show_id=?", (int(show_id),))
        self.db.x("DELETE FROM overrides WHERE show_id=?", (int(show_id),))

    # ------------------------------------------------------------------ status / overrides
    def set_status(self, show_id, status):
        if status not in STATUSES:
            raise UserError("Unknown status.")
        self.db.x("UPDATE user_shows SET status=?, updated_at=? WHERE show_id=?", (status, time.time(), int(show_id)))
        return self.summary(show_id)

    def overrides(self, show_id):
        r = self.db.q1("SELECT * FROM overrides WHERE show_id=?", (int(show_id),))
        return {"hide_titles": bool(r["hide_titles"]) if r else False,
                "absolute_numbering": bool(r["absolute_numbering"]) if r else False,
                "include_specials": bool(r["include_specials"]) if r else False}

    def set_overrides(self, show_id, changes):
        cur = self.overrides(show_id)
        for k in cur:
            if k in changes:
                cur[k] = bool(changes[k])
        self.db.x("""INSERT INTO overrides(show_id,hide_titles,absolute_numbering,include_specials) VALUES(?,?,?,?)
                     ON CONFLICT(show_id) DO UPDATE SET hide_titles=excluded.hide_titles,
                     absolute_numbering=excluded.absolute_numbering, include_specials=excluded.include_specials""",
                  (int(show_id), int(cur["hide_titles"]), int(cur["absolute_numbering"]), int(cur["include_specials"])))
        return self.detail(show_id)

    # ------------------------------------------------------------------ watch log
    def watch_counts(self, show_id):
        rows = self.db.q("SELECT episode_id, SUM(CASE type WHEN 'watch' THEN 1 ELSE -1 END) n FROM watch_events "
                         "WHERE show_id=? GROUP BY episode_id", (int(show_id),))
        return {r["episode_id"]: max(0, r["n"]) for r in rows}

    def _event(self, episode_id, show_id, typ, source, ts="now"):
        self.db.x("INSERT INTO watch_events(episode_id,show_id,type,source,ts) VALUES(?,?,?,?,?)",
                  (episode_id, show_id, typ, source, time.time() if ts == "now" else ts))

    def _auto_start(self, show_id):
        row = self.db.q1("SELECT status FROM user_shows WHERE show_id=?", (show_id,))
        if row and row["status"] in ("plan", "hold", "dropped"):
            self.set_status(show_id, "watching")
            return True
        return False

    # ------------------------------------------------------------------ building views
    def _aired(self, e):
        return bool(e["air_date"]) and e["air_date"] <= self.today()

    def _build(self, show_id, full=False):
        show_id = int(show_id)
        s = self.db.q1("SELECT * FROM shows WHERE id=?", (show_id,))
        u = self.db.q1("SELECT * FROM user_shows WHERE show_id=?", (show_id,))
        if not s:
            return {"id": show_id, "name": "Show %d (waiting for data)" % show_id, "poster_path": None,
                    "status": u["status"] if u else None, "loading": True, "genres": [], "seasons": 0,
                    "episodes": 0, "runtime": 0, "tmdb_status": "", "progress": {"watched": 0, "total": 0, "percent": 0},
                    "next": None, "state": None, "readiness": {"kind": "unknown", "text": "Waiting for data"},
                    "hours": 0, "overview": "", "source": u["source"] if u else None}
        eps = self.db.q("SELECT * FROM episodes WHERE show_id=? ORDER BY season_number, episode_number", (show_id,))
        counts = self.watch_counts(show_id)
        o = self.overrides(show_id)
        favs = self.ratings.favourite_ids(show_id) if full else set()
        reg = [e for e in eps if e["season_number"] >= 1]
        spc = [e for e in eps if e["season_number"] == 0]
        run = s["runtime"] or 40

        def label(e, idx=None):
            base = "S%dE%d" % (e["season_number"], e["episode_number"])
            return base + (" (#%d)" % (idx + 1) if o["absolute_numbering"] and idx is not None else "")

        def item(e, idx, unlocked):
            n = counts.get(e["id"], 0)
            hide = o["hide_titles"]
            d = {"id": e["id"], "season": e["season_number"], "episode": e["episode_number"],
                 "label": label(e, idx) if idx is not None else "Special %d" % e["episode_number"],
                 "abs": (idx + 1) if idx is not None else None,
                 "name": None if hide else e["name"], "titles_hidden": hide,
                 "air_date": e["air_date"], "aired": self._aired(e), "runtime": e["runtime"] or run,
                 "watched": n, "unlocked": unlocked, "favourite": e["id"] in favs}
            if unlocked:  # spoiler protection is enforced here, not only in the UI
                d["overview"] = e["overview"]
                d["still_path"] = e["still_path"]
            else:
                d["overview"] = None
                d["still_path"] = None
            return d

        reg_items = []
        for i, e in enumerate(reg):
            prev_done = i == 0 or counts.get(reg[i - 1]["id"], 0) > 0
            reg_items.append(item(e, i, counts.get(e["id"], 0) > 0 or prev_done))
        aired_reg = [x for x in reg_items if x["aired"]]
        prog_items = list(aired_reg)
        spc_items = [item(e, None, True) for e in spc]
        if o["include_specials"]:
            prog_items += [x for x in spc_items if x["aired"]]
        watched = sum(1 for x in prog_items if x["watched"] > 0)
        total = len(prog_items)
        nxt = next((x for x in reg_items if x["aired"] and x["watched"] == 0), None)
        ended = s["tmdb_status"] in ("Ended", "Canceled")
        state = None
        if total and watched == total:
            state = "All watched" if ended else "Up to date"

        unaired = len(reg_items) - len(aired_reg)
        if not reg_items:
            readiness = {"kind": "unknown", "text": "No episode data yet"}
        elif ended:
            readiness = {"kind": "ready", "text": "Ready to binge"}
        elif unaired > 0:
            readiness = {"kind": "wait", "text": "Still airing (%d of %d episodes out)" % (len(aired_reg), len(reg_items))}
        else:
            last = next((e for e in reversed(reg) if self._aired(e)), None)
            if last is not None and last["episode_type"] == "finale":
                readiness = {"kind": "ready", "text": "Latest season ready"}
            else:
                readiness = {"kind": "maybe", "text": "Probably ready"}

        out = {
            "id": show_id, "name": s["name"], "poster_path": s["poster_path"],
            "status": u["status"] if u else None, "source": u["source"] if u else None,
            "tmdb_status": s["tmdb_status"] or "", "genres": _json(s["genres"], []),
            "seasons": len({e["season_number"] for e in reg}), "episodes": len(reg_items), "runtime": run,
            "progress": {"watched": watched, "total": total, "percent": round(watched / total * 100) if total else 0},
            "next": ({"id": nxt["id"], "label": nxt["label"], "name": nxt["name"], "titles_hidden": nxt["titles_hidden"]}
                     if nxt else None),
            "state": state, "readiness": readiness, "hours": round(len(aired_reg) * run / 60, 1),
            "overview": s["overview"] or "", "rating": self.ratings.current_text(show_id),
        }
        if full:
            seasons = []
            for n in sorted({x["season"] for x in reg_items}):
                lst = [x for x in reg_items if x["season"] == n]
                seasons.append({"number": n, "episodes": lst,
                                "watched": sum(1 for x in lst if x["watched"] > 0),
                                "total": len(lst), "airing": any(not x["aired"] for x in lst)})
            out.update({"backdrop_path": s["backdrop_path"], "networks": _json(s["networks"], []),
                        "cast": _json(s["cast_json"], []), "overrides": o, "season_list": seasons,
                        "specials": spc_items, "next_season": nxt and next(
                            (x["season"] for x in reg_items if x["id"] == nxt["id"]), None),
                        "synced_at": s["synced_at"], "rating_info": self.ratings.show_rating(show_id),
                        "season_rating": self.ratings.season_info(show_id),
                        "rating_profile": self.ratings.profile()})
        return out

    def summary(self, show_id):
        return self._build(show_id)

    def detail(self, show_id):
        d = self._build(show_id, full=True)
        if d.get("loading"):
            raise UserError("The Counting is still fetching this show's data. Try again in a moment.")
        return d

    # ------------------------------------------------------------------ lists
    def status_counts(self):
        c = {k: 0 for k in STATUSES}
        for r in self.db.q("SELECT status, COUNT(*) n FROM user_shows GROUP BY status"):
            c[r["status"]] = r["n"]
        return c

    def library(self, status):
        rows = self.db.q("""SELECT u.show_id, COALESCE((SELECT MAX(ts) FROM watch_events w WHERE w.show_id=u.show_id),
                            u.added_at) act FROM user_shows u WHERE u.status=? ORDER BY act DESC""", (status,))
        return {"counts": self.status_counts(), "shows": [self.summary(r["show_id"]) for r in rows]}

    def to_watch(self):
        rows = self.db.q("SELECT show_id FROM user_shows WHERE status='plan' ORDER BY added_at DESC")
        return {"counts": self.status_counts(), "shows": [self.summary(r["show_id"]) for r in rows]}

    # ------------------------------------------------------------------ marking
    def _regular_aired(self, show_id):
        return [e for e in self.db.q("SELECT * FROM episodes WHERE show_id=? AND season_number>=1 "
                                     "ORDER BY season_number, episode_number", (show_id,)) if self._aired(e)]

    def mark(self, episode_id, resolve=None):
        """Marks one episode. Returns a prompt when the person needs to decide something first."""
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (int(episode_id),))
        if not ep:
            raise UserError("That episode is no longer in TMDB's data.")
        sid = ep["show_id"]
        if not self._aired(ep):
            raise UserError("That episode has not aired yet.")
        counts = self.watch_counts(sid)
        if counts.get(ep["id"], 0) > 0:
            if resolve is None:
                return {"prompt": "rewatch"}
            if resolve == "rewatch":
                self._event(ep["id"], sid, "watch", "rewatch")
                return {"ok": True, "message": "Logged as a rewatch."}
            if resolve == "undo":
                self._event(ep["id"], sid, "undo", "single")
                return {"ok": True, "message": "Earlier mark removed."}
            return {"ok": True, "message": None}  # "mistake": nothing changes
        if ep["season_number"] >= 1:
            gaps = [e for e in self._regular_aired(sid)
                    if (e["season_number"], e["episode_number"]) < (ep["season_number"], ep["episode_number"])
                    and counts.get(e["id"], 0) == 0]
            if gaps and resolve is None:
                return {"prompt": "gaps", "count": len(gaps)}
            if gaps and resolve == "all":
                for g in gaps:
                    self._event(g["id"], sid, "watch", "bulk", ts=None)
        self._event(ep["id"], sid, "watch", "single")
        return {"ok": True, "started": self._auto_start(sid), "show": self.summary(sid)}

    def seen_up_to(self, episode_id):
        """Marks every aired, unwatched episode up to and including this one. Never duplicates."""
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (int(episode_id),))
        if not ep:
            raise UserError("That episode is no longer in TMDB's data.")
        sid = ep["show_id"]
        counts = self.watch_counts(sid)
        key = (ep["season_number"], ep["episode_number"])
        marked = skipped = 0
        with self.db.tx():
            for e in self._regular_aired(sid):
                if (e["season_number"], e["episode_number"]) <= key:
                    if counts.get(e["id"], 0) > 0:
                        skipped += 1
                    else:
                        self._event(e["id"], sid, "watch", "bulk", ts=None)
                        marked += 1
        return {"ok": True, "marked": marked, "skipped": skipped, "started": self._auto_start(sid)}

    def mark_through_season(self, show_id, season):
        """For 'I have already seen this show, up to season N'."""
        sid = int(show_id)
        counts = self.watch_counts(sid)
        marked = 0
        with self.db.tx():
            for e in self._regular_aired(sid):
                if e["season_number"] <= int(season) and counts.get(e["id"], 0) == 0:
                    self._event(e["id"], sid, "watch", "bulk", ts=None)
                    marked += 1
        return {"marked": marked}

    # ------------------------------------------------------------------ stats and log
    def toggle_favourite(self, episode_id):
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (int(episode_id),))
        if not ep:
            raise UserError("That episode is no longer in TMDB's data.")
        if self.watch_counts(ep["show_id"]).get(ep["id"], 0) == 0:
            raise UserError("Mark the episode watched before favouriting it.")
        return {"favourite": self.ratings.toggle_favourite(ep["id"], ep["show_id"])}

    def favourites(self):
        return self.ratings.favourites(lambda sid: self.overrides(sid)["hide_titles"])

    def stats(self):
        per_ep = defaultdict(int)
        show_of = {}
        for r in self.db.q("SELECT episode_id, show_id, SUM(CASE type WHEN 'watch' THEN 1 ELSE -1 END) n "
                           "FROM watch_events GROUP BY episode_id, show_id"):
            if r["n"] > 0:
                per_ep[r["episode_id"]] = r["n"]
                show_of[r["episode_id"]] = r["show_id"]
        shows = {r["id"]: r for r in self.db.q("SELECT * FROM shows")}
        eprun = {r["id"]: r["runtime"] for r in self.db.q("SELECT id, runtime FROM episodes")}
        hours_by_show, hours_by_genre, total_h, rewatched = defaultdict(float), defaultdict(float), 0.0, 0
        for eid, n in per_ep.items():
            sh = shows.get(show_of[eid])
            run = eprun.get(eid) or (sh["runtime"] if sh else None) or 40
            h = n * run / 60
            total_h += h
            rewatched += 1 if n > 1 else 0
            if sh:
                hours_by_show[sh["name"]] += h
                for g in _json(sh["genres"], []):
                    hours_by_genre[g] += h
        # derived from what the shows are: where they aired and when they started
        by_network, by_decade = defaultdict(float), defaultdict(float)
        for sid, sh in shows.items():
            h = hours_by_show.get(sh["name"], 0)
            if not h:
                continue
            for net in _json(sh["networks"], []):
                by_network[net] += h
            year = (sh["first_air_date"] or "")[:4]
            if year.isdigit():
                by_decade["%ds" % (int(year) // 10 * 10)] += h
        # derived from your ratings: how highly you rate each genre
        R = self.ratings
        latest = R.latest()
        genre_scores = defaultdict(list)
        for sid, r in latest.items():
            if sid in shows:
                for g in _json(shows[sid]["genres"], []):
                    genre_scores[g].append(R.final(r))
        rating_by_genre = sorted(([g, round(sum(v) / len(v) * R.max_display(), 2), len(v)] for g, v in genre_scores.items()),
                                 key=lambda x: (-x[1], x[0]))
        # derived from when you tap: months and days of the week
        months, weekdays, undated = defaultdict(int), [0] * 7, 0
        for r in self.db.q("SELECT ts FROM watch_events WHERE type='watch'"):
            if r["ts"] is None:
                undated += 1
            else:
                d = datetime.fromtimestamp(r["ts"])
                months[d.strftime("%Y-%m")] += 1
                weekdays[d.weekday()] += 1
        rnd = lambda d: sorted(([k, round(v, 1)] for k, v in d.items()), key=lambda x: (-x[1], x[0]))
        return {"episodes": len(per_ep), "hours": round(total_h, 1), "rewatched": rewatched,
                "completed": self.status_counts()["completed"], "top_shows": rnd(hours_by_show)[:5],
                "by_genre": rnd(hours_by_genre)[:10], "by_network": rnd(by_network)[:10],
                "by_decade": sorted(([k, round(v, 1)] for k, v in by_decade.items())),
                "rating_by_genre": rating_by_genre[:10], "rating_max": R.max_display(), "rated_shows": len(latest),
                "by_weekday": weekdays, "by_month": sorted(months.items())[-12:], "undated": undated,
                "season_trends": R.season_trends()}

    def log(self, limit=100):
        out = []
        for r in self.db.q("""SELECT w.id, w.type, w.source, w.ts, w.episode_id, w.show_id, e.season_number s,
                              e.episode_number n, e.name en, sh.name shn FROM watch_events w
                              LEFT JOIN episodes e ON e.id=w.episode_id LEFT JOIN shows sh ON sh.id=w.show_id
                              ORDER BY w.id DESC LIMIT ?""", (int(limit),)):
            out.append({"n": r["id"], "type": r["type"], "source": r["source"], "ts": r["ts"],
                        "show": r["shn"] or "Show %d" % r["show_id"], "episode_id": r["episode_id"],
                        "label": ("S%dE%d" % (r["s"], r["n"])) if r["s"] is not None else "episode no longer listed"})
        return out


def netfix_tls(host, port):
    """Opens a normal secure connection using whatever address Windows resolves (no fallback)."""
    import socket
    import ssl
    with socket.create_connection((host, port), timeout=10) as raw:
        with netfix.context().wrap_socket(raw, server_hostname=host):
            return True
