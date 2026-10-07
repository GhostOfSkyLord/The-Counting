"""Ratings: a weighted scorecard (or a simple 1-5 / 1-10 score), history, rankings, the arena, favourites."""
import json
import math
import time

CRITERIA = [("writing", "Writing"), ("acting", "Acting and casting"), ("cine", "Cinematography"),
            ("edit", "Editing and pacing"), ("sound", "Sound and music"), ("dir", "Direction")]
KEYS = [k for k, _ in CRITERIA]
NAMES = dict(CRITERIA)
LEVELS = ["Ignore", "Somewhat", "Important", "Essential"]
PRESETS = {
    "balanced": {"label": "Balanced", "w": [2, 2, 2, 2, 2, 2]},
    "story": {"label": "Story first", "w": [3, 3, 1, 2, 1, 2]},
    "looks": {"label": "Looks first", "w": [1, 1, 3, 2, 3, 2]},
}
DEFAULT_WEIGHTS = {"writing": 3, "acting": 2, "cine": 2, "edit": 1, "sound": 1, "dir": 2}
NEAR_TIE_POINTS = 0.5      # scores this close (in points) count as a tie for the arena
ARENA_MIN_FRACTION = 0.8   # the arena only asks about shows scored 4 out of 5 or higher: that is where scores bunch up
SEASON_MODES = ("off", "blend", "seasons")
ARENA_TOP_K = 3            # by default the arena only settles your top three in a view: that is where the order matters
ARENA_SHIFT = 0.06         # each "is better" answer moves a show by this much (0.3 points on a 5-point scale)


class RatingError(Exception):
    """A problem the person can understand. The message is shown as is."""


class Ratings:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ profile
    def weights(self):
        try:
            w = json.loads(self.db.get_setting("rating_weights") or "{}")
        except ValueError:
            w = {}
        return {k: int(w.get(k, DEFAULT_WEIGHTS[k])) for k in KEYS}

    def mode(self):
        m = self.db.get_setting("rating_mode", "card")
        return m if m in ("card", "5", "10") else "card"

    def max_display(self):
        return 10 if self.mode() == "10" else 5

    def same_genre(self):
        return self.db.get_setting("arena_same_genre", "1") == "1"

    def top_only(self):
        """True: the arena only settles your top three in each view (fewer questions). False: it orders everything."""
        return self.db.get_setting("arena_top_only", "1") == "1"

    def profile(self):
        w = self.weights()
        total = sum(w.values())
        return {
            "mode": self.mode(), "max": self.max_display(), "same_genre": self.same_genre(), "top_only": self.top_only(),
            "levels": LEVELS,
            "criteria": [{"key": k, "name": n, "weight": w[k], "share": round(w[k] / total * 100) if total else 0}
                         for k, n in CRITERIA],
            "presets": [{"key": k, "label": v["label"], "active": all(w[KEYS[i]] == v["w"][i] for i in range(6))}
                        for k, v in PRESETS.items()],
        }

    def save_profile(self, mode=None, weights=None, preset=None, same_genre=None, top_only=None):
        if mode is not None:
            if mode not in ("card", "5", "10"):
                raise RatingError("Unknown rating style.")
            self.db.set_setting("rating_mode", mode)
        if preset is not None:
            if preset not in PRESETS:
                raise RatingError("Unknown preset.")
            weights = dict(zip(KEYS, PRESETS[preset]["w"]))
        if weights is not None:
            cur = self.weights()
            for k, v in weights.items():
                if k in cur:
                    if int(v) not in range(4):
                        raise RatingError("Importance must be Ignore, Somewhat, Important or Essential.")
                    cur[k] = int(v)
            self.db.set_setting("rating_weights", json.dumps(cur))
        if same_genre is not None:
            self.db.set_setting("arena_same_genre", "1" if same_genre else "0")
        if top_only is not None:
            self.db.set_setting("arena_top_only", "1" if top_only else "0")
        return self.profile()

    # ------------------------------------------------------------------ scores
    def _parse(self, row):
        return {"id": row["id"], "show_id": row["show_id"], "mode": row["mode"],
                "scores": json.loads(row["scores"]) if row["scores"] else None,
                "overall": row["overall"], "gut": row["gut"], "created_at": row["created_at"]}

    def _base_final(self, r):
        """The show's own score as a 0-1 fraction, from the CURRENT importance weights. Season scores are not included."""
        if r["mode"] != "card":
            return r["overall"]
        w, sc = self.weights(), r["scores"]
        tw = sum(w.values())
        if not tw:
            return sum(sc[k] for k in KEYS) / len(KEYS)
        return sum(w[k] * sc[k] for k in KEYS) / tw

    def final(self, r):
        """The score that counts, as a 0-1 fraction. It is the show's own score unless the person has chosen to let
        season scores count for this show (then `effective` was filled in by latest())."""
        return r["effective"] if "effective" in r else self._base_final(r)

    def value(self, r, scope):
        if scope == "overall":
            return self.final(r)
        return r["scores"][scope] if r["mode"] == "card" else None

    def text(self, f):
        m = self.max_display()
        v = round(f * m * 10) / 10
        return "%g / %d" % (v, m)

    def text5(self, f):
        return "%g / 5" % (round(f * 50) / 10)

    def scope_text(self, scope, f):
        return self.text(f) if scope == "overall" else self.text5(f)

    # ------------------------------------------------------------------ season scores
    def season_scale(self):
        return 10 if self.mode() == "10" else 5

    @staticmethod
    def _combine(base, avg, mode, mix):
        """How season scores count. base and avg are 0-1 fractions (base may be None)."""
        if mode == "off" or avg is None:
            return base
        if mode == "seasons" or base is None:
            return avg
        return (1 - mix / 100) * base + (mix / 100) * avg

    def _season_state(self, show_id=None):
        """Latest season scores, preferences and episode counts, for one show or for all of them."""
        where, args = ("WHERE show_id=?", (int(show_id),)) if show_id is not None else ("", ())
        rows = self.db.q("SELECT * FROM season_ratings WHERE id IN (SELECT MAX(id) FROM season_ratings %s "
                         "GROUP BY show_id, season_number)" % where, args)
        fracs, made = {}, {}
        for r in rows:
            fracs.setdefault(r["show_id"], {})[r["season_number"]] = r["fraction"]
            made[r["show_id"]] = max(made.get(r["show_id"], 0), r["created_at"])
        prefs = {r["show_id"]: (r["mode"], r["mix"]) for r in self.db.q("SELECT * FROM season_prefs " + where, args)}
        counts = {}
        for r in self.db.q("SELECT show_id, season_number, COUNT(*) n FROM episodes WHERE season_number>=1 %s "
                           "GROUP BY show_id, season_number" % ("AND show_id=?" if show_id is not None else ""), args):
            counts.setdefault(r["show_id"], {})[r["season_number"]] = r["n"]
        return fracs, prefs, counts, made

    @staticmethod
    def _season_average(fracs, counts):
        """The average of the rated seasons, weighted by how many episodes each has."""
        if not fracs:
            return None
        w = {s: max(1, counts.get(s, 1)) for s in fracs}
        return sum(fracs[s] * w[s] for s in fracs) / sum(w.values())

    def latest(self):
        rows = self.db.q("SELECT * FROM ratings WHERE id IN (SELECT MAX(id) FROM ratings GROUP BY show_id)")
        out = {r["show_id"]: self._parse(r) for r in rows}
        fracs, prefs, counts, made = self._season_state()
        for sid, fr in fracs.items():
            mode, mix = prefs.get(sid, ("off", 50))
            if mode == "off":
                continue
            avg = self._season_average(fr, counts.get(sid, {}))
            if sid in out:
                out[sid]["effective"] = self._combine(self._base_final(out[sid]), avg, mode, mix)
                out[sid]["season_note"] = True
            else:  # no score for the show itself: it is rated from its seasons alone
                out[sid] = {"id": None, "show_id": sid, "mode": "seasons", "scores": None, "overall": avg, "gut": None,
                            "created_at": made.get(sid, 0), "effective": avg, "season_note": True}
        return out

    def rate(self, show_id, mode, scores=None, overall=None, gut=None):
        show_id = int(show_id)
        if not self.db.q1("SELECT 1 FROM shows WHERE id=?", (show_id,)):
            raise RatingError("That show is not in your library yet.")
        if mode == "card":
            if not isinstance(scores, dict) or set(scores) != set(KEYS):
                raise RatingError("Score every category.")
            fr = {}
            for k in KEYS:
                v = float(scores[k])
                if not 1 <= v <= 5:
                    raise RatingError("Scores run from 1 to 5.")
                fr[k] = v / 5
            g = None
            if gut is not None:
                if not 1 <= float(gut) <= 5:
                    raise RatingError("The gut score runs from 1 to 5.")
                g = float(gut) / 5
            self.db.x("INSERT INTO ratings(show_id,mode,scores,overall,gut,created_at) VALUES(?,?,?,?,?,?)",
                      (show_id, "card", json.dumps(fr), None, g, time.time()))
        elif mode in ("5", "10"):
            top = int(mode)
            if overall is None or not 1 <= float(overall) <= top:
                raise RatingError("The score runs from 1 to %d." % top)
            self.db.x("INSERT INTO ratings(show_id,mode,scores,overall,gut,created_at) VALUES(?,?,?,?,?,?)",
                      (show_id, mode, None, float(overall) / top, None, time.time()))
        else:
            raise RatingError("Unknown rating style.")
        return self.show_rating(show_id)

    def show_rating(self, show_id):
        rows = self.db.q("SELECT * FROM ratings WHERE show_id=? ORDER BY id DESC", (int(show_id),))

        def out(row):
            r = self._parse(row)
            d = {"id": r["id"], "mode": r["mode"], "final": self.text(self.final(r)),
                 "fraction": self.final(r), "created_at": r["created_at"],
                 "gut": round(r["gut"] * 5) if r["gut"] is not None else None}
            if r["mode"] == "card":
                d["scores"] = {k: round(r["scores"][k] * 5) for k in KEYS}
            return d
        cur = out(rows[0]) if rows else None
        if cur is not None:
            cur["base"] = cur["final"]
            eff = self._effective_for(show_id, self._base_final(self._parse(rows[0])))
            if eff is not None:
                cur["final"], cur["fraction"] = self.text(eff), eff
        return {"current": cur, "history": [out(r) for r in rows[1:]]}

    def _effective_for(self, show_id, base):
        """The score that counts for one show, given its own score (or None)."""
        fracs, prefs, counts, _ = self._season_state(show_id)
        mode, mix = prefs.get(int(show_id), ("off", 50))
        fr = fracs.get(int(show_id), {})
        if mode == "off" or not fr:
            return base
        return self._combine(base, self._season_average(fr, counts.get(int(show_id), {})), mode, mix)

    def current_text(self, show_id):
        row = self.db.q1("SELECT * FROM ratings WHERE show_id=? ORDER BY id DESC LIMIT 1", (int(show_id),))
        base = self._base_final(self._parse(row)) if row else None
        eff = self._effective_for(show_id, base)
        return self.text(eff) if eff is not None else None

    # ------------------------------------------------------------------ comparisons
    def _net(self, scope):
        net = {}
        for c in self.db.q("SELECT * FROM comparisons WHERE scope=?", (scope,)):
            if c["result"] in ("a", "b"):
                win, lose = (c["show_a"], c["show_b"]) if c["result"] == "a" else (c["show_b"], c["show_a"])
                net[win] = net.get(win, 0) + 1
                net[lose] = net.get(lose, 0) - 1
        return net

    def _show_info(self, ids):
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r["id"]: r for r in self.db.q("SELECT id,name,poster_path,genres FROM shows WHERE id IN (%s)" % marks, list(ids))}

    def rankings(self, scope):
        if scope != "overall" and scope not in KEYS:
            raise RatingError("Unknown category.")
        latest = self.latest()
        info = self._show_info(latest.keys())
        net = self._net(scope)
        items, skipped = [], 0
        for sid, r in latest.items():
            v = self.value(r, scope)
            if v is None or sid not in info:
                skipped += 1
                continue
            items.append({"id": sid, "name": info[sid]["name"], "poster_path": info[sid]["poster_path"], "fraction": v,
                          "score": self.scope_text(scope, v), "net": net.get(sid, 0),
                          "seasons": bool(r.get("season_note")) and scope == "overall",
                          "key": v + ARENA_SHIFT * net.get(sid, 0)})
        items.sort(key=lambda x: (-round(x["key"] * 10000), x["name"]))
        for x in items:
            x["moved"] = "up" if x["net"] > 0 else "down" if x["net"] < 0 else None
        return {"scope": scope, "scope_name": "Overall" if scope == "overall" else NAMES[scope],
                "items": items, "skipped": skipped}

    def _implied(self, scope):
        """Returns (implied, beaten_by): implied(a, b) says whether your earlier answers already settle a pair, and
        beaten_by(x) is the set of shows your answers say are better than x.
        If A beat B and B beat C, A against C is settled. 'About the same' joins shows into one group."""
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        rows = self.db.q("SELECT show_a, show_b, result FROM comparisons WHERE scope=?", (scope,))
        for c in rows:
            if c["result"] == "same":
                parent[find(c["show_a"])] = find(c["show_b"])
        beats = {}
        for c in rows:
            if c["result"] in ("a", "b"):
                w, l = (c["show_a"], c["show_b"]) if c["result"] == "a" else (c["show_b"], c["show_a"])
                if find(w) != find(l):
                    beats.setdefault(find(w), set()).add(find(l))
        memo = {}

        def below(root):
            if root not in memo:
                seen, stack = set(), [root]
                while stack:
                    for nxt in beats.get(stack.pop(), ()):
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
                memo[root] = seen
            return memo[root]

        def implied(a, b):
            ra, rb = find(a), find(b)
            return ra == rb or rb in below(ra) or ra in below(rb)

        def beaten_by(x, candidates):
            rx = find(x)
            return {y for y in candidates if find(y) != rx and rx in below(find(y))}
        return implied, beaten_by

    def _all_pairs(self):
        """Every pair worth asking about, by category: (exact_not, gap, a, b). Already-answered and already-settled pairs are left out."""
        latest = self.latest()
        info = self._show_info(latest.keys())
        ids = sorted(i for i in latest if i in info)
        genres = {i: set(json.loads(info[i]["genres"] or "[]")) for i in ids}
        done = {(c["scope"], frozenset((c["show_a"], c["show_b"]))) for c in self.db.q("SELECT * FROM comparisons")}
        same_genre = self.same_genre()
        top_only = self.top_only()
        out = {}
        for scope in ["overall"] + KEYS:
            scale = self.max_display() if scope == "overall" else 5
            implied, beaten_by = self._implied(scope)
            pairs = out[scope] = []
            # only top-scoring shows, sorted by score so only close neighbours are compared
            vals = sorted((v, i) for i in ids for v in [self.value(latest[i], scope)]
                          if v is not None and v >= ARENA_MIN_FRACTION - 1e-9)
            # a show is out of the running for the top spots once enough shows are clearly above it, either by score or by
            # your answers. Pairs between two shows that are both out of the running are not worth asking about.
            contenders = None
            if top_only:
                score = {i: v for v, i in vals}
                members = list(score)
                contenders = set()
                for i in members:
                    clearly = {j for j in members if (score[j] - score[i]) * scale > NEAR_TIE_POINTS + 1e-9}
                    if len(clearly | beaten_by(i, members)) < ARENA_TOP_K:
                        contenders.add(i)
            for x in range(len(vals)):
                for y in range(x + 1, len(vals)):
                    gap = (vals[y][0] - vals[x][0]) * scale
                    if gap > NEAR_TIE_POINTS + 1e-9:
                        break
                    a, b = sorted((vals[x][1], vals[y][1]))
                    if (scope, frozenset((a, b))) in done:
                        continue
                    if same_genre and not (genres[a] & genres[b]):
                        continue
                    if implied(a, b):
                        continue
                    if contenders is not None and a not in contenders and b not in contenders:
                        continue
                    pairs.append((gap >= 1e-6, gap, a, b))
        return out, latest, info

    @staticmethod
    def _questions(pairs):
        """A realistic number of questions, not the number of pairs. Shows that are tied form groups, and putting a group
        of m shows in order takes about log2(m!) comparisons, because each answer settles other pairs too."""
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for p in pairs:
            parent[find(p[-2])] = find(p[-1])
        sizes = {}
        for x in list(parent):
            r = find(x)
            sizes[r] = sizes.get(r, 0) + 1
        return min(len(pairs), sum(math.ceil(math.log2(math.factorial(m))) for m in sizes.values()))

    def _scope_priority(self, scope):
        return 4 if scope == "overall" else self.weights()[scope]

    def _is_default(self, scope):
        """The arena opens on Overall. Each category is one tap away, with the ones you care about most listed first."""
        return scope == "overall"

    def _pairs(self, scope=None):
        """Pairs for one category, or (with no category) for Overall. Returns tuples (exact_not, gap, scope, a, b), best first."""
        allp, latest, info = self._all_pairs()
        if scope in (None, "all"):
            scopes = [s for s in allp if self._is_default(s)]
        elif scope in allp:
            scopes = [scope]
        else:
            raise RatingError("Unknown category.")
        out = [(e, g, s, a, b) for s in scopes for (e, g, a, b) in allp[s]]
        out.sort(key=lambda t: (-self._scope_priority(t[2]), t[0], t[1], t[3], t[4]))
        return out, latest, info, allp

    def _matchup(self, pair, latest, info):
        exact_not, gap, scope, a, b = pair
        va, vb = self.value(latest[a], scope), self.value(latest[b], scope)
        return {"scope": scope, "scope_name": "Overall" if scope == "overall" else NAMES[scope],
                "exact": not exact_not, "gap": abs(va - vb) * (self.max_display() if scope == "overall" else 5),
                "a": {"id": a, "name": info[a]["name"], "poster_path": info[a]["poster_path"], "score": self.scope_text(scope, va)},
                "b": {"id": b, "name": info[b]["name"], "poster_path": info[b]["poster_path"], "score": self.scope_text(scope, vb)}}

    def matchups(self, scope=None):
        pairs, latest, info, _ = self._pairs(scope)
        return [self._matchup(p, latest, info) for p in pairs]

    def arena(self, scope=None):
        pairs, latest, info, allp = self._pairs(scope)
        n = self.db.q1("SELECT COUNT(*) n FROM comparisons")["n"]
        qs = {s: self._questions(allp[s]) for s in allp}
        by_scope = [{"scope": s, "name": "Overall" if s == "overall" else NAMES[s], "count": len(allp[s]),
                     "questions": qs[s], "default": self._is_default(s),
                     "weight": 4 if s == "overall" else self.weights()[s]} for s in allp]
        view = [s for s in allp if (self._is_default(s) if scope in (None, "all") else s == scope)]
        return {"next": self._matchup(pairs[0], latest, info) if pairs else None, "remaining": len(pairs),
                "questions": sum(qs[s] for s in view), "scope": scope or "all",
                "default_total": sum(c["count"] for c in by_scope if c["default"]),
                "default_total_q": sum(c["questions"] for c in by_scope if c["default"]),
                "by_scope": by_scope, "settled": n, "same_genre": self.same_genre(), "top_only": self.top_only()}

    def compare(self, scope, a, b, result, view=None):
        if scope != "overall" and scope not in KEYS:
            raise RatingError("Unknown category.")
        if result not in ("a", "b", "same", "skip"):
            raise RatingError("Unknown answer.")
        self.db.x("INSERT INTO comparisons(scope,show_a,show_b,result,created_at) VALUES(?,?,?,?,?)",
                  (scope, int(a), int(b), result, time.time()))
        return self.arena(view)

    # ------------------------------------------------------------------ rating seasons
    def _season_numbers(self, show_id):
        return {r["season_number"]: r["n"] for r in self.db.q(
            "SELECT season_number, COUNT(*) n FROM episodes WHERE show_id=? AND season_number>=1 GROUP BY season_number",
            (int(show_id),))}

    def rate_seasons(self, show_id, scores):
        """scores: {season number: score}. Only changed scores are recorded, so re-saving adds nothing to the history."""
        show_id = int(show_id)
        seasons = self._season_numbers(show_id)
        if not seasons:
            raise RatingError("That show has no seasons yet.")
        top = self.season_scale()
        fracs = self._season_state(show_id)[0].get(show_id, {})
        todo = []
        for k, v in (scores or {}).items():
            n = int(k)
            if n not in seasons:
                raise RatingError("Season %d does not exist." % n)
            if v is None:
                continue
            v = float(v)
            if not 1 <= v <= top:
                raise RatingError("Season scores run from 1 to %d." % top)
            if n not in fracs or abs(fracs[n] - v / top) > 1e-9:
                todo.append((show_id, n, top, v, v / top, time.time()))
        with self.db.tx():
            for row in todo:
                self.db.x("INSERT INTO season_ratings(show_id,season_number,scale,score,fraction,created_at) VALUES(?,?,?,?,?,?)", row)
        return self.season_info(show_id)

    def save_season_prefs(self, show_id, mode, mix=None):
        if mode not in SEASON_MODES:
            raise RatingError("Unknown choice.")
        cur = self.db.q1("SELECT mix FROM season_prefs WHERE show_id=?", (int(show_id),))
        mix = int(mix) if mix is not None else (cur["mix"] if cur else 50)
        if not 0 <= mix <= 100:
            raise RatingError("The mix runs from 0 to 100 percent.")
        self.db.x("""INSERT INTO season_prefs(show_id,mode,mix) VALUES(?,?,?)
                     ON CONFLICT(show_id) DO UPDATE SET mode=excluded.mode, mix=excluded.mix""", (int(show_id), mode, mix))
        return self.season_info(show_id)

    def compare_seasons(self, show_id, a, b, result):
        """Which of two seasons was better. Stored with the arena's answers, under a scope of its own."""
        show_id, a, b = int(show_id), int(a), int(b)
        seasons = self._season_numbers(show_id)
        if a not in seasons or b not in seasons or a == b:
            raise RatingError("Pick two different seasons of this show.")
        if result not in ("a", "b", "same", "skip"):
            raise RatingError("Unknown answer.")
        self.db.x("INSERT INTO comparisons(scope,show_a,show_b,result,created_at) VALUES(?,?,?,?,?)",
                  ("season:%d" % show_id, a, b, result, time.time()))
        return self.season_info(show_id)

    def season_info(self, show_id):
        show_id = int(show_id)
        counts = self._season_numbers(show_id)
        fracs, prefs, _, _ = self._season_state(show_id)
        fr = fracs.get(show_id, {})
        mode, mix = prefs.get(show_id, ("off", 50))
        row = self.db.q1("SELECT * FROM ratings WHERE show_id=? ORDER BY id DESC LIMIT 1", (show_id,))
        base = self._base_final(self._parse(row)) if row else None
        avg = self._season_average(fr, counts)
        eff = self._combine(base, avg, mode, mix)
        top = self.season_scale()

        # best and weakest season: by score, then by your answers about which of the tied seasons was better
        scope = "season:%d" % show_id
        net = self._net(scope)
        best, worst, pending = [], [], []
        if len(fr) >= 2:
            hi, lo = max(fr.values()), min(fr.values())
            tied_top = sorted(s for s, f in fr.items() if abs(f - hi) < 1e-9)
            tied_low = sorted(s for s, f in fr.items() if abs(f - lo) < 1e-9)
            top_net = max(net.get(s, 0) for s in tied_top)
            low_net = min(net.get(s, 0) for s in tied_low)
            best = [s for s in tied_top if net.get(s, 0) == top_net]
            worst = [s for s in tied_low if net.get(s, 0) == low_net]
            if len(best) == len(fr):          # every season is level and your answers have not separated any
                best = []
            if len(worst) == len(fr):
                worst = []
            if len(tied_top) >= 2:
                implied, _ = self._implied(scope)
                done = {frozenset((c["show_a"], c["show_b"])) for c in self.db.q(
                    "SELECT show_a, show_b FROM comparisons WHERE scope=?", (scope,))}
                for i, a in enumerate(tied_top):
                    for b in tied_top[i + 1:]:
                        if frozenset((a, b)) not in done and not implied(a, b):
                            pending.append([a, b])
        rated = len(fr)
        return {
            "show_id": show_id, "multi": len(counts) >= 2, "scale": top, "mode": mode, "mix": mix,
            "seasons": [{"season": n, "episodes": counts[n],
                         "score": round(fr[n] * top) if n in fr else None,
                         "fraction": fr.get(n), "text": self.text(fr[n]) if n in fr else None,
                         "best": n in best, "weakest": n in worst} for n in sorted(counts)],
            "rated": rated, "best": best, "weakest": worst, "pending": pending,
            "base_fraction": base, "base_text": self.text(base) if base is not None else None,
            "avg_fraction": avg, "avg_text": self.text(avg) if avg is not None else None,
            "effective_fraction": eff, "effective_text": self.text(eff) if eff is not None else None,
            "counts_toward_show": mode != "off" and avg is not None,
        }

    def season_trends(self):
        """How your shows age: first against latest rated season, and the average score by season number."""
        fracs, _, _, _ = self._season_state()
        names = {r["id"] for r in self.db.q("SELECT id FROM shows")}
        better = same = worse = 0
        by_number = {}
        for sid, fr in fracs.items():
            if sid not in names or len(fr) < 2:
                continue
            nums = sorted(fr)
            d = fr[nums[-1]] - fr[nums[0]]
            if d > 0.099:
                better += 1
            elif d < -0.099:
                worse += 1
            else:
                same += 1
            for n in nums:
                by_number.setdefault(n, []).append(fr[n])
        top = self.season_scale()
        return {"shows": better + same + worse, "improved": better, "held": same, "declined": worse,
                "by_number": [[n, round(sum(v) / len(v) * top, 2), len(v)] for n, v in sorted(by_number.items())][:8],
                "scale": top}

    # ------------------------------------------------------------------ favourites
    def favourite_ids(self, show_id):
        return {r["episode_id"] for r in self.db.q("SELECT episode_id FROM favourites WHERE show_id=?", (int(show_id),))}

    def toggle_favourite(self, episode_id, show_id):
        if self.db.q1("SELECT 1 FROM favourites WHERE episode_id=?", (int(episode_id),)):
            self.db.x("DELETE FROM favourites WHERE episode_id=?", (int(episode_id),))
            return False
        self.db.x("INSERT INTO favourites(episode_id,show_id,added_at) VALUES(?,?,?)",
                  (int(episode_id), int(show_id), time.time()))
        return True

    def favourites(self, hide_titles):
        rows = self.db.q("""SELECT f.episode_id, f.show_id, e.season_number s, e.episode_number n, e.name en,
                            sh.name shn, sh.poster_path pp FROM favourites f
                            LEFT JOIN episodes e ON e.id=f.episode_id LEFT JOIN shows sh ON sh.id=f.show_id
                            ORDER BY f.added_at DESC""")
        out = []
        for r in rows:
            hide = hide_titles(r["show_id"])
            out.append({"episode_id": r["episode_id"], "show_id": r["show_id"], "show": r["shn"] or "Show %d" % r["show_id"],
                        "poster_path": r["pp"],
                        "label": ("S%dE%d" % (r["s"], r["n"])) if r["s"] is not None else "episode no longer listed",
                        "name": None if (hide or r["en"] is None) else r["en"]})
        return out
