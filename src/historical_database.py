from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .sync_discovery import SyncCandidate


class HistoricalDatabase:
    """SQLite inventory for historical candidates.

    This database is intentionally separate from production ArmoredCreator
    databases. It stores discovery evidence only; it never stores media bytes
    and never creates a physical download queue.
    """

    def __init__(self, path: Path, source_id: int) -> None:
        self.path = Path(path)
        self.source_id = int(source_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS source (
                source_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                mode TEXT NOT NULL,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                candidates_seen INTEGER NOT NULL DEFAULT 0,
                candidates_inserted INTEGER NOT NULL DEFAULT 0,
                candidates_existing INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                selected_message_id INTEGER NOT NULL,
                message_ids_json TEXT NOT NULL,
                grouped_ids_json TEXT NOT NULL,
                urls_json TEXT NOT NULL,
                original_url TEXT NOT NULL,
                composition_json TEXT NOT NULL,
                kind TEXT NOT NULL,
                topic_id INTEGER NOT NULL DEFAULT 0,
                topic_name TEXT NOT NULL DEFAULT '',
                selected_date TEXT,
                evidence_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_id, original_url)
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_status
                ON candidates(status);
            CREATE INDEX IF NOT EXISTS idx_candidates_url
                ON candidates(original_url);
            CREATE INDEX IF NOT EXISTS idx_candidates_message
                ON candidates(selected_message_id);
            """
        )
        self.conn.commit()

    def set_source(self, title: str, mode: str) -> None:
        self.conn.execute(
            """
            INSERT INTO source(source_id, title, mode)
            VALUES(?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                title=excluded.title,
                mode=excluded.mode,
                collected_at=CURRENT_TIMESTAMP
            """,
            (self.source_id, str(title), str(mode)),
        )
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO collection_runs(source_id) VALUES(?)",
            (self.source_id,),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_seen(self, run_id: int) -> None:
        self.conn.execute(
            "UPDATE collection_runs SET candidates_seen=candidates_seen+1 WHERE id=?",
            (int(run_id),),
        )

    def insert_candidate(self, candidate: SyncCandidate, run_id: int) -> bool:
        original_url = str(candidate.urls[0]).strip() if candidate.urls else ""
        if not original_url:
            return False

        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO candidates(
                source_id, selected_message_id, message_ids_json,
                grouped_ids_json, urls_json, original_url,
                composition_json, kind, topic_id, topic_name,
                selected_date, evidence_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                self.source_id,
                int(candidate.selected_message_id),
                json.dumps(list(candidate.message_ids), ensure_ascii=False),
                json.dumps(list(candidate.grouped_ids), ensure_ascii=False),
                json.dumps(list(candidate.urls), ensure_ascii=False),
                original_url,
                json.dumps(list(candidate.composition), ensure_ascii=False),
                candidate.kind,
                int(candidate.topic_id),
                candidate.topic_name,
                candidate.selected.date.isoformat() if candidate.selected.date else None,
                json.dumps(list(candidate.details), ensure_ascii=False),
            ),
        )
        inserted = cursor.rowcount == 1
        self.conn.execute(
            """
            UPDATE collection_runs
            SET candidates_inserted=candidates_inserted+?,
                candidates_existing=candidates_existing+?
            WHERE id=?
            """,
            (1 if inserted else 0, 0 if inserted else 1, int(run_id)),
        )
        return inserted

    def finish_run(self, run_id: int, status: str = "COMPLETED", error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE collection_runs
            SET finished_at=CURRENT_TIMESTAMP, status=?, error=?
            WHERE id=?
            """,
            (str(status), error, int(run_id)),
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS total FROM candidates GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def total(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS total FROM candidates").fetchone()
        return int(row["total"])

    def close(self) -> None:
        self.conn.close()
