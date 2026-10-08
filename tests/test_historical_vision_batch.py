from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.models import State
from src.historical_executor import HistoricalExecutor
from src.vision import VisionUnresolvedError


class FakeHistorical:
    def __init__(self):
        self.statuses = []

    def set_candidate_status(self, candidate_id, status):
        self.statuses.append((candidate_id, status))


class FakeDB:
    def __init__(self, state=State.RECEIVED):
        self.item = SimpleNamespace(state=state)

    def get(self, _item_id):
        return self.item

    def mark_vision_waiting(self, _item_id, _reason):
        self.item.state = State.WAITING_VISION


def make_executor(db):
    executor = HistoricalExecutor.__new__(HistoricalExecutor)
    executor.State = State
    executor.historical = FakeHistorical()
    executor.db = db
    return executor


def test_process_vision_one_accepts_without_materializing():
    executor = make_executor(FakeDB())
    executor._ensure_reserved = lambda candidate: str(candidate["selected_message_id"])
    calls = []
    executor._set_vision_result = lambda item_id: calls.append(item_id)

    outcome = executor.process_vision_one(
        {"id": 1, "selected_message_id": 123}
    )

    assert outcome == "VISION_ACCEPTED"
    assert calls == ["123"]
    assert executor.historical.statuses == [
        (1, "VISION_PROCESSING"),
        (1, "VISION_ACCEPTED"),
    ]


def test_process_vision_one_moves_unresolved_to_waiting_without_download():
    executor = make_executor(FakeDB())
    executor._ensure_reserved = lambda candidate: str(candidate["selected_message_id"])

    def unresolved(_item_id):
        raise VisionUnresolvedError("produto não encontrado")

    executor._set_vision_result = unresolved

    outcome = executor.process_vision_one(
        {"id": 2, "selected_message_id": 456}
    )

    assert outcome == "WAITING_VISION"
    assert executor.historical.statuses == [
        (2, "VISION_PROCESSING"),
        (2, "WAITING_VISION"),
    ]
    assert executor.db.item.state == State.WAITING_VISION


def test_process_vision_one_reopens_candidate_after_technical_error():
    executor = make_executor(FakeDB())
    executor._ensure_reserved = lambda candidate: str(candidate["selected_message_id"])

    def broken(_item_id):
        raise RuntimeError("Shopee API indisponível")

    executor._set_vision_result = broken

    with pytest.raises(RuntimeError, match="indisponível"):
        executor.process_vision_one(
            {"id": 3, "selected_message_id": 789}
        )

    assert executor.historical.statuses == [
        (3, "VISION_PROCESSING"),
        (3, "DISCOVERED"),
    ]


def test_historical_executor_rejects_empty_inventory(tmp_path, monkeypatch):
    import src.historical_executor as module
    from src.historical_database import HistoricalDatabase

    monkeypatch.setattr(module, "ROOT", tmp_path)
    source_id = -1003788989075
    path = tmp_path / "batch" / "sources" / str(source_id) / "database" / "historical.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = HistoricalDatabase(path, source_id)
    db.close()

    with pytest.raises(RuntimeError, match="Inventory histórica vazia"):
        HistoricalExecutor(source_id)
