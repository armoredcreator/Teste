from __future__ import annotations

from pathlib import Path

from src.historical_database import HistoricalDatabase
from src.sync import TelegramMessage, SyncCandidate
from src.vision.contracts import VisionResult, VisionUnresolvedError
from src.vision.historical import HistoricalVisionRunner


def make_candidate(message_id: int, url: str) -> SyncCandidate:
    message = TelegramMessage(
        source_id=123,
        message_id=message_id,
        date=None,
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


class FakeVision:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    def identify(self, item):
        self.calls.append(item.original_url)
        return self.behavior(item)


def test_historical_vision_accepts_and_persists_result(tmp_path: Path):
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    assert db.insert_candidate(make_candidate(10, "https://s.shopee.com.br/abc123"), run_id)
    db.commit()

    vision = FakeVision(lambda item: VisionResult(
        "Produto",
        "https://s.shopee.com.br/affiliate",
        affiliate_urls=("https://s.shopee.com.br/affiliate",),
        ia_context={"vision_version": "V1"},
    ))

    result = HistoricalVisionRunner(db, vision).drain()

    assert result["processed"] == 1
    assert result["VISION_ACCEPTED"] == 1
    assert db.counts() == {"VISION_ACCEPTED": 1}
    stored = db.vision_result(1)
    assert stored["status"] == "VISION_ACCEPTED"
    assert stored["affiliate_url"] == "https://s.shopee.com.br/affiliate"
    assert vision.calls == ["https://s.shopee.com.br/abc123"]
    db.close()


def test_historical_vision_unresolved_becomes_waiting_without_download(tmp_path: Path):
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    assert db.insert_candidate(make_candidate(10, "https://s.shopee.com.br/abc123"), run_id)
    db.commit()

    def unresolved(_item):
        raise VisionUnresolvedError("produto não resolvido")

    result = HistoricalVisionRunner(db, FakeVision(unresolved)).drain()

    assert result["processed"] == 1
    assert result["WAITING_VISION"] == 1
    assert db.counts() == {"WAITING_VISION": 1}
    assert db.vision_result(1)["error"] == "produto não resolvido"
    db.close()


def test_historical_vision_retryable_error_does_not_become_failed(tmp_path: Path):
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    assert db.insert_candidate(make_candidate(10, "https://s.shopee.com.br/abc123"), run_id)
    db.commit()

    def broken(_item):
        raise TimeoutError("Shopee timeout")

    result = HistoricalVisionRunner(db, FakeVision(broken)).drain()

    assert result["processed"] == 1
    assert result["VISION_PROCESSING"] == 1
    assert db.counts() == {"VISION_PROCESSING": 1}
    assert db.vision_result(1)["error"] == "Shopee timeout"
    db.close()


def test_historical_vision_drains_in_candidate_order_and_honors_limit(tmp_path: Path):
    db = HistoricalDatabase(tmp_path / "historical.db", 123)
    run_id = db.start_run()
    for message_id in (10, 11, 12):
        assert db.insert_candidate(
            make_candidate(message_id, f"https://s.shopee.com.br/{message_id}"),
            run_id,
        )
    db.commit()

    vision = FakeVision(lambda item: VisionResult("P", "https://s.shopee.com.br/a"))
    result = HistoricalVisionRunner(db, vision).drain(limit=2)

    assert result["processed"] == 2
    assert vision.calls == [
        "https://s.shopee.com.br/10",
        "https://s.shopee.com.br/11",
    ]
    assert db.counts() == {"DISCOVERED": 1, "VISION_ACCEPTED": 2}
    db.close()
