from __future__ import annotations

from datetime import datetime

from src.sync import (
    ArmoredSync,
    TelegramMessage,
    is_shopee_short_url,
)
from src.sync.service import _make_followup


def message(message_id: int, *, video=False, image=False, url=None):
    return TelegramMessage(
        source_id=123,
        message_id=message_id,
        date=datetime(2026, 10, 8),
        grouped_id=None,
        has_video=video,
        has_image=image,
        urls=(url,) if url else (),
        text=url or "",
    )


def test_armored_sync_followup_preserves_image_on_link_message():
    candidate = _make_followup(
        message(10, video=True),
        message(11, image=True, url="https://s.shopee.com.br/ABC123"),
        123, 0, "",
    )
    assert candidate.kind == "followup"
    assert candidate.message_ids == (10, 11)
    assert candidate.urls == ("https://s.shopee.com.br/ABC123",)
    assert candidate.composition == ("video", "image", "link")


def test_armored_sync_followup_without_image():
    candidate = _make_followup(
        message(20, video=True),
        message(21, url="https://s.shopee.com.br/ABC123"),
        123, 0, "",
    )
    assert candidate.composition == ("video", "link")


def test_sync_accepts_only_shopee_short_product_links():
    assert is_shopee_short_url("https://s.shopee.com.br/1BEcv24py4")
    assert is_shopee_short_url("https://s.shopee.com.br/ABC123")


def test_sync_rejects_non_short_shopee_urls():
    rejected = (
        "https://creator.shopee.com.br/insight/live",
        "https://shopee.com.br/product/123/456",
        "https://affiliate.shopee.com.br/offer/custom_link",
        "https://s.shopee.com.br/",
        "http://s.shopee.com.br/1BEcv24py4",
        "https://s.shopee.com.br/1BEcv24py4?sub_id=test",
        "https://example.com/1BEcv24py4",
    )
    assert all(not is_shopee_short_url(url) for url in rejected)


class FakeGateway:
    def __init__(self, messages, mode="source"):
        self.messages = messages
        self.mode = mode

    async def source_mode(self, source_id):
        return self.mode

    async def discover_topics(self, source_id):
        return []

    async def iter_source(self, source_id):
        for item in self.messages:
            yield item

    async def iter_topic(self, source_id, topic_id):
        for item in self.messages:
            yield item


async def collect(async_iter):
    return [item async for item in async_iter]


def test_armored_sync_isolated_from_vision_and_download():
    from src.sync import ArmoredSync

    gateway = FakeGateway([
        message(30, video=True, url="https://s.shopee.com.br/ABC123"),
    ])
    candidates = __import__("asyncio").run(
        collect(ArmoredSync(gateway).discover(123))
    )

    assert len(candidates) == 1
    assert candidates[0].selected_message_id == 30
    assert candidates[0].urls == ("https://s.shopee.com.br/ABC123",)
