"""SQLite store: the system of record for a matter.

Tables:
  matters, documents   what the matter is and what has arrived
  events               one row per arrival, the spine of "recent activity"
  facts                the approved state of the matter (what the brief reads)
  changes              every proposed change, with before/after, source, and status
  rejections           proposals the validator refused, kept for audit
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .models import DocumentMeta, Fact

SCHEMA = """
CREATE TABLE IF NOT EXISTS matters (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, court TEXT, matter_type TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, matter_id TEXT NOT NULL, title TEXT NOT NULL,
    doc_type TEXT, received_at TEXT NOT NULL, sha256 TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, matter_id TEXT NOT NULL, ts TEXT NOT NULL,
    event_type TEXT NOT NULL, doc_id TEXT, summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    matter_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
    source_doc_id TEXT NOT NULL, quote TEXT NOT NULL, updated_event INTEGER,
    PRIMARY KEY (matter_id, kind, key)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, matter_id TEXT NOT NULL, event_id INTEGER NOT NULL,
    kind TEXT NOT NULL, key TEXT NOT NULL, change_type TEXT NOT NULL,
    before TEXT, after TEXT NOT NULL, source_doc_id TEXT NOT NULL, quote TEXT NOT NULL,
    confidence REAL, material INTEGER NOT NULL, status TEXT NOT NULL,
    decided_by TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, matter_id TEXT NOT NULL, event_id INTEGER NOT NULL,
    kind TEXT, key TEXT, reason TEXT NOT NULL, quote TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _change(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["before"] = json.loads(row["before"]) if row["before"] else None
    out["after"] = json.loads(row["after"])
    out["material"] = bool(row["material"])
    return out


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # matters and documents

    def create_matter(self, matter_id: str, name: str, court: str = "", matter_type: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO matters (id, name, court, matter_type) VALUES (?, ?, ?, ?)",
            (matter_id, name, court, matter_type),
        )
        self.conn.commit()

    def matter(self, matter_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM matters WHERE id = ?", (matter_id,)).fetchone()
        return dict(row) if row else None

    def add_document(self, matter_id: str, meta: DocumentMeta, text: str) -> bool:
        """Returns False if this document (by id or content hash) was already ingested."""
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dup = self.conn.execute(
            "SELECT 1 FROM documents WHERE doc_id = ? OR (matter_id = ? AND sha256 = ?)",
            (meta.doc_id, matter_id, sha),
        ).fetchone()
        if dup:
            return False
        self.conn.execute(
            "INSERT INTO documents (doc_id, matter_id, title, doc_type, received_at, sha256, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (meta.doc_id, matter_id, meta.title, meta.doc_type, meta.received_at, sha, text),
        )
        self.conn.commit()
        return True

    def documents(self, matter_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT doc_id, title, doc_type, received_at FROM documents "
            "WHERE matter_id = ? ORDER BY received_at, doc_id", (matter_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def document_text(self, doc_id: str) -> str | None:
        row = self.conn.execute("SELECT text FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return row["text"] if row else None

    # events

    def add_event(self, matter_id: str, ts: str, event_type: str, doc_id: str | None, summary: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (matter_id, ts, event_type, doc_id, summary) VALUES (?, ?, ?, ?, ?)",
            (matter_id, ts, event_type, doc_id, summary),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def events(self, matter_id: str, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE matter_id = ? ORDER BY id DESC LIMIT ?", (matter_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_event(self, matter_id: str) -> dict[str, Any] | None:
        rows = self.events(matter_id, limit=1)
        return rows[0] if rows else None

    # facts and changes

    def facts(self, matter_id: str, kind: str | None = None) -> list[Fact]:
        sql = "SELECT * FROM facts WHERE matter_id = ?"
        args: list[Any] = [matter_id]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        rows = self.conn.execute(sql + " ORDER BY kind, key", args).fetchall()
        return [Fact(r["kind"], r["key"], json.loads(r["data"]), r["source_doc_id"], r["quote"]) for r in rows]

    def current_state(self, matter_id: str, kind: str, key: str) -> dict[str, Any] | None:
        """Latest known state of a fact, counting changes still awaiting review."""
        pending = self.conn.execute(
            "SELECT after FROM changes WHERE matter_id = ? AND kind = ? AND key = ? "
            "AND status = 'pending' ORDER BY id DESC LIMIT 1", (matter_id, kind, key),
        ).fetchone()
        if pending:
            return json.loads(pending["after"])
        row = self.conn.execute(
            "SELECT data FROM facts WHERE matter_id = ? AND kind = ? AND key = ?",
            (matter_id, kind, key),
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def has_earlier_parties(self, matter_id: str, event_id: int) -> bool:
        """True if an approved non-counsel party was recorded by an earlier event.

        Used to tell a new party joining the matter apart from the parties named
        in the document that opened it.
        """
        for fact in self.facts(matter_id, "party"):
            row = self.conn.execute(
                "SELECT updated_event FROM facts WHERE matter_id = ? AND kind = 'party' AND key = ?",
                (matter_id, fact.key),
            ).fetchone()
            if str(fact.data.get("role", "")).startswith("Counsel"):
                continue
            if row["updated_event"] is not None and row["updated_event"] < event_id:
                return True
        return False

    def record_change(self, *, matter_id: str, event_id: int, kind: str, key: str, change_type: str,
                      before: dict[str, Any] | None, after: dict[str, Any], source_doc_id: str,
                      quote: str, confidence: float, material: bool,
                      status: str, decided_by: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO changes (matter_id, event_id, kind, key, change_type, before, after, "
            "source_doc_id, quote, confidence, material, status, decided_by, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (matter_id, event_id, kind, key, change_type,
             json.dumps(before) if before is not None else None, json.dumps(after),
             source_doc_id, quote, confidence, int(material), status,
             decided_by, _now() if status != "pending" else None),
        )
        change_id = int(cur.lastrowid)
        if status == "approved":
            self._apply(change_id)
        self.conn.commit()
        return change_id

    def _apply(self, change_id: int) -> None:
        ch = self.get_change(change_id)
        self.conn.execute(
            "INSERT INTO facts (matter_id, kind, key, data, source_doc_id, quote, updated_event) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(matter_id, kind, key) DO UPDATE SET data = excluded.data, "
            "source_doc_id = excluded.source_doc_id, quote = excluded.quote, "
            "updated_event = excluded.updated_event",
            (ch["matter_id"], ch["kind"], ch["key"], json.dumps(ch["after"]),
             ch["source_doc_id"], ch["quote"], ch["event_id"]),
        )

    def get_change(self, change_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
        if row is None:
            raise KeyError(f"no such change: {change_id}")
        return _change(row)

    def decide(self, change_id: int, approve: bool, by: str) -> None:
        ch = self.get_change(change_id)
        if ch["status"] != "pending":
            raise ValueError(f"change {change_id} is already {ch['status']}")
        status = "approved" if approve else "rejected"
        self.conn.execute(
            "UPDATE changes SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (status, by, _now(), change_id),
        )
        if approve:
            self._apply(change_id)
        self.conn.commit()

    def pending(self, matter_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM changes WHERE matter_id = ? AND status = 'pending' ORDER BY id", (matter_id,),
        ).fetchall()
        return [_change(r) for r in rows]

    def changes_for_event(self, event_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM changes WHERE event_id = ? ORDER BY id", (event_id,),
        ).fetchall()
        return [_change(r) for r in rows]

    # audit

    def log_rejection(self, matter_id: str, event_id: int, kind: str | None, key: str | None,
                      reason: str, quote: str | None) -> None:
        self.conn.execute(
            "INSERT INTO rejections (matter_id, event_id, kind, key, reason, quote) VALUES (?, ?, ?, ?, ?, ?)",
            (matter_id, event_id, kind, key, reason, quote),
        )
        self.conn.commit()

    def rejections(self, matter_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM rejections WHERE matter_id = ? ORDER BY id", (matter_id,),
        ).fetchall()
        return [dict(r) for r in rows]
