"""Fetches show data from TMDB into the local cache."""
import json
import logging
import threading
import time

from .tmdb import TMDBError

log = logging.getLogger("tally.sync")

SEASONS_PER_REQUEST = 15  # TMDB allows about 20 appended items per request; stay under it
RETURNING_REFRESH_S = 24 * 3600
ENDED_REFRESH_S = 30 * 24 * 3600


def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def sync_show(db, tmdb, show_id):
    """Fetch a show, all its seasons and episodes, and store them. Watch history is never touched."""
    d = tmdb.get("/tv/%d" % show_id, language="en-US")
    numbers = sorted({s["season_number"] for s in (d.get("seasons") or []) if s.get("season_number") is not None})
    payloads, credits, first = {}, None, True
    for chunk in _chunks(numbers, SEASONS_PER_REQUEST):
        keys = ["season/%d" % n for n in chunk] + (["aggregate_credits"] if first else [])
        try:
            r = tmdb.get("/tv/%d" % show_id, append_to_response=",".join(keys), language="en-US")
        except TMDBError as e:
            if e.kind in ("auth", "network", "nokey", "rate"):
                raise
            r = {}
        for n in chunk:
            p = r.get("season/%d" % n)
            if p is None:  # fall back to one request per season
                try:
                    p = tmdb.get("/tv/%d/season/%d" % (show_id, n), language="en-US")
                except TMDBError as e:
                    if e.kind != "notfound":
                        raise
                    p = None
            payloads[n] = p
        if first:
            credits = r.get("aggregate_credits")
            first = False

    runtimes = [e.get("runtime") for p in payloads.values() if p for e in (p.get("episodes") or []) if e.get("runtime")]
    run = round(sum(runtimes) / len(runtimes)) if runtimes else None
    if not run:
        erl = d.get("episode_run_time") or []
        run = erl[0] if erl else 40
    cast = []
    for c in ((credits or {}).get("cast") or [])[:12]:
        roles = c.get("roles") or []
        cast.append({"name": c.get("name"), "character": roles[0].get("character") if roles else None,
                     "episodes": c.get("total_episode_count")})

    with db.tx():
        db.x("""INSERT INTO shows(id,name,overview,tmdb_status,type,poster_path,backdrop_path,genres,networks,
                first_air_date,in_production,runtime,cast_json,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, overview=excluded.overview,
                tmdb_status=excluded.tmdb_status, type=excluded.type, poster_path=excluded.poster_path,
                backdrop_path=excluded.backdrop_path, genres=excluded.genres, networks=excluded.networks,
                first_air_date=excluded.first_air_date, in_production=excluded.in_production,
                runtime=excluded.runtime, cast_json=excluded.cast_json, synced_at=excluded.synced_at""",
             (show_id, d.get("name") or "Untitled", d.get("overview"), d.get("status"), d.get("type"),
              d.get("poster_path"), d.get("backdrop_path"),
              json.dumps([g["name"] for g in d.get("genres") or []]),
              json.dumps([n["name"] for n in d.get("networks") or []]),
              d.get("first_air_date"), 1 if d.get("in_production") else 0, run, json.dumps(cast), time.time()))
        db.x("DELETE FROM seasons WHERE show_id=?", (show_id,))
        for s in d.get("seasons") or []:
            db.x("INSERT INTO seasons VALUES(?,?,?,?,?,?)",
                 (show_id, s["season_number"], s.get("name"), s.get("episode_count"), s.get("air_date"),
                  s.get("poster_path")))
        seen = set()
        for n, p in payloads.items():
            for e in (p or {}).get("episodes") or []:
                seen.add(e["id"])
                db.x("""INSERT INTO episodes(id,show_id,season_number,episode_number,name,overview,air_date,runtime,
                        still_path,episode_type) VALUES(?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET show_id=excluded.show_id, season_number=excluded.season_number,
                        episode_number=excluded.episode_number, name=excluded.name, overview=excluded.overview,
                        air_date=excluded.air_date, runtime=excluded.runtime, still_path=excluded.still_path,
                        episode_type=excluded.episode_type""",
                     (e["id"], show_id, e.get("season_number", n), e.get("episode_number"), e.get("name"),
                      e.get("overview"), e.get("air_date"), e.get("runtime"), e.get("still_path"),
                      e.get("episode_type")))
        # Drop cached episodes TMDB no longer lists. Watch events are never deleted.
        # If a season failed to load (payload None) keep its old episodes.
        loaded = [n for n, p in payloads.items() if p is not None]
        if loaded:
            marks = ",".join("?" * len(loaded))
            old = db.q("SELECT id FROM episodes WHERE show_id=? AND season_number IN (%s)" % marks,
                       [show_id] + loaded)
            for row in old:
                if row["id"] not in seen:
                    db.x("DELETE FROM episodes WHERE id=?", (row["id"],))


def needs_refresh(row, now=None):
    now = now or time.time()
    age = now - (row["synced_at"] or 0)
    returning = (row["tmdb_status"] not in ("Ended", "Canceled")) or row["in_production"]
    return age > (RETURNING_REFRESH_S if returning else ENDED_REFRESH_S)


class Refresher(threading.Thread):
    """Background thread: fetches data for shows that have none yet, and refreshes stale ones."""

    def __init__(self, db, tmdb, has_key):
        super().__init__(daemon=True, name="tally-refresher")
        self.db, self.tmdb, self.has_key = db, tmdb, has_key
        self.stop_event = threading.Event()
        self.pending = 0

    def work_list(self):
        missing = [r["show_id"] for r in self.db.q(
            "SELECT u.show_id FROM user_shows u LEFT JOIN shows s ON s.id=u.show_id WHERE s.id IS NULL")]
        stale = [r["id"] for r in self.db.q(
            "SELECT s.id, s.tmdb_status, s.in_production, s.synced_at FROM shows s "
            "JOIN user_shows u ON u.show_id=s.id") if needs_refresh(r)]
        return missing + stale

    def run(self):
        self.stop_event.wait(5)
        while not self.stop_event.is_set():
            try:
                if self.has_key():
                    todo = self.work_list()
                    self.pending = len(todo)
                    for sid in todo:
                        if self.stop_event.is_set():
                            break
                        try:
                            sync_show(self.db, self.tmdb, sid)
                        except TMDBError as e:
                            log.warning("sync %s failed: %s", sid, e.message)
                            if e.kind in ("auth", "network", "nokey"):
                                break
                        except Exception:
                            log.exception("sync %s crashed", sid)
                        self.pending = max(0, self.pending - 1)
                    self.pending = 0
            except Exception:
                log.exception("refresher loop error")
            self.stop_event.wait(300)

    def stop(self):
        self.stop_event.set()
