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
    """Read history using the same discovery state machine as ArmoredSync.

    This is read-only: it never materializes Telegram media and never checks
    or mutates the production SQLite database.
    """
    topics = await reader.discover_topics(source_id)
    for topic_id, topic_name in topics:
        pending_video: TelegramMessage | None = None
        pending_group_id: int | None = None
        pending_group: list[TelegramMessage] = []

        async def flush_group() -> AsyncIterator[SyncCandidate]:
            nonlocal pending_group_id, pending_group
            if pending_group:
                candidate = _resolve_group(
                    pending_group,
                    source_id,
                    topic_id,
                    topic_name,
                )
                if candidate is not None:
                    yield candidate
            pending_group_id = None
            pending_group = []

        async for message in reader.iter_topic(source_id, topic_id):
            if message.grouped_id is not None:
                grouped_id = int(message.grouped_id)
                if pending_group_id is None:
                    if pending_video is not None:
                        candidate = _resolve_pending(
                            pending_video,
                            source_id,
                            topic_id,
                            topic_name,
                        )
                        if candidate is not None:
                            yield candidate
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
                    url = message.urls[0] if message.urls else None
                    if url:
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

            if message.urls:
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
            candidate = _resolve_pending(
                pending_video,
                source_id,
                topic_id,
                topic_name,
            )
            if candidate is not None:
                yield candidate


def _resolve_pending(
    video: TelegramMessage,
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate | None:
    if not video.urls:
        return None
    return _make_direct(video, source_id, topic_id, topic_name)


def _resolve_group(
    messages: list[TelegramMessage],
    source_id: int,
    topic_id: int,
    topic_name: str,
) -> SyncCandidate | None:
    videos = [m for m in messages if m.has_video]
    if not videos:
        return None

    unique: dict[str, str] = {}
    for message in messages:
        for url in message.urls:
            unique.setdefault(url.casefold(), url)

    if len(unique) == 1:
        url = next(iter(unique.values()))
        linked = [m for m in videos if url.casefold() in {u.casefold() for u in m.urls}]
        selected = min(linked or videos, key=lambda m: m.message_id)
        return _make_group(
            messages,
            selected,
            url,
            source_id,
            topic_id,
            topic_name,
        )

    if len(unique) > 1:
        # Exact Sync rule: with multiple distinct links, only videos carrying
        # their own link are safe; links attached only to photos are ambiguous.
        for selected in sorted(videos, key=lambda m: m.message_id):
            if not selected.urls:
                continue
            url = selected.urls[0]
            return _make_group(
                messages,
                selected,
                url,
                source_id,
                topic_id,
                topic_name,
            )

    return None


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
        message_ids=tuple(m.message_id for m in messages),
        grouped_ids=tuple(
            sorted({m.grouped_id for m in messages if m.grouped_id is not None})
        ),
        urls=(url,),
        composition=tuple(_kind(m) for m in messages) + ("link",),
        selected_message_id=selected.message_id,
        selected=selected,
        details=tuple(_detail(m) for m in messages),
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
