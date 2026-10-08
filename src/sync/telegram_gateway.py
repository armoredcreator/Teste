from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient, functions


@dataclass(frozen=True)
class TelegramMessage:
    source_id: int
    message_id: int
    date: datetime | None
    grouped_id: int | None
    has_video: bool
    has_image: bool
    urls: tuple[str, ...]
    text: str


class TelethonTelegramGateway:
    """Telegram transport owned by ArmoredSync.

    This class only reads Telegram and materializes message metadata. It does
    not decide candidate state, download media, call Vision, or publish.
    """

    def __init__(self, api_id: int, api_hash: str, session_path: Path):
        self.client = TelegramClient(str(session_path), api_id, api_hash)

    async def connect(self) -> None:
        await self.client.start()

    async def close(self) -> None:
        await self.client.disconnect()

    async def source_title(self, source_id: int) -> str:
        entity = await self.client.get_entity(source_id)
        title = getattr(entity, "title", None) or getattr(entity, "username", None)
        return str(title or source_id)

    async def source_mode(self, source_id: int) -> str:
        entity = await self.client.get_entity(source_id)
        return "forum" if bool(getattr(entity, "forum", False)) else "source"

    async def discover_topics(self, source_id: int) -> list[tuple[int, str]]:
        result = await self.client(
            functions.messages.GetForumTopicsRequest(
                peer=source_id, q=None, offset_date=None,
                offset_id=0, offset_topic=0, limit=100,
            )
        )
        topics: list[tuple[int, str]] = []
        for topic in getattr(result, "topics", []) or []:
            topic_id = getattr(topic, "id", None)
            if topic_id is not None:
                topics.append(
                    (int(topic_id), str(getattr(topic, "title", None) or topic_id).strip())
                )
        return topics

    async def iter_topic(self, source_id: int, topic_id: int) -> AsyncIterator[TelegramMessage]:
        offset_id = 0
        while True:
            result = await self.client(
                functions.messages.GetRepliesRequest(
                    peer=source_id, msg_id=topic_id, offset_id=offset_id,
                    offset_date=None, add_offset=0, limit=100,
                    max_id=0, min_id=0, hash=0,
                )
            )
            messages = list(getattr(result, "messages", []) or [])
            if not messages:
                return
            for message in messages:
                yield self._convert(source_id, message)
            ids = [int(getattr(message, "id", 0) or 0) for message in messages]
            ids = [value for value in ids if value > 0]
            if not ids:
                return
            oldest = min(ids)
            if oldest == offset_id:
                return
            offset_id = oldest

    async def iter_source(self, source_id: int) -> AsyncIterator[TelegramMessage]:
        async for message in self.client.iter_messages(source_id, reverse=True):
            yield self._convert(source_id, message)

    def _convert(self, source_id: int, message) -> TelegramMessage:
        text = message.raw_text or ""
        urls = tuple(sorted(set(extract_shopee_short_urls(message, text))))
        document = getattr(message, "document", None)
        mime = getattr(document, "mime_type", None) if document else None
        has_video = bool(getattr(message, "video", None)) or bool(
            mime and mime.lower().startswith("video/")
        )
        has_image = bool(getattr(message, "photo", None)) or bool(
            mime and mime.lower().startswith("image/")
        )
        return TelegramMessage(
            source_id=source_id,
            message_id=int(getattr(message, "id", 0) or 0),
            date=getattr(message, "date", None),
            grouped_id=getattr(message, "grouped_id", None),
            has_video=has_video,
            has_image=has_image,
            urls=urls,
            text=text,
        )


def extract_shopee_short_urls(message, text: str) -> list[str]:
    found: list[str] = []

    for entity in getattr(message, "entities", None) or []:
        url = getattr(entity, "url", None)
        if url and is_shopee_short_url(url):
            found.append(url)

    import re
    for raw in re.findall(r"https?://[^\s<>]+", text, flags=re.IGNORECASE):
        url = raw.rstrip(".,;:!?)]}>\\\"'")
        if is_shopee_short_url(url):
            found.append(url)

    return found


def is_shopee_short_url(url: str) -> bool:
    """ArmoredSync input contract: https://s.shopee.com.br/<alphanumeric-code>."""
    from urllib.parse import urlparse
    import re

    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme.lower() != "https":
        return False
    if (parsed.hostname or "").lower() != "s.shopee.com.br":
        return False
    if parsed.query or parsed.fragment:
        return False
    return bool(re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path))
