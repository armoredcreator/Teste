from datetime import datetime, timezone

from src.pattern_analyzer import (
    PATTERN_LINK_THEN_VIDEO,
    PATTERN_TWO_IMAGES_VIDEO_LINK,
    PATTERN_VIDEO_IMAGE_LINK,
    PATTERN_VIDEO_LINK,
    PATTERN_VIDEO_THEN_LINK,
    classify_messages,
)
from src.telegram_reader import TelegramMessage


DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def msg(i, *, video=False, image=False, urls=(), group=None):
    return TelegramMessage(
        source_id=1,
        message_id=i,
        date=DATE,
        grouped_id=group,
        has_video=video,
        has_image=image,
        urls=tuple(urls),
        text="",
    )


def test_five_required_patterns():
    messages = [
        msg(1, video=True, urls=("https://shopee.com.br/a",)),
        msg(2, video=True),
        msg(3, urls=("https://shopee.com.br/b",)),
        msg(4, urls=("https://shopee.com.br/c",)),
        msg(5, video=True),
        msg(6, video=True, group=100),
        msg(7, image=True, group=100),
        msg(8, urls=("https://shopee.com.br/d",)),
        msg(9, image=True, group=200),
        msg(10, image=True, group=200),
        msg(11, video=True, group=200),
        msg(12, urls=("https://shopee.com.br/e",)),
    ]

    matches = classify_messages(messages)

    assert [m.pattern for m in matches] == [
        PATTERN_VIDEO_LINK,
        PATTERN_VIDEO_THEN_LINK,
        PATTERN_LINK_THEN_VIDEO,
        PATTERN_VIDEO_IMAGE_LINK,
        PATTERN_TWO_IMAGES_VIDEO_LINK,
    ]


def test_group_order_is_strict():
    messages = [
        msg(1, image=True, group=10),
        msg(2, video=True, group=10),
        msg(3, urls=("https://shopee.com.br/a",)),
        msg(4, image=True, group=20),
        msg(5, image=True, group=20),
        msg(6, video=True, group=20),
        msg(7, urls=("https://shopee.com.br/b",)),
    ]

    matches = classify_messages(messages)

    assert len(matches) == 1
    assert matches[0].pattern == PATTERN_TWO_IMAGES_VIDEO_LINK


def test_link_before_video_does_not_become_video_then_link():
    messages = [
        msg(1, urls=("https://shopee.com.br/a",)),
        msg(2, video=True),
    ]

    matches = classify_messages(messages)

    assert [m.pattern for m in matches] == [PATTERN_LINK_THEN_VIDEO]
