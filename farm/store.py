"""SQLite checkpoint + append-only events; exact fractions survive restart."""
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
import json
import re
import sqlite3
import time
import uuid

from .experience import ARCHIVE_SCHEMA, recall_experiences, save_experiences
from .memory import PUBLIC_SCHEMA, decision_recall, save_public_memory


def encode(value):
    if isinstance(value, Fraction):
        return {"$fraction": [str(value.numerator), str(value.denominator)]}
    raise TypeError(type(value).__name__)


def decode(value):
    return Fraction(*map(int, value["$fraction"])) if set(value) == {"$fraction"} else value


def dumps(value):
    return json.dumps(value, default=encode, ensure_ascii=False)


def loads(value):
    return json.loads(value, object_hook=decode)


def display(value):
    """Approximate UI numbers only; never used for accounting or saved actions."""
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, dict):
        return {k: display(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [display(x) for x in value]
    return value


class Store:
    def __init__(self, path="data/lab.sqlite3"):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created REAL, updated REAL, state TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id TEXT, body TEXT);
            CREATE INDEX IF NOT EXISTS event_run ON events(run_id,id);
            CREATE TABLE IF NOT EXISTS decisions(run_id TEXT, action_id TEXT, response TEXT,
                PRIMARY KEY(run_id,action_id));
            CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, run_id TEXT, action_id TEXT,
                attempt INTEGER, body TEXT);
            CREATE INDEX IF NOT EXISTS call_run ON calls(run_id,id);
            CREATE TABLE IF NOT EXISTS call_totals(run_id TEXT PRIMARY KEY, calls INTEGER,
                corrections INTEGER, errors INTEGER, seconds REAL, tokens INTEGER);
            CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, run_id TEXT, agent_id TEXT,
                action_id TEXT, body TEXT, UNIQUE(run_id,action_id));
            CREATE INDEX IF NOT EXISTS observation_owner ON observations(run_id,agent_id,id);
            CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, body TEXT);
            """)
            db.executescript(ARCHIVE_SCHEMA)
            db.executescript(PUBLIC_SCHEMA)
            # Reconcile an older worker's resumed writes before using cached counters.
            db.execute("""DELETE FROM call_totals WHERE calls !=
                (SELECT COUNT(*) FROM calls WHERE calls.run_id=call_totals.run_id)""")
            # Backfill only missing or stale counters; ordinary polling stays cheap.
            db.execute("""INSERT INTO call_totals
                SELECT run_id, COUNT(*), SUM(attempt>0), SUM(json_extract(body,'$.error') IS NOT NULL),
                SUM(json_extract(body,'$.seconds')),
                SUM(json_extract(body,'$.prompt_tokens')+json_extract(body,'$.completion_tokens'))
                FROM calls WHERE run_id NOT IN (SELECT run_id FROM call_totals) GROUP BY run_id""")
            # A prior worker cannot be assumed to still exist after process restart.
            for row in db.execute("SELECT id,state FROM runs").fetchall():
                s = loads(row[1])
                if s["status"] == "running":
                    s["status"] = "interrupted"
                    db.execute("UPDATE runs SET state=? WHERE id=?", (dumps(s), row[0]))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state):
        rid = uuid.uuid4().hex[:12]
        with self.connection() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?)", (rid, time.time(), time.time(), dumps(state)))
        return rid

    def load(self, rid):
        with self.connection() as db:
            row = db.execute("SELECT state FROM runs WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise KeyError("Game not found.")
        return loads(row[0])

    def save(self, rid, state):
        events = state["events"]
        persisted = {**state, "events": []}
        with self.connection() as db:
            db.execute("UPDATE runs SET state=?,updated=? WHERE id=?", (dumps(persisted), time.time(), rid))
            db.executemany("INSERT INTO events(run_id,body) VALUES(?,?)", [(rid, dumps(x)) for x in events])
            save_experiences(db, rid, state, events)
            if state['config']['communication']:
                save_public_memory(db, rid, events, state['contracts'])
        state["events"] = []

    def list(self):
        with self.connection() as db:
            rows = db.execute("SELECT id,created,updated,state FROM runs ORDER BY created DESC").fetchall()
        return [{"id": r[0], "created": r[1], "updated": r[2], **{k: loads(r[3])[k] for k in ("status", "round", "phase", "config")}} for r in rows]

    def decision(self, rid, key):
        with self.connection() as db:
            row = db.execute("SELECT response FROM decisions WHERE run_id=? AND action_id=?", (rid, key)).fetchone()
        return loads(row[0]) if row else None

    def accept(self, rid, key, aid, decision, observation):
        # Stable action key makes retry after a checkpoint interruption idempotent.
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?)", (rid, key, dumps(decision)))
            db.execute("INSERT OR IGNORE INTO observations(run_id,agent_id,action_id,body) VALUES(?,?,?,?)",
                       (rid, aid, key, dumps(observation)))

    def log_call(self, rid, key, attempt, body):
        with self.connection() as db:
            db.execute("INSERT INTO calls(run_id,action_id,attempt,body) VALUES(?,?,?,?)", (rid, key, attempt, dumps(body)))
            db.execute("""INSERT INTO call_totals VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
                calls=calls+1, corrections=corrections+excluded.corrections, errors=errors+excluded.errors,
                seconds=seconds+excluded.seconds, tokens=tokens+excluded.tokens""",
                (rid, 1, int(attempt > 0), int(body["error"] is not None), body["seconds"],
                 body["prompt_tokens"] + body["completion_tokens"]))

    def recall(self, rid, aid, query="", limit=5):
        """Historical observation inspector. Agent decisions use experiences instead."""
        with self.connection() as db:
            rows = db.execute("SELECT body FROM observations WHERE run_id=? AND agent_id=? ORDER BY id DESC", (rid, aid))
            result = []
            terms = query.lower().split()
            for (body,) in rows:
                if not terms or any(term in body.lower() for term in terms):
                    obs = loads(body)
                    # Do not recursively nest past recalled observations.
                    obs.pop("recalled_observations", None)
                    result.append(obs)
                    if len(result) == limit:
                        break
        return result

    def experiences(self, rid, aid, observation, query):
        with self.connection() as db:
            return recall_experiences(db, rid, aid, observation, query)

    def decision_recall(self, rid, aid, observation, query, turn_text, public):
        with self.connection() as db:
            return decision_recall(db, rid, aid, observation, query, turn_text, public)

    def note_history(self, rid, aid, before=None):
        with self.connection() as db:
            rows = db.execute("SELECT id,body FROM events WHERE run_id=? AND id<? "
                              "AND json_extract(body,'$.kind') IN ('note_changed','round_review') AND json_extract(body,'$.agent_id')=? "
                              "ORDER BY id DESC LIMIT 51", (rid, before or 2**63-1, aid)).fetchall()
        return {'changes': [dict(id=k, **loads(b)) for k,b in rows[:50]],
                'before': rows[49][0] if len(rows) > 50 else None}

    def recall_reviews(self, rid, aid, query):
        """Search this run and owner only, including superseded and retired versions."""
        terms = re.findall(r'[\w]+(?::\d+)?', query.casefold())
        if not set(terms) & {'archive', 'review', 'lesson', 'note', 'question'} and not any(':' in t for t in terms):
            return []
        rounds = re.findall(r'\bround\s+(\d+)', query, re.I)
        words = [t for t in terms if t not in {'archive','review','round','my','find','about','the','old'} and t not in rounds]
        with self.connection() as db:
            rows = db.execute("SELECT body FROM events WHERE run_id=? AND json_extract(body,'$.agent_id')=? "
                              "AND json_extract(body,'$.kind')='round_review' ORDER BY id DESC", (rid, aid))
            found = []
            for (raw,) in rows:
                item = loads(raw)
                if rounds and str(item['round']) not in rounds:
                    continue
                if not all(word in raw.casefold() for word in words):
                    continue
                found.append({k: item[k] for k in ('round','choice','conclusion','evidence','changes','money_unit',
                                                   'measurement_conflicts') if k in item})
                if len(found) == 2:
                    break
            return found

    def last_observation(self, rid, aid):
        with self.connection() as db:
            row = db.execute("SELECT body FROM observations WHERE run_id=? AND agent_id=? "
                             "ORDER BY id DESC LIMIT 1", (rid, aid)).fetchone()
        return loads(row[0]) if row else None

    def events(self, rid, after=0, limit=200):
        with self.connection() as db:
            return [{"id": row[0], **loads(row[1])} for row in db.execute(
                "SELECT id,body FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT ?", (rid, after, limit))]

    def calls(self, rid):
        with self.connection() as db:
            return [{"action_id": row[0], "attempt": row[1], **loads(row[2])} for row in db.execute(
                "SELECT action_id,attempt,body FROM calls WHERE run_id=? ORDER BY id", (rid,))]

    def call_stats(self, rid):
        with self.connection() as db:
            row = db.execute("SELECT calls,corrections,errors,seconds,tokens FROM call_totals WHERE run_id=?", (rid,)).fetchone()
        row = row or (0, 0, 0, 0, 0)
        return dict(zip(("calls", "corrections", "errors", "seconds", "tokens"), row))

    def export(self, rid):
        with self.connection() as db:
            observations = [{"agent_id": a, "action_id": k, "observation": loads(b)} for a, k, b in db.execute(
                "SELECT agent_id,action_id,body FROM observations WHERE run_id=? ORDER BY id", (rid,))]
            decisions = [{"action_id": k, "decision": loads(b)} for k, b in db.execute(
                "SELECT action_id,response FROM decisions WHERE run_id=? ORDER BY action_id", (rid,))]
            experiences = [{"agent_id": aid, **json.loads(body)} for aid, body in db.execute(
                "SELECT agent_id,body FROM experiences WHERE run_id=? ORDER BY round,agent_id,kind,subject", (rid,))]
        return {"state": self.load(rid), "events": self.events(rid, limit=10**9), "calls": self.calls(rid),
                "observations": observations, "decisions": decisions, "experiences": experiences}

    def save_experiment(self, eid, body):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO experiments VALUES(?,?)", (eid, dumps(body)))

    def experiments(self):
        with self.connection() as db:
            return [loads(r[0]) for r in db.execute("SELECT body FROM experiments ORDER BY rowid DESC")]
