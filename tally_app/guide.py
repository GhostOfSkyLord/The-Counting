"""First-time guidance: the tour, the getting-started checklist and one-time tips.

This only remembers what has already been shown. Someone who already has shows when this first runs is not treated
as new: they are not offered the tour, and their tips and checklist are marked as seen (they can bring all of it back
from Settings). A phone keeps its own copy of this state in the browser, so the computer's is not changed by it.
"""
import json

from .service import UserError

TIPS = ("ratings", "arena", "discover", "stats", "show")
VISITS = ("arena", "discover")
TOUR = ("", "done", "skipped")
CHECKLIST = ("", "dismissed")


def fresh():
    return {"tour": "", "checklist": "", "tips": [], "visited": []}


class Guide:
    def __init__(self, db):
        self.db = db

    def existing_data(self):
        q = self.db.q1
        return bool(q("SELECT COUNT(*) n FROM user_shows")["n"] or q("SELECT COUNT(*) n FROM watch_events")["n"]
                    or q("SELECT COUNT(*) n FROM ratings")["n"])

    def state(self):
        raw = self.db.get_setting("guide")
        if raw:
            try:
                s = json.loads(raw)
                return {**fresh(), **{k: s[k] for k in fresh() if k in s}}
            except ValueError:
                pass
        s = fresh()
        if self.existing_data():          # not a newcomer: nothing to teach unasked
            s = {"tour": "skipped", "checklist": "dismissed", "tips": list(TIPS), "visited": list(VISITS)}
        self._store(s)
        return s

    def _store(self, s):
        self.db.set_setting("guide", json.dumps(s))

    def progress(self, visited=None):
        q = self.db.q1
        v = self.state()["visited"] if visited is None else visited
        return {"added": q("SELECT COUNT(*) n FROM user_shows")["n"] > 0,
                "marked": q("SELECT COUNT(*) n FROM watch_events WHERE type='watch'")["n"] > 0,
                "rated": q("SELECT COUNT(*) n FROM ratings")["n"] > 0,
                "favourite": q("SELECT COUNT(*) n FROM favourites")["n"] > 0,
                "phone": q("SELECT COUNT(*) n FROM paired_devices")["n"] > 0,
                "arena": "arena" in v, "discover": "discover" in v}

    def get(self):
        return {"state": self.state(), "progress": self.progress(), "existing": self.existing_data(),
                "tips": list(TIPS)}

    def save(self, patch):
        s = self.state()
        if patch.get("reset"):
            s = fresh()
        if "tour" in patch:
            if patch["tour"] not in TOUR:
                raise UserError("Unknown tour state.")
            s["tour"] = patch["tour"]
        if "checklist" in patch:
            if patch["checklist"] not in CHECKLIST:
                raise UserError("Unknown checklist state.")
            s["checklist"] = patch["checklist"]
        if "tip" in patch:
            if patch["tip"] not in TIPS:
                raise UserError("Unknown tip.")
            if patch["tip"] not in s["tips"]:
                s["tips"].append(patch["tip"])
        if "visit" in patch:
            if patch["visit"] not in VISITS:
                raise UserError("Unknown screen.")
            if patch["visit"] not in s["visited"]:
                s["visited"].append(patch["visit"])
        self._store(s)
        return self.get()
