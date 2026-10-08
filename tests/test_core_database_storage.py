from pathlib import Path

from src.core import Item, State
from src.core.database import Database
from src.core.storage import Storage


def test_database_reserves_and_round_trips_item(tmp_path):
    db=Database(tmp_path/"armored.db")
    original=tmp_path/"storage"/"videos"/"42"/"42_unknown.mp4"
    db.reserve_item("42",source_id="-1001",topic_id=7,topic_name="Produtos",original_url="https://shopee.com/x",original_path=original)
    item=db.get("42")
    assert isinstance(item,Item)
    assert item.state is State.RECEIVED
    assert item.original_path==original
    assert item.source_id=="-1001"
    db.close()


def test_database_transition_and_vision_persistence(tmp_path):
    db=Database(tmp_path/"armored.db")
    db.reserve_item("42",original_url="https://shopee.com/x",original_path=tmp_path/"42.mp4")
    db.set_vision("42","Produto","https://shopee.com/offer",affiliate_urls=("https://shopee.com/offer",),ia_context={"itemId":42})
    db.transition("42",State.STUDIO,"test")
    item=db.get("42")
    assert item.state is State.STUDIO
    assert item.affiliate_url=="https://shopee.com/offer"
    assert item.ia_context=={"itemId":42}
    db.close()


def test_storage_contract_is_canonical_per_content_id(tmp_path):
    storage=Storage(tmp_path)
    original=storage.original("550",original_url="https://shopee.com/product/123/550")
    assert original.parent==tmp_path/"storage"/"videos"/"550"
    assert original.name=="550_finallinkoriginal.mp4"
    assert storage.working("550").name=="550_.mp4"
