from pathlib import Path

import pytest

from src.core.database import Database
from src.core.models import State
from src.core.pipeline import Pipeline
from src.core.services import StudioResult, VisionResult


class Vision:
    def identify(self, item):
        return VisionResult("Produto", "https://shopee.test/offer", ia_context={"id": item.item_id})


class Studio:
    def process(self, item):
        result = item.workspace / "42_result.mp4"
        result.write_bytes(b"video")
        return StudioResult(None, result)


class Publisher:
    def check_publication(self, item):
        from src.core.models import PublicationCheck
        return PublicationCheck.ABSENT

    def publish(self, item):
        from src.core.services import PublicationResult
        return PublicationResult(True, "900")


def test_pipeline_reaches_published_and_cleans_workspace(tmp_path):
    db=Database(tmp_path/"armored.db")
    original=tmp_path/"storage"/"videos"/"42"/"42_original.mp4"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original")
    db.reserve_item("42",original_url="https://shopee.test/product/1/2",original_path=original)

    pipeline=Pipeline(db, object(), Vision(), Studio(), Publisher(), None)
    pipeline.run("42")

    item=db.get("42")
    assert item.state is State.PUBLISHED
    assert item.cleanup_completed is True
    assert original.exists()
    assert list(original.parent.iterdir()) == [original]
    db.close()


def test_pipeline_waits_when_vision_cannot_resolve(tmp_path):
    from src.core.services import VisionUnresolvedError

    class Unresolved:
        def identify(self, item):
            raise VisionUnresolvedError("unavailable")

    db=Database(tmp_path/"armored.db")
    original=tmp_path/"42.mp4"
    original.write_bytes(b"original")
    db.reserve_item("42",original_path=original)

    pipeline=Pipeline(db, object(), Unresolved(), Studio(), Publisher(), None)
    pipeline.run("42")

    assert db.get("42").state is State.WAITING_VISION
    db.close()
