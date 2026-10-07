"""Local backups: rotating database snapshots plus a portable JSON export."""
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("tally.backup")

DEFAULT_KEEP = 10
LAUNCH_INTERVAL_S = 6 * 3600


class BackupManager:
    def __init__(self, db, default_dir):
        self.db = db
        self.default_dir = Path(default_dir)
        self.last_write_mark = db.writes

    # ---- locations ----
    def folder(self) -> Path:
        custom = self.db.get_setting("backup_dir")
        p = Path(custom) if custom else self.default_dir / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def keep(self) -> int:
        try:
            return max(3, int(self.db.get_setting("backup_keep", DEFAULT_KEEP)))
        except (TypeError, ValueError):
            return DEFAULT_KEEP

    def set_folder(self, path):
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".tally-write-test"
        probe.write_text("ok")
        probe.unlink()
        self.db.set_setting("backup_dir", str(p))

    # ---- snapshots ----
    def snapshot(self, reason="manual") -> Path:
        name = "tally-%s-%s.db" % (datetime.now().strftime("%Y%m%d-%H%M%S"), reason)
        dest = self.folder() / name
        n = 1
        while dest.exists():
            n += 1
            dest = self.folder() / name.replace(".db", "-%d.db" % n)
        out = sqlite3.connect(str(dest))
        try:
            with self.db.lock:
                self.db.conn.backup(out)
        finally:
            out.close()
        self.last_write_mark = self.db.writes
        self.prune()
        log.info("backup written: %s", dest.name)
        return dest

    def list(self):
        rows = []
        for f in self.folder().glob("tally-*.db"):
            st = f.stat()
            rows.append({"name": f.name, "size": st.st_size, "modified": st.st_mtime})
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return rows

    def prune(self):
        for r in self.list()[self.keep():]:
            try:
                (self.folder() / r["name"]).unlink()
            except OSError:
                pass

    def on_launch(self):
        """Snapshot at start-up if the newest backup is older than a few hours."""
        try:
            has_data = self.db.q1("SELECT 1 FROM user_shows LIMIT 1") is not None
            latest = self.list()
            if has_data and (not latest or time.time() - latest[0]["modified"] > LAUNCH_INTERVAL_S):
                self.snapshot("launch")
        except Exception:
            log.exception("launch backup failed")

    def on_exit(self):
        """Snapshot on close, but only if something changed since the last backup."""
        try:
            if self.db.writes != self.last_write_mark and self.db.q1("SELECT 1 FROM user_shows LIMIT 1"):
                self.snapshot("exit")
        except Exception:
            log.exception("exit backup failed")

    # ---- restore ----
    def restore(self, name):
        src_path = self.folder() / os.path.basename(name)
        if not src_path.exists():
            raise ValueError("That backup file was not found.")
        src = sqlite3.connect(str(src_path))
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not ok or not {"watch_events", "user_shows"} <= tables:
                raise ValueError("That file is not a valid backup from The Counting.")
            keep = {k: self.db.get_setting(k) for k in ("tmdb_key", "backup_dir", "backup_keep", "secure_dns", "theme")}
            self.snapshot("before-restore")
            with self.db.lock:
                src.backup(self.db.conn)
                self.db.migrate()
                for k, v in keep.items():  # settings such as your API key stay as they are now
                    if v is not None:
                        self.db.set_setting(k, v)
        finally:
            src.close()

    # ---- portable export / import ----
    def export_json(self):
        db = self.db
        data = {
            "format": "tally-export", "version": 2, "exported_at": time.time(),
            "user_shows": [dict(r) for r in db.q("SELECT * FROM user_shows")],
            "overrides": [dict(r) for r in db.q("SELECT * FROM overrides")],
            "watch_events": [dict(r) for r in db.q("SELECT * FROM watch_events ORDER BY id")],
            "ratings": [dict(r) for r in db.q("SELECT * FROM ratings ORDER BY id")],
            "comparisons": [dict(r) for r in db.q("SELECT * FROM comparisons ORDER BY id")],
            "favourites": [dict(r) for r in db.q("SELECT * FROM favourites")],
            "dismissed": [dict(r) for r in db.q("SELECT * FROM dismissed")],
            "season_ratings": [dict(r) for r in db.q("SELECT * FROM season_ratings ORDER BY id")],
            "season_prefs": [dict(r) for r in db.q("SELECT * FROM season_prefs")],
            "rating_settings": {k: db.get_setting(k) for k in ("rating_mode", "rating_weights", "arena_same_genre", "arena_top_only")
                                if db.get_setting(k) is not None},
        }
        folder = self.default_dir / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("the-counting-export-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return path

    def import_json(self, data):
        if not isinstance(data, dict) or data.get("format") != "tally-export":
            raise ValueError("That file is not an export from The Counting.")
        if data.get("version") not in (1, 2):
            raise ValueError("That export was made by a newer version of The Counting.")
        self.snapshot("before-import")
        db = self.db
        with db.tx():
            db.x("DELETE FROM user_shows")
            db.x("DELETE FROM overrides")
            db.x("DELETE FROM watch_events")
            for t in ("ratings", "comparisons", "favourites", "dismissed", "season_ratings", "season_prefs"):
                db.x("DELETE FROM " + t)
            for r in data.get("user_shows", []):
                db.x("INSERT INTO user_shows(show_id,status,source,added_at,updated_at) VALUES(?,?,?,?,?)",
                     (r["show_id"], r["status"], r.get("source", "manual"), r["added_at"], r["updated_at"]))
            for r in data.get("overrides", []):
                db.x("INSERT INTO overrides(show_id,hide_titles,absolute_numbering,include_specials) VALUES(?,?,?,?)",
                     (r["show_id"], r.get("hide_titles", 0), r.get("absolute_numbering", 0),
                      r.get("include_specials", 0)))
            for r in data.get("watch_events", []):
                db.x("INSERT INTO watch_events(id,episode_id,show_id,type,source,ts) VALUES(?,?,?,?,?,?)",
                     (r["id"], r["episode_id"], r["show_id"], r["type"], r["source"], r.get("ts")))
            for r in data.get("ratings", []):
                db.x("INSERT INTO ratings(id,show_id,mode,scores,overall,gut,created_at) VALUES(?,?,?,?,?,?,?)",
                     (r["id"], r["show_id"], r["mode"], r.get("scores"), r.get("overall"), r.get("gut"), r["created_at"]))
            for r in data.get("comparisons", []):
                db.x("INSERT INTO comparisons(id,scope,show_a,show_b,result,created_at) VALUES(?,?,?,?,?,?)",
                     (r["id"], r["scope"], r["show_a"], r["show_b"], r["result"], r["created_at"]))
            for r in data.get("season_ratings", []):
                db.x("INSERT INTO season_ratings(id,show_id,season_number,scale,score,fraction,created_at) VALUES(?,?,?,?,?,?,?)",
                     (r["id"], r["show_id"], r["season_number"], r["scale"], r["score"], r["fraction"], r["created_at"]))
            for r in data.get("season_prefs", []):
                db.x("INSERT INTO season_prefs(show_id,mode,mix) VALUES(?,?,?)", (r["show_id"], r["mode"], r["mix"]))
            for r in data.get("favourites", []):
                db.x("INSERT INTO favourites(episode_id,show_id,added_at) VALUES(?,?,?)",
                     (r["episode_id"], r["show_id"], r["added_at"]))
            for r in data.get("dismissed", []):
                db.x("INSERT INTO dismissed(show_id,dismissed_at) VALUES(?,?)", (r["show_id"], r["dismissed_at"]))
            for k, v in (data.get("rating_settings") or {}).items():
                if k in ("rating_mode", "rating_weights", "arena_same_genre", "arena_top_only"):
                    db.x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        return {"shows": len(data.get("user_shows", [])), "events": len(data.get("watch_events", [])),
                "ratings": len(data.get("ratings", []))}
