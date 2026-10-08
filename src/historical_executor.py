from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from .historical_database import HistoricalDatabase
from .config import load_config
from .sync import TelethonTelegramGateway
from .vision import ArmoredVision, VisionUnresolvedError
from .core.database import Database
from .core.models import State
from .core.storage import Storage


ROOT = Path(__file__).resolve().parents[1]


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "armored.db"


def historical_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def source_root(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id)


class HistoricalExecutor:
    """Historical catch-up executor, migrated stage by stage.

    The current migration stage is Vision-in-bulk. Materialization and all
    downstream tools are deliberately kept out of this stage.
    """

    def __init__(self, source_id: int):
        load_config(ROOT)
        self.source_id = int(source_id)
        self.source_root = source_root(self.source_id)
        inventory_path = historical_path(self.source_id)
        if not inventory_path.is_file():
            raise RuntimeError(
                f"Inventory histórica ausente para source {self.source_id}: "
                f"{inventory_path}. Execute scripts/collect_historical.py "
                f"--source <1|2|3> antes do Vision."
            )

        self.historical = HistoricalDatabase(inventory_path, self.source_id)
        inventory_total = self.historical.total()
        if inventory_total <= 0:
            self.historical.close()
            raise RuntimeError(
                f"Inventory histórica vazia para source {self.source_id}: "
                f"{inventory_path}. O Vision não pode avançar com zero candidatos. "
                f"Reconstrua a inventory com scripts/collect_historical.py "
                f"--source <1|2|3>."
            )

        self.State = State
        self.Database = Database
        self.Storage = Storage
        self.storage = self.Storage(self.source_root)
        self.db = self.Database(database_path(self.source_id))
        self.vision = ArmoredVision()

        # Deliberately absent in this migration stage.
        self.studio = None
        self.ia = None
        self.publisher = None
        self.pipeline = None
        self.recovery = None

        config = load_config(ROOT)
        self.reader = TelethonTelegramGateway(
            api_id=config.api_id,
            api_hash=config.api_hash,
            session_path=ROOT / "credentials" / "telegram" / "armoredsync",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def _materialize(self, selected_message_id: int, target: Path) -> None:
        raw = await self.reader.client.get_messages(
            self.source_id,
            ids=int(selected_message_id),
        )
        if raw is None:
            raise FileNotFoundError(
                f"Telegram message {selected_message_id} não encontrado na fonte {self.source_id}"
            )
        if isinstance(raw, list):
            raw = next((message for message in raw if message is not None), None)
        if raw is None:
            raise FileNotFoundError(
                f"Telegram message {selected_message_id} não retornou mídia"
            )

        document = getattr(raw, "document", None)
        mime = str(getattr(document, "mime_type", "") or "").lower()
        if not getattr(raw, "video", None) and not mime.startswith("video/"):
            raise RuntimeError(
                f"selected_message_id={selected_message_id} não contém vídeo"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        if partial.exists():
            partial.unlink()

        telegram_size = getattr(
            getattr(raw, "document", None), "size", None
        )
        idle_timeout = max(
            1,
            int(os.getenv("ARMORED_SYNC_DOWNLOAD_IDLE_TIMEOUT", "60")),
        )

        iterator = self.reader.client.iter_download(
            raw,
            request_size=1024 * 1024,
        ).__aiter__()

        with partial.open("wb") as output:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        iterator.__anext__(),
                        timeout=idle_timeout,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"download sem progresso por {idle_timeout}s "
                        f"para Telegram message {selected_message_id}"
                    ) from exc

                if chunk:
                    output.write(chunk)

        size = partial.stat().st_size if partial.exists() else 0
        if size <= 0:
            raise RuntimeError("download retornou arquivo vazio")
        if telegram_size is not None and size != int(telegram_size):
            raise RuntimeError(
                f"download incompleto: {size} bytes de {int(telegram_size)}"
            )

        partial.replace(target)
        self.db.finalize_original_path(
            str(selected_message_id),
            target,
            self._sha256(target),
        )

    def _reserve(self, candidate) -> str:
        item_id = str(candidate["selected_message_id"])
        original = self.storage.original(
            item_id,
            original_url=str(candidate["original_url"]),
        )
        self.db.reserve_item(
            item_id,
            source_id=str(self.source_id),
            topic_id=int(candidate["topic_id"]),
            topic_name=str(candidate["topic_name"] or ""),
            original_url=str(candidate["original_url"]),
            original_path=original,
        )
        return item_id

    def _set_vision_result(self, item_id: str) -> None:
        item = self.db.get(item_id)
        result = self.vision.identify(item)
        self.db.set_vision(
            item_id,
            result.affiliate_name,
            result.affiliate_url,
            affiliate_urls=getattr(result, "affiliate_urls", ()),
            publication_caption=None,
            ia_context=getattr(result, "ia_context", None),
        )

        # This stage intentionally stops before Studio/IA/Hub. Vision data is
        # persisted, but the item must remain resumable at the materialization
        # boundary rather than being transitioned into downstream processing.
        refreshed = self.db.get(item_id)
        if refreshed.state not in {self.State.RECEIVED, self.State.VISION}:
            raise RuntimeError(
                f"estado inesperado após Vision: {refreshed.state}"
            )

    def _ensure_reserved(self, candidate) -> str:
        item_id = str(candidate["selected_message_id"])
        try:
            self.db.get(item_id)
        except KeyError:
            self._reserve(candidate)
        return item_id

    def process_vision_one(self, candidate) -> str:
        """Run V1 Vision for one persisted historical candidate, without media."""
        candidate_id = int(candidate["id"])
        item_id = self._ensure_reserved(candidate)
        self.historical.set_candidate_status(candidate_id, "VISION_PROCESSING")

        item = self.db.get(item_id)
        if item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(candidate_id, "WAITING_VISION")
            return "WAITING_VISION"

        if item.state not in {self.State.RECEIVED, self.State.VISION}:
            raise RuntimeError(
                f"estado inesperado antes da Vision: {item.state}"
            )

        try:
            if item.state == self.State.RECEIVED:
                self._set_vision_result(item_id)
        except VisionUnresolvedError as exc:
            self.db.mark_vision_waiting(item_id, str(exc))
            self.historical.set_candidate_status(
                candidate_id, "WAITING_VISION"
            )
            return "WAITING_VISION"
        except Exception:
            # A technical Vision failure leaves the candidate eligible for a
            # retry and stops this source before the next source can start.
            self.historical.set_candidate_status(candidate_id, "DISCOVERED")
            raise

        self.historical.set_candidate_status(candidate_id, "VISION_ACCEPTED")
        return "VISION_ACCEPTED"

    async def run_vision_batch(self) -> None:
        """Drain the complete Vision stage for this source before downloads.

        Vision operates exclusively on the persisted historical candidate URL
        and the native SQLite item. Telegram media is deliberately not touched
        here; Telegram is reopened only by the later materialization stage.
        """
        processed = 0
        accepted = 0
        waiting = 0
        try:
            while True:
                candidate = self.historical.next_vision_candidate()
                if candidate is None:
                    print(
                        f"[VISION][SOURCE {self.source_id}] "
                        f"COMPLETED processed={processed} "
                        f"accepted={accepted} waiting={waiting}",
                        flush=True,
                    )
                    return

                outcome = self.process_vision_one(candidate)
                processed += 1
                if outcome == "VISION_ACCEPTED":
                    accepted += 1
                elif outcome == "WAITING_VISION":
                    waiting += 1

                print(
                    f"[VISION][SOURCE {self.source_id}] "
                    f"candidate={candidate['id']} "
                    f"selected={candidate['selected_message_id']} "
                    f"outcome={outcome}",
                    flush=True,
                )
        finally:
            self.historical.close()
            self.db.close()

    async def process_one(self, candidate) -> str:
        candidate_id = int(candidate["id"])
        item_id = str(candidate["selected_message_id"])

        self.historical.set_candidate_status(candidate_id, "RESERVED")
        item_id = self._reserve(candidate)

        item = self.db.get(item_id)
        if item.state == self.State.RECEIVED:
            try:
                self._set_vision_result(item_id)
            except VisionUnresolvedError as exc:
                self.db.mark_vision_waiting(item_id, str(exc))
                self.historical.set_candidate_status(
                    candidate_id, "WAITING_VISION"
                )
                return "WAITING_VISION"
            except Exception:
                # Technical Vision failure before immutable ORIGINAL: preserve
                # the candidate as RESERVED and stop this source.
                self.historical.set_candidate_status(candidate_id, "RESERVED")
                raise

        item = self.db.get(item_id)
        if item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(
                candidate_id, "WAITING_VISION"
            )
            return "WAITING_VISION"

        if not item.original_path.is_file():
            self.historical.set_candidate_status(candidate_id, "DOWNLOADING")
            try:
                await self._materialize(
                    int(candidate["selected_message_id"]),
                    item.original_path,
                )
            except Exception:
                # A failed/timeout download must never advance to the next
                # historical candidate.
                self.historical.set_candidate_status(candidate_id, "RESERVED")
                raise

        item = self.db.get(item_id)
        if not item.original_path.is_file():
            self.historical.set_candidate_status(candidate_id, "RESERVED")
            raise RuntimeError(
                f"ORIGINAL ausente após materialização: {item.original_path}"
            )

        self.historical.set_candidate_status(candidate_id, "MATERIALIZED")
        return "MATERIALIZED"

    async def run(self) -> None:
        await self.reader.connect()
        try:
            while True:
                candidate = self.historical.next_candidate()
                if candidate is None:
                    return
                outcome = await self.process_one(candidate)
                print(
                    f"[CATCH-UP][SOURCE {self.source_id}] "
                    f"candidate={candidate['id']} "
                    f"selected={candidate['selected_message_id']} "
                    f"outcome={outcome}",
                    flush=True,
                )
        finally:
            await self.reader.close()
            self.historical.close()
            self.db.close()


async def run_all() -> None:
    config = load_config(ROOT)
    for source_id in config.sources:
        print(f"\n=== SOURCE {source_id} ===", flush=True)
        executor = HistoricalExecutor(source_id)
        await executor.run()


if __name__ == "__main__":
    asyncio.run(run_all())
