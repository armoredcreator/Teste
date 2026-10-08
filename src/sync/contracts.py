from __future__ import annotations

from dataclasses import dataclass

from .telegram_gateway import TelegramMessage


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
    kind: str
