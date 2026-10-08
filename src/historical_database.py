from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .sync import SyncCandidate


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

            CREATE TABLE IF NOT EXISTS vision_results (
                candidate_id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                affiliate_name TEXT,
                affiliate_url TEXT,
                affiliate_urls_json TEXT NOT NULL DEFAULT '[]',
                ia_context_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_vision_status
                ON vision_results(status);
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
        # A machine/process crash can leave a run in RUNNING forever. Mark
        # those stale runs explicitly before opening a new attempt. Existing
        # candidates remain untouched and are safely deduplicated by URL.
        self.conn.execute(
            "UPDATE collection_runs "
            "SET status='INTERRUPTED', "
            "finished_at=COALESCE(finished_at, CURRENT_TIMESTAMP), "
            "error=COALESCE(error, 'collector interrupted before normal completion') "
            "WHERE source_id=? AND status='RUNNING'",
            (self.source_id,),
        )
        cur = self.conn.execute(
            "INSERT INTO collection_runs(source_id) VALUES(?)",
            (self.source_id,),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def has_completed_run(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM collection_runs "
            "WHERE source_id=? AND status='COMPLETED' LIMIT 1",
            (self.source_id,),
        ).fetchone()
        return row is not None

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

    def next_candidate(self):
        return self.conn.execute(
            """
            SELECT * FROM candidates
            WHERE status IN ('DISCOVERED','RESERVED','DOWNLOADING','PROCESSING','RECOVERY')
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

    def next_vision_candidate(self):
        """Return the next candidate that still needs the historical Vision stage."""
        return self.conn.execute(
            """
            SELECT * FROM candidates
            WHERE status IN ('DISCOVERED','VISION_PROCESSING')
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

    def candidate_by_selected_message(self, selected_message_id: int):
        return self.conn.execute(
            "SELECT * FROM candidates WHERE source_id=? AND selected_message_id=? LIMIT 1",
            (self.source_id, int(selected_message_id)),
        ).fetchone()

    def set_candidate_status(self, candidate_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE candidates SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND source_id=?",
            (str(status), int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_vision_processing(self, candidate_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO vision_results(candidate_id,source_id,status,error)
            VALUES(?,?,?,NULL)
            ON CONFLICT(candidate_id) DO UPDATE SET
                source_id=excluded.source_id,
                status=excluded.status,
                error=NULL,
                updated_at=CURRENT_TIMESTAMP
            """,
            (int(candidate_id), self.source_id, "VISION_PROCESSING"),
        )
        self.conn.execute(
            "UPDATE candidates SET status='VISION_PROCESSING', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_vision_accepted(self, candidate_id: int, result) -> None:
        links = list(dict.fromkeys(
            str(value).strip()
            for value in (result.affiliate_urls or ())
            if str(value).strip()
        ))
        if not links and result.affiliate_url:
            links = [str(result.affiliate_url).strip()]
        self.conn.execute(
            """
            INSERT INTO vision_results(
                candidate_id,source_id,status,affiliate_name,affiliate_url,
                affiliate_urls_json,ia_context_json,error
            )
            VALUES(?,?,?,?,?,?,?,NULL)
            ON CONFLICT(candidate_id) DO UPDATE SET
                source_id=excluded.source_id,
                status=excluded.status,
                affiliate_name=excluded.affiliate_name,
                affiliate_url=excluded.affiliate_url,
                affiliate_urls_json=excluded.affiliate_urls_json,
                ia_context_json=excluded.ia_context_json,
                error=NULL,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(candidate_id), self.source_id, "VISION_ACCEPTED",
                result.affiliate_name, result.affiliate_url,
                json.dumps(links, ensure_ascii=False),
                json.dumps(result.ia_context or {}, ensure_ascii=False, default=str),
            ),
        )
        self.conn.execute(
            "UPDATE candidates SET status='VISION_ACCEPTED', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_vision_waiting(self, candidate_id: int, error: str) -> None:
        self.conn.execute(
            """
            INSERT INTO vision_results(candidate_id,source_id,status,error)
            VALUES(?,?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                source_id=excluded.source_id,
                status=excluded.status,
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
            """,
            (int(candidate_id), self.source_id, "WAITING_VISION", str(error)),
        )
        self.conn.execute(
            "UPDATE candidates SET status='WAITING_VISION', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_vision_retryable_error(self, candidate_id: int, error: str) -> None:
        self.conn.execute(
            """
            INSERT INTO vision_results(candidate_id,source_id,status,error)
            VALUES(?,?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                source_id=excluded.source_id,
                status=excluded.status,
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
            """,
            (int(candidate_id), self.source_id, "VISION_PROCESSING", str(error)),
        )
        self.conn.execute(
            "UPDATE candidates SET status='VISION_PROCESSING', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def next_stock_candidate(self):
        return self.conn.execute(
            """
            SELECT c.* FROM candidates c
            JOIN vision_results v ON v.candidate_id=c.id
            WHERE c.status IN ('VISION_ACCEPTED','STOCK_PROCESSING')
              AND v.status='VISION_ACCEPTED'
            ORDER BY c.id
            LIMIT 1
            """
        ).fetchone()

    def set_stock_processing(self, candidate_id: int) -> None:
        self.conn.execute(
            "UPDATE candidates SET status='STOCK_PROCESSING', updated_at=CURRENT_TIMESTAMP WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_stock_ready(self, candidate_id: int, original_path) -> None:
        self.conn.execute(
            "UPDATE candidates SET status='STOCK_READY', updated_at=CURRENT_TIMESTAMP WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.commit()

    def set_stock_retryable_error(self, candidate_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE candidates SET status='STOCK_PROCESSING', updated_at=CURRENT_TIMESTAMP WHERE id=? AND source_id=?",
            (int(candidate_id), self.source_id),
        )
        self.conn.execute(
            "UPDATE vision_results SET error=?, updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
            (str(error), int(candidate_id)),
        )
        self.conn.commit()

    def next_stage_candidate(self, statuses: tuple[str, ...]):
        placeholders = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"SELECT * FROM candidates WHERE status IN ({placeholders}) ORDER BY id LIMIT 1",
            tuple(statuses),
        ).fetchone()

    def set_stage_status(self, candidate_id: int, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE candidates SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND source_id=?",
            (str(status), int(candidate_id), self.source_id),
        )
        if error is not None:
            self.conn.execute(
                "UPDATE vision_results SET error=?, updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                (str(error), int(candidate_id)),
            )
        self.conn.commit()

    def reset_stage_processing(self, candidate_id: int, status: str) -> None:
        self.set_stage_status(candidate_id, status)

    def vision_result(self, candidate_id: int):
        return self.conn.execute(
            "SELECT * FROM vision_results WHERE candidate_id=?",
            (int(candidate_id),),
        ).fetchone()

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
