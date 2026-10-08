from pathlib import Path

from src.historical_database import HistoricalDatabase
from src.historical_pipeline import HistoricalToolDrain, content_id


def test_historical_content_id_is_source_scoped():
    class Row:
        def __getitem__(self, key):
            return {"source_id": -1001, "selected_message_id": 42}[key]

    assert content_id(Row()) == "-1001_42"


def test_catchup_complete_ignores_terminal_waiting_vision(tmp_path):
    root = Path(tmp_path)
    for source_id in (-1001, -1002, -1003):
        db = HistoricalDatabase(
            root / "batch" / "sources" / str(source_id) / "database" / "historical.db",
            source_id,
        )
        db.set_source(str(source_id), "forum")
        db.conn.execute(
            "INSERT INTO candidates(source_id,selected_message_id,message_ids_json,grouped_ids_json,urls_json,original_url,composition_json,kind,topic_id,topic_name,evidence_json,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                source_id, 1, "[]", "[]", '["https://s.shopee.com.br/abc"]',
                "https://s.shopee.com.br/abc", "[]", "video", 0, "", "[]", "WAITING_VISION"
            ),
        )
        db.conn.commit()
        db.close()

    runner = HistoricalToolDrain(root, (-1001, -1002, -1003))
    try:
        assert runner.catchup_complete() is True
    finally:
        runner.close()
