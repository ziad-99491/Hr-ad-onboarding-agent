import json, os, sqlite3, threading, uuid
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "/data/hiring.db")
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS requests(
            id TEXT PRIMARY KEY, created TEXT, status TEXT, start_date TEXT,
            payload TEXT, plan TEXT, sam TEXT, dn TEXT, error TEXT)""")


def create(payload: dict) -> str:
    rid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute("INSERT INTO requests(id,created,status,start_date,payload) VALUES(?,?,?,?,?)",
                  (rid, datetime.now(timezone.utc).isoformat(), "received",
                   payload["start_date"], json.dumps(payload)))
    return rid


def update(rid: str, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE requests SET {keys} WHERE id=?", (*fields.values(), rid))


def get(rid: str):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    return dict(r) if r else None


def list_all(limit=100):
    with _lock, _conn() as c:
        rows = c.execute("SELECT id,created,status,start_date,sam,error FROM requests "
                         "ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_due(today: str):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM requests WHERE status='created' AND start_date<=?",
                         (today,)).fetchall()
    return [dict(r) for r in rows]
