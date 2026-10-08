from __future__ import annotations

from datetime import datetime

from src.sync_discovery import _make_followup
from src.telegram_reader import TelegramMessage


def message(
    message_id: int,
    *,
    video: bool = False,
    image: bool = False,
    url: str | None = None,
) -> TelegramMessage:
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


def test_followup_preserves_image_on_link_message() -> None:
    candidate = _make_followup(
        message(10, video=True),
        message(11, image=True, url="https://shopee.co/test"),
        123,
        0,
        "",
    )

    assert candidate.kind == "followup"
    assert candidate.message_ids == (10, 11)
    assert candidate.urls == ("https://shopee.co/test",)
    assert candidate.composition == ("video", "image", "link")


def test_followup_without_image_keeps_original_composition() -> None:
    candidate = _make_followup(
        message(20, video=True),
        message(21, url="https://shopee.co/test"),
        123,
        0,
        "",
    )

    assert candidate.composition == ("video", "link")
