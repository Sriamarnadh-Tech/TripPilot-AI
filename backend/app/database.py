import json, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "adaptivetrip.db"

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, request_json TEXT NOT NULL,
        current_itinerary_json TEXT NOT NULL, original_itinerary_json TEXT NOT NULL,
        budget REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL,
        received_at TEXT NOT NULL, evidence_json TEXT NOT NULL, assessment_json TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL, revision INTEGER NOT NULL,
        created_at TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
        itinerary_json TEXT NOT NULL, validation_json TEXT NOT NULL)""")

def create_trip(tid, created, request, itinerary, budget):
    with connect() as c:
        c.execute("INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?, 0)",
                  (tid, created, json.dumps(request), json.dumps(itinerary),
                   json.dumps(itinerary), budget))

def get_trip(tid):
    with connect() as c:
        r = c.execute("SELECT * FROM trips WHERE id=?", (tid,)).fetchone()
    if not r: return None
    d = dict(r)
    for k in ("request_json", "current_itinerary_json", "original_itinerary_json"):
        d[k[:-5]] = json.loads(d.pop(k))
    return d

def update_trip(tid, itinerary, budget, revision):
    with connect() as c:
        c.execute("UPDATE trips SET current_itinerary_json=?, budget=?, revision=? WHERE id=?",
                  (json.dumps(itinerary), budget, revision, tid))

def add_evidence(tid, received, evidence, assessment):
    with connect() as c:
        cur = c.execute("INSERT INTO evidence (trip_id,received_at,evidence_json,assessment_json) VALUES (?,?,?,?)",
                        (tid, received, json.dumps(evidence), json.dumps(assessment)))
        return cur.lastrowid

def add_revision(tid, rev, created, decision, reason, itinerary, validation):
    with connect() as c:
        c.execute("""INSERT INTO revisions
        (trip_id,revision,created_at,decision,reason,itinerary_json,validation_json)
        VALUES (?,?,?,?,?,?,?)""",
        (tid, rev, created, decision, reason, json.dumps(itinerary), json.dumps(validation)))

def history(tid):
    with connect() as c:
        ev = c.execute("SELECT * FROM evidence WHERE trip_id=? ORDER BY id", (tid,)).fetchall()
        rv = c.execute("SELECT * FROM revisions WHERE trip_id=? ORDER BY revision", (tid,)).fetchall()
    return {
        "evidence": [{**dict(x), "evidence": json.loads(x["evidence_json"]),
                      "assessment": json.loads(x["assessment_json"])} for x in ev],
        "revisions": [{**dict(x), "itinerary": json.loads(x["itinerary_json"]),
                       "validation": json.loads(x["validation_json"])} for x in rv]
    }
