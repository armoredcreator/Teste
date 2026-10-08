from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from .models import Item, PublicationCheck


class VisionUnresolvedError(RuntimeError):
    """Vision could not resolve the product with enough certainty."""


class PublicationUnknownError(RuntimeError):
    """Publication outcome is unresolved and must enter recovery."""


@dataclass(frozen=True)
class VisionResult:
    affiliate_name: str
    affiliate_url: str
    affiliate_urls: tuple[str, ...] = ()
    publication_caption: str | None = None
    ia_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class StudioResult:
    working_path: Path | None
    result_path: Path


@dataclass(frozen=True)
class PublicationResult:
    confirmed: bool
    message_id: str | None


class VisionService(Protocol):
    def identify(self, item: Item) -> VisionResult: ...


class StudioService(Protocol):
    def process(self, item: Item) -> StudioResult: ...


class AIService(Protocol):
    def generate_caption(self, context: dict[str, Any]) -> str: ...


class Publisher(Protocol):
    def check_publication(self, item: Item) -> PublicationCheck: ...
    def publish(self, item: Item) -> PublicationResult: ...


@dataclass(frozen=True)
class IngestMessage:
    telegram_message_id: str
    source_id: str = "telegram"
    topic_id: int | None = None
    topic_name: str | None = None
    original_url: str | None = None
    source_path: Path | None = None
    materialize: Callable[[Path], None] | Callable[[Path], Awaitable[None]] | None = None
