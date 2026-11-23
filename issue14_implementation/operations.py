"""Issue #14: durable operational audit, error logging, and outbox events.

No credentials or article body text are stored. SQLite is a local reference adapter;
production deployment should supply a shared transactional database.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

EVENTS = {'review_requested', 'edited', 'approved', 'rejected', 'upload_attempt', 'upload_succeeded', 'upload_failed', 'sensitive_flagged'}
ALERT_EVENTS = {'upload_failed', 'sensitive_flagged'}

class OperationError(ValueError):
    pass

class OperationsStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              article_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              actor_id TEXT,
              occurred_at TEXT NOT NULL,
              outcome TEXT NOT NULL,
              error_type TEXT,
              error_message TEXT,
              evidence_ref TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_article ON events(article_id, id);
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL
            );
            ''')

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def record(self, article_id: str, event_type: str, *, actor_id: str | None = None,
               outcome: str = 'success', error_type: str | None = None,
               error_message: str | None = None, evidence_ref: str | None = None) -> int:
        if not article_id or event_type not in EVENTS or outcome not in {'success','failure','pending'}:
            raise OperationError('Invalid article, event or outcome')
        if event_type == 'upload_failed' and (not error_type or not error_message):
            raise OperationError('Upload failure requires classified error')
        if event_type == 'sensitive_flagged' and not evidence_ref:
            raise OperationError('Sensitive alert requires evidence reference')
        # Avoid storing arbitrary exception strings or tokens: callers must provide
        # a pre-sanitized short, non-secret error description.
        if error_message and (len(error_message) > 200 or any(x in error_message.lower() for x in ('token=', 'password=', 'apikey=', 'authorization:'))):
            raise OperationError('Unsafe error message')
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute('''INSERT INTO events
                (article_id,event_type,actor_id,occurred_at,outcome,error_type,error_message,evidence_ref)
                VALUES (?,?,?,?,?,?,?,?)''',
                (article_id,event_type,actor_id,now,outcome,error_type,error_message,evidence_ref))
            event_id = cursor.lastrowid
            if event_type in ALERT_EVENTS:
                db.execute('INSERT INTO alerts(event_id,created_at) VALUES (?,?)', (event_id,now))
            return event_id

    def history(self, article_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('SELECT * FROM events WHERE article_id=? ORDER BY id', (article_id,)).fetchall()
            return [dict(row) for row in rows]

    def pending_alerts(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('''SELECT alerts.id AS alert_id, events.article_id,
                events.event_type, events.error_type, events.evidence_ref
                FROM alerts JOIN events ON events.id=alerts.event_id
                WHERE alerts.status='pending' ORDER BY alerts.id''').fetchall()
            return [dict(row) for row in rows]

    def mark_alert_delivered(self, alert_id: int):
        with self._connect() as db:
            cur = db.execute("UPDATE alerts SET status='delivered' WHERE id=? AND status='pending'", (alert_id,))
            if cur.rowcount != 1:
                raise OperationError('Alert not pending')
