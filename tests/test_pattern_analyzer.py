import asyncio
from datetime import datetime, timezone

from src.pattern_analyzer import (
    PATTERN_TWO_IMAGES_VIDEO_LINK,
    PATTERN_VIDEO_IMAGE_LINK,
    PATTERN_VIDEO_LINK,
    PATTERN_VIDEO_THEN_LINK,
    classify_candidates,
)
from src.sync_discovery import _resolve_group, discover_sync_candidates
from src.telegram_reader import TelegramMessage


DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
URL_A = "https://shopee.com.br/a"
URL_B = "https://shopee.com.br/b"


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


class FakeReader:
    def __init__(self, topics, messages, *, mode="forum"):
        self._topics = topics
        self._messages = messages
        self._mode = mode

    async def source_mode(self, source_id):
        return self._mode

    async def discover_topics(self, source_id):
        return self._topics

    async def iter_topic(self, source_id, topic_id):
        for message in self._messages[topic_id]:
            yield message

    async def iter_source(self, source_id):
        for message in self._messages[0]:
            yield message


def collect(reader):
    async def run():
        return [
            candidate
            async for candidate in discover_sync_candidates(reader, 1)
        ]

    return asyncio.run(run())


def test_direct_video_with_link():
    reader = FakeReader(
        [(10, "topic")],
        {10: [msg(1, video=True, urls=(URL_A,))]},
    )

    candidates = collect(reader)

    assert len(candidates) == 1
    assert candidates[0].kind == "direct"
    assert classify_candidates(candidates[0]).pattern == PATTERN_VIDEO_LINK
    assert candidates[0].selected_message_id == 1


def test_video_then_link():
    reader = FakeReader(
        [(10, "topic")],
        {
            10: [
                msg(1, video=True),
                msg(2, urls=(URL_A,)),
            ]
        },
    )

    candidates = collect(reader)

    assert len(candidates) == 1
    assert candidates[0].kind == "followup"
    assert candidates[0].message_ids == (1, 2)
    assert classify_candidates(candidates[0]).pattern == PATTERN_VIDEO_THEN_LINK


def test_link_then_video_is_not_a_sync_candidate():
    reader = FakeReader(
        [(10, "topic")],
        {
            10: [
                msg(1, urls=(URL_A,)),
                msg(2, video=True),
            ]
        },
    )

    assert collect(reader) == []


def test_group_video_image_link():
    group = [
        msg(1, video=True, group=100),
        msg(2, image=True, urls=(URL_A,), group=100),
    ]

    candidates = _resolve_group(group, 1, 10, "topic")

    assert len(candidates) == 1
    assert candidates[0].kind == "group"
    assert candidates[0].selected_message_id == 1
    assert candidates[0].urls == (URL_A,)
    assert classify_candidates(candidates[0]).pattern == PATTERN_VIDEO_IMAGE_LINK


def test_group_two_images_video_link():
    group = [
        msg(1, image=True, group=100),
        msg(2, image=True, group=100),
        msg(3, video=True, urls=(URL_A,), group=100),
    ]

    candidates = _resolve_group(group, 1, 10, "topic")

    assert len(candidates) == 1
    assert candidates[0].selected_message_id == 3
    assert classify_candidates(candidates[0]).pattern == PATTERN_TWO_IMAGES_VIDEO_LINK


def test_group_single_unique_link_selects_lowest_linked_video():
    group = [
        msg(10, video=True, group=100),
        msg(5, video=True, urls=(URL_A,), group=100),
        msg(7, image=True, urls=(URL_A,), group=100),
    ]

    candidates = _resolve_group(group, 1, 10, "topic")

    assert len(candidates) == 1
    assert candidates[0].selected_message_id == 5


def test_group_multiple_links_emits_each_linked_video_once():
    group = [
        msg(10, image=True, urls=(URL_A,), group=100),
        msg(11, video=True, urls=(URL_A,), group=100),
        msg(12, video=True, urls=(URL_B,), group=100),
        msg(13, video=True, group=100),
    ]

    candidates = _resolve_group(group, 1, 10, "topic")

    assert [candidate.selected_message_id for candidate in candidates] == [11, 12]
    assert [candidate.urls for candidate in candidates] == [(URL_A,), (URL_B,)]


def test_group_without_video_emits_nothing():
    group = [
        msg(1, image=True, group=100),
        msg(2, image=True, urls=(URL_A,), group=100),
    ]

    assert _resolve_group(group, 1, 10, "topic") == []


def test_discovery_is_topic_scoped():
    reader = FakeReader(
        [(10, "first"), (20, "second")],
        {
            10: [msg(1, video=True, urls=(URL_A,))],
            20: [msg(2, video=True, urls=(URL_B,))],
        },
    )

    candidates = collect(reader)

    assert [(c.topic_id, c.selected_message_id) for c in candidates] == [
        (10, 1),
        (20, 2),
    ]


def test_discovery_without_topics_uses_source_history():
    reader = FakeReader(
        [],
        {
            0: [
                msg(1, video=True),
                msg(2, urls=(URL_A,)),
            ]
        },
        mode="source",
    )

    candidates = collect(reader)

    assert len(candidates) == 1
    assert candidates[0].topic_id == 0
    assert candidates[0].topic_name == ""
    assert candidates[0].kind == "followup"
    assert candidates[0].message_ids == (1, 2)
    assert classify_candidates(candidates[0]).pattern == PATTERN_VIDEO_THEN_LINK


def test_non_forum_link_then_video_is_not_a_sync_candidate():
    reader = FakeReader(
        [],
        {0: [msg(1, urls=(URL_A,)), msg(2, video=True)]},
        mode="source",
    )

    assert collect(reader) == []
