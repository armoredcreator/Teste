from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..core.storage import Storage
from ..historical_database import HistoricalDatabase
from ..sync.telegram_gateway import TelethonTelegramGateway


class ArmoredStock:
    """Materializes exactly one Vision-approved historical candidate.

    Stock is the only historical stage allowed to download media. A candidate
    reaches this stage only after Vision persisted VISION_ACCEPTED in SQLite.
    """

    def __init__(self, db: HistoricalDatabase, root: Path, gateway: TelethonTelegramGateway | None = None):
        self.db = db
        self.root = Path(root).resolve()
        self.storage = Storage(self.root)
        self.gateway = gateway

    async def process_one(self, row) -> str:
        candidate_id = int(row["id"])
        vision = self.db.vision_result(candidate_id)
        if vision is None or str(vision["status"]) != "VISION_ACCEPTED":
            raise RuntimeError(f"stock-requires-vision-accepted:{candidate_id}")

        self.db.set_stock_processing(candidate_id)
        gateway = self.gateway
        own_gateway = gateway is None
        if gateway is None:
            gateway = TelethonTelegramGateway(
                api_id=int(os.environ["TELEGRAM_API_ID"]),
                api_hash=os.environ["TELEGRAM_API_HASH"],
                session_path=self.root / "credentials" / "telegram" / "armoredsync",
            )

        try:
            await gateway.connect()
            messages = await gateway.client.get_messages(
                int(row["source_id"]), ids=int(row["selected_message_id"])
            )
            message = messages[0] if isinstance(messages, list) else messages
            if message is None or not getattr(message, "video", None):
                raise RuntimeError("stock-selected-telegram-message-has-no-video")

            target = self.storage.original(candidate_id)
            await self._download_to(gateway, message, target)
            self.db.set_stock_ready(candidate_id, target)
            return "STOCK_READY"
        except Exception as exc:
            self.db.set_stock_retryable_error(candidate_id, str(exc))
            return "STOCK_PROCESSING"
        finally:
            if own_gateway:
                await gateway.close()

    async def _download_to(self, gateway, message, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return
        expected = getattr(getattr(message, "document", None), "size", None)
        idle_timeout = max(1, int(os.getenv("ARMORED_STOCK_DOWNLOAD_IDLE_TIMEOUT", "60")))
        iterator = gateway.client.iter_download(message, request_size=1024 * 1024).__aiter__()
        with target.open("wb") as output:
            while True:
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=idle_timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"download Telegram sem progresso por {idle_timeout}s para {getattr(message, 'id', '?')}"
                    ) from exc
                if chunk:
                    output.write(chunk)
        size = target.stat().st_size if target.exists() else 0
        if size <= 0:
            raise RuntimeError("stock-download-empty")
        if expected is not None and size != int(expected):
            raise RuntimeError(f"stock-download-incomplete:{size}/{int(expected)}")
