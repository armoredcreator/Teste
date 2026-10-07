from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from .telegram_reader import TelegramReader, TelegramMessage


@dataclass(frozen=True)
class SyncCandidate:
    source_id: int
    topic_id: int
    topic_name: str
    message_ids: tuple[int, ...]
    grouped_ids: tuple[int, ...]
    urls: tuple[str, ...]
    composition: tuple[str, ...]
    selected_message_id: int
    selected: TelegramMessage
    details: tuple[dict, ...]
    kind: str  # "direct", "followup", "group"


def _kind(message: TelegramMessage) -> str:
    if message.has_video:
        return "video"
    if message.has_image:
        return "image"
    return "other"


async def discover_sync_candidates(
    reader: TelegramReader,
    source_id: int,
) -> AsyncIterator[SyncCandidate]:
    """Historical candidate state machine adapted from ArmoredSync.

    This module is intentionally read-only: it never downloads media and never
    consults or mutates the production SQLite database.
    """
    topics = await reader.discover_topics(source_id)

    for topic_id, topic_name in topics:
        pending_video: TelegramMessage | None = None
        pending_group_id: int | None = None
        pending_group: list[TelegramMessage] = []

        async def flush_group() -> AsyncIterator[SyncCandidate]:
            nonlocal pending_group_id, pending_group
            if pending_group:
                for candidate in _resolve_group(
                    pending_group,
                    source_id,
                    topic_id,
                    topic_name,
                ):
                    yield candidate
            pending_group_id = None
            pending_group = []

        async for message in reader.iter_topic(source_id, topic_id):
            grouped_id = message.grouped_id
            if grouped_id is not None:
                grouped_id = int(grouped_id)

                if pending_group_id is None:
                    if pending_video is not None:
                        candidate = _resolve_pending(pending_video)
                        if candidate is not None:
                            yield _with_topic(candidate, source_id, topic_id, topic_name)
                        pending_video = None

                    pending_group_id = grouped_id
                    pending_group = [message]

                elif grouped_id == pending_group_id:
                    pending_group.append(message)

                else:
                    async for candidate in flush_group():
                        yield candidate
                    pending_group_id = grouped_id
                    pending_group = [message]

                continue

            if pending_group:
                async for candidate in flush_group():
                    yield candidate

            if pending_video is not None:
                if not message.has_video:
                    original_url = message.urls[0] if message.urls else None
                    if original_url:
                        yield _make_followup(
                            pending_video,
                            message,
                            source_id,
                            topic_id,
                            topic_name,
                        )
                pending_video = None

            if not message.has_video:
                continue

            original_url = message.urls[0] if message.urls else None
            if original_url is not None:
                yield _make_direct(
                    message,
                    source_id,
                    topic_id,
                    topic_name,
                )
                continue

            pending_video = message

        if pending_group:
            async for candidate in flush_group():
                yield candidate

        if pending_video is not None:
            original_url = pending_video.urls[0] if pending_video.urls else None
            if original_url is not None:
                yield _make_direct(
                    pending_video,
                    source_id,
                    topic_id,
                    topic_name,
                )


def _resolve_pending(message: TelegramMessage) -> SyncCandidate | None:
    if not message.has_video or not message.urls:
        return None
    return _make_direct(message, message.source_id, 0, "")


def _with_topic(
    candidate: SyncCandidate,
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate:
    return SyncCandidate(
        source_id=source_id,
        topic_id=topic_id,
        topic_name=topic_name,
        message_ids=candidate.message_ids,
        grouped_ids=candidate.grouped_ids,
        urls=candidate.urls,
        composition=candidate.composition,
        selected_message_id=candidate.selected_message_id,
        selected=candidate.selected,
        details=candidate.details,
        kind=candidate.kind,
    )


def _resolve_group(
    messages: list[TelegramMessage],
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> list[SyncCandidate]:
    videos = [message for message in messages if message.has_video]
    if not videos:
        return []

    unique_links: dict[str, str] = {}
    for message in messages:
        for url in message.urls:
            unique_links.setdefault(url.casefold(), url)

    if len(unique_links) == 1:
        original_url = next(iter(unique_links.values()))
        linked_videos = [message for message in videos if message.urls]
        selected = min(
            linked_videos or videos,
            key=lambda message: message.message_id,
        )
        return [
            _make_group(
                messages,
                selected,
                original_url,
                source_id,
                topic_id,
                topic_name,
            )
        ]

    if len(unique_links) > 1:
        candidates: list[SyncCandidate] = []
        emitted_links: set[str] = set()

        for message in sorted(videos, key=lambda value: value.message_id):
            if not message.urls:
                continue

            url = message.urls[0]
            key = url.casefold()
            if key in emitted_links:
                continue

            emitted_links.add(key)
            candidates.append(
                _make_group(
                    messages,
                    message,
                    url,
                    source_id,
                    topic_id,
                    topic_name,
                )
            )

        return candidates

    return []


def _make_direct(
    message: TelegramMessage,
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate:
    return SyncCandidate(
        source_id=source_id,
        topic_id=topic_id,
        topic_name=topic_name,
        message_ids=(message.message_id,),
        grouped_ids=(),
        urls=message.urls,
        composition=("video", "link"),
        selected_message_id=message.message_id,
        selected=message,
        details=(_detail(message),),
        kind="direct",
    )


def _make_followup(
    video: TelegramMessage,
    link_message: TelegramMessage,
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate:
    return SyncCandidate(
        source_id=source_id,
        topic_id=topic_id,
        topic_name=topic_name,
        message_ids=(video.message_id, link_message.message_id),
        grouped_ids=(),
        urls=link_message.urls,
        composition=("video", "link"),
        selected_message_id=video.message_id,
        selected=video,
        details=(_detail(video), _detail(link_message)),
        kind="followup",
    )


def _make_group(
    messages: list[TelegramMessage],
    selected: TelegramMessage,
    url: str,
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate:
    return SyncCandidate(
        source_id=source_id,
        topic_id=topic_id,
        topic_name=topic_name,
        message_ids=tuple(message.message_id for message in messages),
        grouped_ids=tuple(
            sorted(
                {
                    int(message.grouped_id)
                    for message in messages
                    if message.grouped_id is not None
                }
            )
        ),
        urls=(url,),
        composition=tuple(_kind(message) for message in messages) + ("link",),
        selected_message_id=selected.message_id,
        selected=selected,
        details=tuple(_detail(message) for message in messages),
        kind="group",
    )


def _detail(message: TelegramMessage) -> dict:
    return {
        "message_id": message.message_id,
        "date": message.date.isoformat() if message.date else None,
        "grouped_id": message.grouped_id,
        "type": _kind(message),
        "urls": list(message.urls),
    }
