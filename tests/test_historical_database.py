from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.historical_database import HistoricalDatabase
from src.telegram_reader import TelegramMessage
from src.sync_discovery import SyncCandidate


def candidate(message_id: int, url: str) -> SyncCandidate:
    message = TelegramMessage(
        source_id=123,
        message_id=message_id,
        date=datetime(2026, 10, 7),
        grouped_id=None,
        has_video=True,
        has_image=False,
        urls=(url,),
        text=url,
    )
    return SyncCandidate(
        source_id=123,
        topic_id=0,
        topic_name="",
        message_ids=(message_id,),
        grouped_ids=(),
        urls=(url,),
        composition=("video", "link"),
        selected_message_id=message_id,
        selected=message,
        details=({"message_id": message_id},),
        kind="direct",
    )


def test_historical_database_is_idempotent_per_source_url(tmp_path: Path) -> None:
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    db.set_source("source", "source")

    assert db.insert_candidate(candidate(10, "https://shopee.co/a"), run_id)
    assert not db.insert_candidate(candidate(11, "https://shopee.co/a"), run_id)
    assert db.insert_candidate(candidate(12, "https://shopee.co/b"), run_id)

    db.commit()

    assert db.total() == 2
    assert db.counts() == {"DISCOVERED": 2}

    row = db.conn.execute(
        "SELECT candidates_seen, candidates_inserted, candidates_existing "
        "FROM collection_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    # insert_candidate accounts for persistence outcomes; record_seen is owned
    # by the collector because it represents discovery, not database insertion.
    assert row["candidates_inserted"] == 2
    assert row["candidates_existing"] == 1

    db.finish_run(run_id)
    db.close()


def test_interrupted_run_is_recovered_without_touching_candidates(tmp_path: Path) -> None:
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    first_run = db.start_run()
    db.insert_candidate(candidate(10, "https://shopee.co/a"), first_run)
    db.commit()

    # Simulate a process crash: the run remains RUNNING.
    second_run = db.start_run()

    old = db.conn.execute(
        "SELECT status, finished_at, error FROM collection_runs WHERE id=?",
        (first_run,),
    ).fetchone()
    current = db.conn.execute(
        "SELECT status FROM collection_runs WHERE id=?",
        (second_run,),
    ).fetchone()

    assert old["status"] == "INTERRUPTED"
    assert old["finished_at"] is not None
    assert old["error"] == "collector interrupted before normal completion"
    assert current["status"] == "RUNNING"
    assert db.total() == 1

    db.finish_run(second_run)
    db.close()


def test_completed_run_is_detected(tmp_path: Path) -> None:
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    db.finish_run(run_id)

    assert db.has_completed_run()
    db.close()
