from pathlib import Path

from src.core import Item, PublicationCheck, State


def test_state_contract_contains_pipeline_states():
    assert State.RECEIVED.value == "RECEIVED"
    assert State.VISION.value == "VISION"
    assert State.WAITING_VISION.value == "WAITING_VISION"
    assert State.RECOVERY.value == "RECOVERY"
    assert State.PUBLISHED.value == "PUBLISHED"


def test_publication_check_contract_is_three_state():
    assert {item.value for item in PublicationCheck} == {
        "CONFIRMED",
        "ABSENT",
        "UNKNOWN",
    }


def test_item_exposes_stable_item_id_and_source_metadata():
    item = Item(
        content_id="42",
        telegram_message_id="99",
        state=State.RECEIVED,
        workspace=Path("workspace"),
        original_path=Path("workspace/original.mp4"),
        working_path=None,
        result_path=None,
        affiliate_name=None,
        affiliate_url=None,
        source_id="-100123",
        original_url="https://shopee.com/example",
        topic_id=7,
        topic_name="Produtos",
    )

    assert item.item_id == "42"
    assert item.source_id == "-100123"
    assert item.topic_id == 7
