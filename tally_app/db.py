"""SQLite storage with simple versioned migrations."""
import sqlite3
import threading
from contextlib import contextmanager

# Each entry upgrades the database by one version. Never edit an old entry; add a new one.
MIGRATIONS = [
    """
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);

    -- Layer 1: TMDB cache (can always be re-fetched)
    CREATE TABLE shows(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, overview TEXT, tmdb_status TEXT, type TEXT,
        poster_path TEXT, backdrop_path TEXT, genres TEXT, networks TEXT, first_air_date TEXT,
        in_production INTEGER, runtime INTEGER, cast_json TEXT, synced_at REAL);
    CREATE TABLE seasons(
        show_id INTEGER NOT NULL, season_number INTEGER NOT NULL, name TEXT, episode_count INTEGER,
        air_date TEXT, poster_path TEXT, PRIMARY KEY(show_id, season_number));
    CREATE TABLE episodes(
        id INTEGER PRIMARY KEY, show_id INTEGER NOT NULL, season_number INTEGER NOT NULL,
        episode_number INTEGER NOT NULL, name TEXT, overview TEXT, air_date TEXT, runtime INTEGER,
        still_path TEXT, episode_type TEXT);
    CREATE INDEX idx_ep_show ON episodes(show_id, season_number, episode_number);

    -- Layer 2: overrides (small, manual)
    CREATE TABLE overrides(
        show_id INTEGER PRIMARY KEY, hide_titles INTEGER NOT NULL DEFAULT 0,
        absolute_numbering INTEGER NOT NULL DEFAULT 0, include_specials INTEGER NOT NULL DEFAULT 0);

    -- Layer 3: your data (protect this)
    CREATE TABLE user_shows(
        show_id INTEGER PRIMARY KEY, status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
        added_at REAL NOT NULL, updated_at REAL NOT NULL);
    -- Append-only. Undoing a mark adds an 'undo' row; nothing is ever deleted.
    -- show_id is stored on the event so history survives even if TMDB drops an episode.
    CREATE TABLE watch_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id INTEGER NOT NULL, show_id INTEGER NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('watch','undo')), source TEXT NOT NULL, ts REAL);
    CREATE INDEX idx_ev_ep ON watch_events(episode_id);
    CREATE INDEX idx_ev_show ON watch_events(show_id);
    """,
    # Version 2: ratings, comparisons, favourites, recommendations
    """
    -- Ratings are a history. The newest row per show is the current rating; nothing is overwritten.
    -- scores holds one 0-1 fraction per criterion (scorecard); overall holds a 0-1 fraction (simple styles).
    CREATE TABLE ratings(
        id INTEGER PRIMARY KEY AUTOINCREMENT, show_id INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('card','5','10')), scores TEXT, overall REAL, gut REAL,
        created_at REAL NOT NULL);
    CREATE INDEX idx_rat_show ON ratings(show_id);
    CREATE TABLE comparisons(
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, show_a INTEGER NOT NULL, show_b INTEGER NOT NULL,
        result TEXT NOT NULL CHECK(result IN ('a','b','same','skip')), created_at REAL NOT NULL);
    CREATE TABLE favourites(episode_id INTEGER PRIMARY KEY, show_id INTEGER NOT NULL, added_at REAL NOT NULL);
    CREATE TABLE dismissed(show_id INTEGER PRIMARY KEY, dismissed_at REAL NOT NULL);
    -- recommendation cache (can always be re-fetched)
    CREATE TABLE genres(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE candidates(
        id INTEGER PRIMARY KEY, name TEXT, overview TEXT, poster_path TEXT, first_air_date TEXT, genre_ids TEXT);
    CREATE TABLE rec_links(seed_id INTEGER NOT NULL, rec_id INTEGER NOT NULL, PRIMARY KEY(seed_id, rec_id));
    CREATE TABLE rec_fetched(seed_id INTEGER PRIMARY KEY, fetched_at REAL NOT NULL);
    """,
    # Version 3: season ratings. Like show ratings, a history: the newest row per show and season is current.
    """
    CREATE TABLE season_ratings(
        id INTEGER PRIMARY KEY AUTOINCREMENT, show_id INTEGER NOT NULL, season_number INTEGER NOT NULL,
        scale INTEGER NOT NULL CHECK(scale IN (5, 10)), score REAL NOT NULL, fraction REAL NOT NULL,
        created_at REAL NOT NULL);
    CREATE INDEX idx_srat ON season_ratings(show_id, season_number);
    -- Whether season scores count toward a show's score. Off unless the person chooses otherwise.
    CREATE TABLE season_prefs(
        show_id INTEGER PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'off' CHECK(mode IN ('off', 'blend', 'seasons')),
        mix INTEGER NOT NULL DEFAULT 50);
    """,
    # Version 4: phones and other browsers paired to use this computer's copy over the home network.
    # Only a hash of each device's secret is stored.
    """
    CREATE TABLE paired_devices(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL, last_seen REAL NOT NULL);
    """,
]


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.writes = 0
        self.conn = self._connect()
        self.migrate()

    def _connect(self):
        c = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def migrate(self):
        with self.lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for i in range(version, len(MIGRATIONS)):
                try:
                    self.conn.executescript("BEGIN;" + MIGRATIONS[i] + "PRAGMA user_version=%d;COMMIT;" % (i + 1))
                except Exception:
                    try:
                        self.conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise

    def q(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def q1(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.writes += 1
            return cur

    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")
                self.writes += 1

    def get_setting(self, key, default=None):
        row = self.q1("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, value))

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
