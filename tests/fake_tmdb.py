"""A tiny fake TMDB used by the tests, shaped like the real v3 responses."""
import json
import re
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

GOOD_KEY = "goodkey123"
CALLS = []


def d(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def make_show(sid, name, status, seasons, specials=0, genres=("Drama",), finale=True):
    """seasons: list of (episode_count, aired_count). Aired ones get past dates, the rest future dates."""
    show = {"id": sid, "name": name, "overview": name + " overview", "status": status, "type": "Scripted",
            "poster_path": "/poster%d.jpg" % sid, "backdrop_path": "/back%d.jpg" % sid,
            "genres": [{"id": i, "name": g} for i, g in enumerate(genres)], "networks": [{"name": "Net"}],
            "first_air_date": "2020-01-01", "in_production": status not in ("Ended", "Canceled"),
            "episode_run_time": [45], "seasons": [], "_eps": {}}
    eid = sid * 1000
    nums = ([0] if specials else []) + list(range(1, len(seasons) + 1))
    for n in nums:
        count, aired = (specials, specials) if n == 0 else seasons[n - 1]
        eps = []
        for e in range(1, count + 1):
            eid += 1
            past = e <= aired
            eps.append({"id": eid, "season_number": n, "episode_number": e, "name": "%s S%dE%d" % (name, n, e),
                        "overview": "Synopsis of %d-%d" % (n, e), "air_date": d(-400 + e) if past else d(30 + e),
                        "runtime": 45 if n else 20, "still_path": "/still%d.jpg" % eid,
                        "episode_type": "finale" if (n and e == count and finale) else "standard"})
        show["seasons"].append({"season_number": n, "name": "Season %d" % n, "episode_count": count,
                                "air_date": eps[0]["air_date"] if eps else None, "poster_path": None})
        show["_eps"][n] = {"season_number": n, "episodes": eps}
    return show


SHOWS = {s["id"]: s for s in [
    make_show(100, "Harbour Lights", "Ended", [(4, 4), (4, 4)], specials=2, genres=("Drama", "Mystery")),
    make_show(200, "Paper Kingdoms", "Returning Series", [(4, 4), (4, 2)], genres=("Drama",), finale=False),
    make_show(300, "Very Long Show", "Ended", [(2, 2)] * 20),
    make_show(400, "Night Ferry", "Returning Series", [(6, 2)], genres=("Thriller",)),
    make_show(500, "Cold Meridian", "Ended", [(3, 3)], genres=("Drama", "Thriller")),
    make_show(501, "Velvet Ledger", "Ended", [(3, 3)], genres=("Drama",)),
    make_show(502, "Tin Horizon", "Ended", [(3, 3)], genres=("Sci-Fi",)),
    make_show(503, "Orchard Street", "Ended", [(3, 3)], genres=("Comedy",)),
]}
GENRES = [{"id": 18, "name": "Drama"}, {"id": 9648, "name": "Mystery"}, {"id": 53, "name": "Thriller"},
          {"id": 878, "name": "Sci-Fi"}, {"id": 35, "name": "Comedy"}]
GENRE_ID = {g["name"]: g["id"] for g in GENRES}
# which shows TMDB recommends after each show
RECS = {100: [500, 501], 200: [501, 503], 300: [502], 400: [502], 500: [], 501: [], 502: [], 503: []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        CALLS.append(self.path)
        if u.path.startswith("/t/p/"):  # image host
            body = b"\x89PNG fake"
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if q.get("api_key") != GOOD_KEY and self.headers.get("Authorization") != "Bearer " + "x" * 70:
            return self._send(401, {"status_code": 7})
        p = u.path[len("/3"):]
        if p == "/configuration":
            return self._send(200, {"images": {}})
        if p == "/search/tv":
            hits = [s for s in SHOWS.values() if q.get("query", "").lower() in s["name"].lower()]
            return self._send(200, {"results": [{"id": s["id"], "name": s["name"], "first_air_date": "2020-01-01",
                                                 "overview": s["overview"], "poster_path": s["poster_path"]}
                                                for s in hits]})
        m = re.fullmatch(r"/tv/(\d+)", p)
        if m and int(m.group(1)) in SHOWS:
            s = SHOWS[int(m.group(1))]
            out = {k: v for k, v in s.items() if not k.startswith("_")}
            for part in (q.get("append_to_response") or "").split(","):
                if part.startswith("season/"):
                    n = int(part.split("/")[1])
                    if n in s["_eps"]:
                        out[part] = s["_eps"][n]
                elif part == "aggregate_credits":
                    out[part] = {"cast": [{"name": "Ada Actor", "total_episode_count": 8,
                                           "roles": [{"character": "Lead"}]}]}
            if len((q.get("append_to_response") or "").split(",")) > 20 and q.get("append_to_response"):
                return self._send(400, {"status_message": "too many"})
            return self._send(200, out)
        if p == "/genre/tv/list":
            return self._send(200, {"genres": GENRES})
        m = re.fullmatch(r"/tv/(\d+)/recommendations", p)
        if m and int(m.group(1)) in SHOWS:
            res = []
            for rid in RECS.get(int(m.group(1)), []):
                r = SHOWS[rid]
                res.append({"id": rid, "name": r["name"], "overview": r["overview"], "poster_path": r["poster_path"],
                            "first_air_date": "2021-05-05", "genre_ids": [GENRE_ID.get(g["name"], 0) for g in r["genres"]]})
            return self._send(200, {"results": res})
        m = re.fullmatch(r"/tv/(\d+)/season/(\d+)", p)
        if m and int(m.group(1)) in SHOWS and int(m.group(2)) in SHOWS[int(m.group(1))]["_eps"]:
            return self._send(200, SHOWS[int(m.group(1))]["_eps"][int(m.group(2))])
        return self._send(404, {"status_code": 34})


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
