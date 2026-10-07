from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient


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


class TelegramReader:
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

    async def iter_source(self, source_id: int) -> AsyncIterator[TelegramMessage]:
        async for message in self.client.iter_messages(source_id, reverse=True):
            text = message.raw_text or ""
            urls = tuple(sorted(set(_extract_shopee_urls(message, text))))
            document = getattr(message, "document", None)
            mime = getattr(document, "mime_type", None) if document else None
            has_video = bool(getattr(message, "video", None)) or bool(
                mime and mime.lower().startswith("video/")
            )
            has_image = bool(getattr(message, "photo", None)) or bool(
                mime and mime.lower().startswith("image/")
            )
            grouped_id = getattr(message, "grouped_id", None)

            yield TelegramMessage(
                source_id=source_id,
                message_id=message.id,
                date=message.date,
                grouped_id=grouped_id,
                has_video=has_video,
                has_image=has_image,
                urls=urls,
                text=text,
            )


def _extract_shopee_urls(message, text: str) -> list[str]:
    found: list[str] = []

    for entity in getattr(message, "entities", None) or []:
        url = getattr(entity, "url", None)
        if url and _is_shopee_url(url):
            found.append(url)

    import re

    for raw in re.findall(r"https?://[^\\s<>]+", text, flags=re.IGNORECASE):
        url = raw.rstrip(".,;:!?)]}>\\\"'")
        if _is_shopee_url(url):
            found.append(url)

    return found


def _is_shopee_url(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False

    return (
        host == "shopee.com.br"
        or host.endswith(".shopee.com.br")
        or host == "shopee.co"
        or host.endswith(".shopee.co")
        or host == "shopee.ee"
        or host.endswith(".shopee.ee")
    )
