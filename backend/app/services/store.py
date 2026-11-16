"""SQLite log of calls, transcript segments, decisions and dispatcher reviews.

Standard-library sqlite3, one file (backend/data/civops.db, gitignored). The
point of the log is accountability: every recommendation a dispatcher acts on
is stored with the rule that produced it, and every override records what the
dispatcher chose instead and why.

Privacy posture (this is a synthetic demonstration, see docs/RESPONSIBLE_USE.md):

* Transcript text, and the evidence quotes cut from it, are stored only for
  scripted calls, which are fictional by construction.
* For live-microphone and typed transcripts the log keeps the decision and the
  true/false/unknown answers but no words, unless CIVOPS_STORE_LIVE_TRANSCRIPTS=1.
"""

import csv
import io
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.models import Decision, Incident

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "civops.db"

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE calls (
    call_id     TEXT PRIMARY KEY,
    source      TEXT NOT NULL,              -- microphone | script:<id> | manual
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    outcome     TEXT CHECK (outcome IN ('ended', 'error'))
);

CREATE TABLE transcript_segments (
    id       INTEGER PRIMARY KEY,
    call_id  TEXT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    t        REAL NOT NULL,                 -- seconds since the call started
    speaker  TEXT NOT NULL,
    text     TEXT NOT NULL
);

CREATE TABLE decisions (
    id                INTEGER PRIMARY KEY,
    call_id           TEXT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    rule_id           TEXT NOT NULL,
    destination       TEXT NOT NULL,
    reason            TEXT NOT NULL,
    source            TEXT,
    rulebook_version  TEXT,
    provisional       INTEGER NOT NULL DEFAULT 0,
    incident_json     TEXT NOT NULL,
    simulated_time    TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE reviews (
    id                       INTEGER PRIMARY KEY,
    decision_id              INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    call_id                  TEXT NOT NULL REFERENCES calls(call_id) ON DELETE CASCADE,
    action                   TEXT NOT NULL CHECK (action IN ('confirmed', 'overridden')),
    recommended_destination  TEXT NOT NULL,
    chosen_destination       TEXT NOT NULL,
    reason                   TEXT NOT NULL DEFAULT '',
    created_at               TEXT NOT NULL,
    -- An override must choose something else and say why.
    CHECK (action = 'confirmed' OR
           (chosen_destination <> recommended_destination AND length(trim(reason)) > 0)),
    CHECK (action = 'overridden' OR chosen_destination = recommended_destination)
);

CREATE INDEX idx_segments_call ON transcript_segments(call_id, id);
CREATE INDEX idx_decisions_call ON decisions(call_id);
CREATE INDEX idx_reviews_created ON reviews(created_at);
"""

REVIEW_COLUMNS = (
    "id", "created_at", "call_id", "call_source", "action", "rule_id",
    "recommended_destination", "chosen_destination", "reason",
    "rulebook_version", "simulated_time",
)


def db_path() -> Path:
    return Path(os.environ.get("CIVOPS_DB_PATH") or DEFAULT_DB_PATH)


def stores_words(source: str) -> bool:
    """Whether transcript text and evidence quotes may be written for this call."""
    if source.startswith("script:"):
        return True  # scripted calls are fictional by construction
    return os.environ.get("CIVOPS_STORE_LIVE_TRANSCRIPTS", "") == "1"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _spreadsheet_safe(value):
    """Stop a free-text cell from running as a formula when the CSV is opened."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the event loop and worker threads, guarded
        # by a lock. Autocommit; multi-statement writes use explicit transactions.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.path} has schema version {version}; this build knows {SCHEMA_VERSION}"
                )
            if version == 0:
                self._db.executescript(
                    f"BEGIN;{SCHEMA}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;"
                )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- calls ---------------------------------------------------------------

    def start_call(self, call_id: str, source: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO calls (call_id, source, started_at) VALUES (?, ?, ?)",
                (call_id, source, _now()),
            )

    def end_call(self, call_id: str, outcome: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE calls SET ended_at = ?, outcome = ? "
                "WHERE call_id = ? AND ended_at IS NULL",
                (_now(), outcome, call_id),
            )

    def call_source(self, call_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT source FROM calls WHERE call_id = ?", (call_id,)
            ).fetchone()
        return row["source"] if row else None

    def add_segment(self, call_id: str, t: float, speaker: str, text: str) -> bool:
        """Store one final transcript line, if this call's words may be stored."""
        source = self.call_source(call_id)
        if source is None or not stores_words(source):
            return False
        with self._lock:
            self._db.execute(
                "INSERT INTO transcript_segments (call_id, t, speaker, text) VALUES (?, ?, ?, ?)",
                (call_id, t, speaker, text),
            )
        return True

    # -- decisions and reviews ----------------------------------------------

    def record_review(
        self,
        *,
        call_id: str,
        incident: Incident,
        decision: Decision,
        action: str,
        chosen_destination: str,
        reason: str,
    ) -> dict:
        """Store the decision a dispatcher acted on and what they did, atomically."""
        source = self.call_source(call_id) or "manual"

        stored = incident.model_dump(mode="json")
        if not stores_words(source):
            stored["evidence"] = {}  # quotes are transcript text
            stored["location"] = None  # so is the stated location

        now = _now()

        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute(
                    "INSERT OR IGNORE INTO calls (call_id, source, started_at) VALUES (?, ?, ?)",
                    (call_id, source, now),
                )
                decision_id = self._db.execute(
                    "INSERT INTO decisions (call_id, rule_id, destination, reason, source, "
                    "rulebook_version, provisional, incident_json, simulated_time, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        call_id,
                        decision.rule_id,
                        decision.destination.value,
                        decision.reason,
                        decision.source,
                        decision.rulebook_version,
                        int(decision.provisional),
                        json.dumps(stored, sort_keys=True),
                        stored["timestamp"],
                        now,
                    ),
                ).lastrowid
                review_id = self._db.execute(
                    "INSERT INTO reviews (decision_id, call_id, action, recommended_destination, "
                    "chosen_destination, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        decision_id,
                        call_id,
                        action,
                        decision.destination.value,
                        chosen_destination,
                        reason,
                        now,
                    ),
                ).lastrowid
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

        return self.review(review_id)

    _REVIEW_QUERY = """
        SELECT r.id, r.created_at, r.call_id, c.source AS call_source, r.action,
               d.rule_id, r.recommended_destination, r.chosen_destination, r.reason,
               d.rulebook_version, d.simulated_time
        FROM reviews r
        JOIN decisions d ON d.id = r.decision_id
        JOIN calls c ON c.call_id = r.call_id
    """

    def review(self, review_id: int) -> dict:
        with self._lock:
            row = self._db.execute(
                self._REVIEW_QUERY + " WHERE r.id = ?", (review_id,)
            ).fetchone()
        return dict(row)

    def reviews(self, limit: int | None = 50) -> list[dict]:
        """Newest first."""
        query = self._REVIEW_QUERY + " ORDER BY r.id DESC"
        with self._lock:
            if limit is None:
                rows = self._db.execute(query).fetchall()
            else:
                rows = self._db.execute(query + " LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def reviews_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(REVIEW_COLUMNS)
        for row in reversed(self.reviews(limit=None)):  # oldest first reads as a log
            writer.writerow([_spreadsheet_safe(row[column]) for column in REVIEW_COLUMNS])
        return buffer.getvalue()

    # -- reading calls -------------------------------------------------------

    def calls(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT c.call_id, c.source, c.started_at, c.ended_at, c.outcome,
                       (SELECT COUNT(*) FROM transcript_segments s WHERE s.call_id = c.call_id)
                           AS segments,
                       (SELECT COUNT(*) FROM reviews r WHERE r.call_id = c.call_id) AS reviews
                FROM calls c
                ORDER BY c.started_at DESC, c.rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def call(self, call_id: str) -> dict | None:
        with self._lock:
            call = self._db.execute(
                "SELECT call_id, source, started_at, ended_at, outcome FROM calls "
                "WHERE call_id = ?",
                (call_id,),
            ).fetchone()
            if call is None:
                return None
            segments = self._db.execute(
                "SELECT t, speaker, text FROM transcript_segments WHERE call_id = ? ORDER BY id",
                (call_id,),
            ).fetchall()
            decisions = self._db.execute(
                "SELECT id, rule_id, destination, reason, source, rulebook_version, "
                "provisional, incident_json, simulated_time, created_at "
                "FROM decisions WHERE call_id = ? ORDER BY id",
                (call_id,),
            ).fetchall()
            reviews = self._db.execute(
                self._REVIEW_QUERY + " WHERE r.call_id = ? ORDER BY r.id", (call_id,)
            ).fetchall()

        return {
            **dict(call),
            "transcript_stored": stores_words(call["source"]),
            "segments": [dict(row) for row in segments],
            "decisions": [
                {
                    **{k: row[k] for k in row.keys() if k not in ("incident_json", "provisional")},
                    "provisional": bool(row["provisional"]),
                    "incident": json.loads(row["incident_json"]),
                }
                for row in decisions
            ],
            "reviews": [dict(row) for row in reviews],
        }


_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """The process-wide store, opened on first use (and reopened if the
    configured path changes, which is how tests get a fresh database)."""
    global _store

    with _store_lock:
        path = db_path()
        if _store is None or _store.path != path:
            if _store is not None:
                _store.close()
            _store = Store(path)
        return _store
