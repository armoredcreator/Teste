from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class VisionUnresolvedError(RuntimeError):
    """Vision V1 could not resolve an exact Shopee product."""


@dataclass(frozen=True)
class VisionResult:
    affiliate_name: str
    affiliate_url: str
    affiliate_urls: tuple[str, ...] = ()
    publication_caption: str | None = None
    ia_context: dict[str, Any] | None = None
