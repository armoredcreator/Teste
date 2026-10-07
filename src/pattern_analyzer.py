from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .telegram_reader import TelegramMessage


PATTERN_VIDEO_LINK = "video + link"
PATTERN_VIDEO_THEN_LINK = "video → link"
PATTERN_VIDEO_IMAGE_LINK = "video + image + link"
PATTERN_TWO_IMAGES_VIDEO_LINK = "image + image + video + link"
PATTERN_LINK_THEN_VIDEO = "link + video"

PATTERNS = (
    PATTERN_VIDEO_LINK,
    PATTERN_VIDEO_THEN_LINK,
    PATTERN_VIDEO_IMAGE_LINK,
    PATTERN_TWO_IMAGES_VIDEO_LINK,
    PATTERN_LINK_THEN_VIDEO,
)


@dataclass(frozen=True)
class Match:
    pattern: str
    source_id: int
    message_ids: tuple[int, ...]
    grouped_ids: tuple[int, ...]
    urls: tuple[str, ...]
    composition: tuple[str, ...]
    details: tuple[dict, ...]


def classify_messages(messages: Iterable[TelegramMessage]) -> list[Match]:
    items = list(messages)
    matches: list[Match] = []
    i = 0

    while i < len(items):
        current = items[i]

        if current.grouped_id is not None:
            group_end = i + 1
            while group_end < len(items) and items[group_end].grouped_id == current.grouped_id:
                group_end += 1

            group = items[i:group_end]
            next_message = items[group_end] if group_end < len(items) else None
            group_match = _classify_group(group, next_message)

            if group_match:
                matches.append(group_match)

            i = group_end
            continue

        if current.has_video and current.urls and not current.has_image:
            matches.append(
                Match(
                    pattern=PATTERN_VIDEO_LINK,
                    source_id=current.source_id,
                    message_ids=(current.message_id,),
                    grouped_ids=(),
                    urls=current.urls,
                    composition=("video", "link"),
                    details=(_detail(current),),
                )
            )
            i += 1
            continue

        if _is_link_only(current):
            if i + 1 < len(items) and _is_standalone_video(items[i + 1]):
                nxt = items[i + 1]
                matches.append(
                    Match(
                        pattern=PATTERN_LINK_THEN_VIDEO,
                        source_id=current.source_id,
                        message_ids=(current.message_id, nxt.message_id),
                        grouped_ids=(),
                        urls=current.urls,
                        composition=("link", "video"),
                        details=(_detail(current), _detail(nxt)),
                    )
                )
                i += 2
                continue

            i += 1
            continue

        if _is_standalone_video(current):
            if i + 1 < len(items) and _is_link_only(items[i + 1]):
                nxt = items[i + 1]
                matches.append(
                    Match(
                        pattern=PATTERN_VIDEO_THEN_LINK,
                        source_id=current.source_id,
                        message_ids=(current.message_id, nxt.message_id),
                        grouped_ids=(),
                        urls=nxt.urls,
                        composition=("video", "link"),
                        details=(_detail(current), _detail(nxt)),
                    )
                )
                i += 2
                continue

        i += 1

    return matches


def _classify_group(
    group: list[TelegramMessage],
    next_message: TelegramMessage | None,
) -> Match | None:
    kinds = [
        "video" if m.has_video else "image" if m.has_image else "other"
        for m in group
    ]

    if kinds not in (["video", "image"], ["image", "image", "video"]):
        return None

    # The link must occur after the media composition:
    # either on the final media message or in the immediately following
    # standalone link message.
    urls = list(group[-1].urls)
    external_link = False

    if not urls and next_message is not None and _is_link_only(next_message):
        urls = list(next_message.urls)
        external_link = True

    if not urls:
        return None

    details = tuple(_detail(m) for m in group)
    message_ids = tuple(m.message_id for m in group)

    if external_link:
        details = details + (_detail(next_message),)
        message_ids = message_ids + (next_message.message_id,)

    if kinds == ["video", "image"]:
        return Match(
            pattern=PATTERN_VIDEO_IMAGE_LINK,
            source_id=group[0].source_id,
            message_ids=message_ids,
            grouped_ids=(group[0].grouped_id,) if group[0].grouped_id is not None else (),
            urls=tuple(urls),
            composition=("video", "image", "link"),
            details=details,
        )

    return Match(
        pattern=PATTERN_TWO_IMAGES_VIDEO_LINK,
        source_id=group[0].source_id,
        message_ids=message_ids,
        grouped_ids=(group[0].grouped_id,) if group[0].grouped_id is not None else (),
        urls=tuple(urls),
        composition=("image", "image", "video", "link"),
        details=details,
    )


def _is_link_only(message: TelegramMessage) -> bool:
    return bool(message.urls) and not message.has_video and not message.has_image


def _is_standalone_video(message: TelegramMessage) -> bool:
    return message.has_video and message.grouped_id is None


def _unique_urls(messages: Iterable[TelegramMessage]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for message in messages:
        for url in message.urls:
            if url not in seen:
                seen.add(url)
                result.append(url)

    return result


def _detail(message: TelegramMessage) -> dict:
    kind = "video" if message.has_video else "image" if message.has_image else "link/text"
    return {
        "message_id": message.message_id,
        "date": message.date.isoformat() if message.date else None,
        "grouped_id": message.grouped_id,
        "type": kind,
        "urls": list(message.urls),
    }
