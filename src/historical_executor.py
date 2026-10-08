from __future__ import annotations

import asyncio
import hashlib
import importlib
import os
import sys
from pathlib import Path
from typing import Any

from .historical_database import HistoricalDatabase
from .config import load_config
from .telegram_reader import TelegramReader


ROOT = Path(__file__).resolve().parents[1]


def _base_root() -> Path:
    raw = (os.getenv("ARMORED_BASE_ROOT") or "").strip()
    if not raw:
        raise RuntimeError(
            "ARMORED_BASE_ROOT não configurado; a execução usa o armoredcreator-test congelado "
            "sem copiar ou modificar o repositório de referência."
        )
    path = Path(raw).expanduser().resolve()
    if not (path / "armored_core" / "coordinator.py").is_file():
        raise FileNotFoundError(f"armoredcreator-test inválido: {path}")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path


def _import_base() -> dict[str, Any]:
    _base_root()
    return {
        "Database": importlib.import_module("armored_core.database").Database,
        "State": importlib.import_module("armored_core.models").State,
        "Storage": importlib.import_module("armored_core.storage").Storage,
        "Pipeline": importlib.import_module("armored_core.pipeline").Pipeline,
        "Recovery": importlib.import_module("armored_core.recovery").Recovery,
        "ArmoredVision": importlib.import_module("ArmoredVision.service").ArmoredVision,
        "ArmoredStudio": importlib.import_module("ArmoredStudio.service").ArmoredStudio,
        "ArmoredIA": importlib.import_module("ArmoredIA.service").ArmoredIA,
        "ArmoredHub": importlib.import_module("ArmoredHub.service").ArmoredHub,
    }


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "armored.db"


def historical_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def source_root(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id)


class SessionAwareHub:
    """Keep the frozen Hub implementation while reusing Teste's Telegram session."""

    def __init__(self, hub: Any, session_path: Path):
        self._hub = hub
        self._session_path = Path(session_path)

    def __getattr__(self, name: str):
        return getattr(self._hub, name)

    def _telegram_session_path(self) -> Path:
        return self._session_path


class HistoricalExecutor:
    """One-item historical executor.

    Historical.db is the immutable discovery inventory. The frozen
    armoredcreator-test Database is the execution source of truth for each
    isolated source. No physical queue or pre-download batch is created.

    Crucially, Vision V1 runs after SQLite reservation but before Telegram
    media materialization. Only an accepted V1 result is allowed to download.
    """

    def __init__(self, source_id: int):
        self.source_id = int(source_id)
        self.source_root = source_root(self.source_id)
        self.historical = HistoricalDatabase(historical_path(self.source_id), self.source_id)
        base = _import_base()

        self.Database = base["Database"]
        self.State = base["State"]
        self.Storage = base["Storage"]
        self.Pipeline = base["Pipeline"]
        self.Recovery = base["Recovery"]

        self.storage = self.Storage(self.source_root)
        self.db = self.Database(database_path(self.source_id))
        self.vision = base["ArmoredVision"]()
        self.studio = base["ArmoredStudio"](self.source_root)
        self.ia = base["ArmoredIA"]()

        base_root = _base_root()
        hub = base["ArmoredHub"](base_root, self.db)
        self.publisher = SessionAwareHub(
            hub,
            ROOT / "credentials" / "telegram" / "armoredsync",
        )

        self.pipeline = self.Pipeline(
            self.db,
            self.storage,
            self.vision,
            self.studio,
            self.publisher,
            self.ia,
        )
        self.recovery = self.Recovery(
            self.db,
            self.storage,
            self.vision,
            self.studio,
            self.publisher,
            self.ia,
        )
        self.reader = TelegramReader(
            api_id=load_config(ROOT).api_id,
            api_hash=load_config(ROOT).api_hash,
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
        if not getattr(raw, "video", None) and not getattr(raw, "document", None):
            raise RuntimeError(
                f"selected_message_id={selected_message_id} não contém vídeo"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        if partial.exists():
            partial.unlink()

        telegram_size = getattr(getattr(raw, "document", None), "size", None)
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
            ".mp4",
            original_url=str(candidate["original_url"]),
        )
        self.db.reserve_item(
            str(candidate["selected_message_id"]),
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
        if self.ia is not None and os.getenv("ARMORED_IA_ENABLED", "1") == "1" and os.getenv("ARMORED_IA_CAPTION_ENABLED", "1") == "1":
            self.db.transition(item_id, self.State.IA, "vision-complete-before-download")
        else:
            self.db.transition(item_id, self.State.STUDIO, "vision-complete-before-download")

    async def _recover_or_resume(self, candidate) -> bool:
        item_id = str(candidate["selected_message_id"])
        try:
            item = self.db.get(item_id)
        except KeyError:
            return False

        if item.state == self.State.PUBLISHED and item.cleanup_completed:
            self.historical.set_candidate_status(int(candidate["id"]), "PUBLISHED")
            return True

        if item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(int(candidate["id"]), "WAITING_VISION")
            return True

        if item.state in {self.State.RECOVERY, self.State.FAILED}:
            self.recovery.reconcile(item_id)
            item = self.db.get(item_id)

        if item.state == self.State.PUBLISHED and item.cleanup_completed:
            self.historical.set_candidate_status(int(candidate["id"]), "PUBLISHED")
            return True

        if item.state != self.State.WAITING_VISION and item.state != self.State.PUBLISHED:
            if item.original_path.is_file():
                self.pipeline.run(item_id)

        item = self.db.get(item_id)
        if item.state == self.State.PUBLISHED and item.cleanup_completed:
            self.historical.set_candidate_status(int(candidate["id"]), "PUBLISHED")
        elif item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(int(candidate["id"]), "WAITING_VISION")
        elif item.state == self.State.RECOVERY:
            self.historical.set_candidate_status(int(candidate["id"]), "RECOVERY")
        return True

    async def process_one(self, candidate) -> str:
        candidate_id = int(candidate["id"])
        item_id = str(candidate["selected_message_id"])
        self.historical.set_candidate_status(candidate_id, "RESERVED")
        item_id = self._reserve(candidate)

        item = self.db.get(item_id)
        if item.state == self.State.RECEIVED:
            try:
                self._set_vision_result(item_id)
            except Exception as exc:
                if type(exc).__name__ == "VisionUnresolvedError":
                    self.db.mark_vision_waiting(item_id, str(exc))
                    self.historical.set_candidate_status(candidate_id, "WAITING_VISION")
                    return "WAITING_VISION"
                self.db.transition(item_id, self.State.RECOVERY, f"VisionError: {exc}")
                self.historical.set_candidate_status(candidate_id, "RECOVERY")
                return "RECOVERY"

        item = self.db.get(item_id)
        if item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(candidate_id, "WAITING_VISION")
            return "WAITING_VISION"

        if not item.original_path.is_file():
            self.historical.set_candidate_status(candidate_id, "DOWNLOADING")
            await self._materialize(int(candidate["selected_message_id"]), item.original_path)

        item = self.db.get(item_id)
        self.historical.set_candidate_status(candidate_id, "PROCESSING")
        try:
            self.pipeline.run(item_id)
        except Exception:
            item = self.db.get(item_id)
            if item.state != self.State.RECOVERY:
                self.db.transition(item_id, self.State.RECOVERY, "pipeline-error")
            self.historical.set_candidate_status(candidate_id, "RECOVERY")
            return "RECOVERY"

        item = self.db.get(item_id)
        if item.state == self.State.PUBLISHED and item.cleanup_completed:
            self.historical.set_candidate_status(candidate_id, "PUBLISHED")
            return "PUBLISHED"
        if item.state == self.State.WAITING_VISION:
            self.historical.set_candidate_status(candidate_id, "WAITING_VISION")
            return "WAITING_VISION"
        if item.state == self.State.RECOVERY:
            self.historical.set_candidate_status(candidate_id, "RECOVERY")
            return "RECOVERY"
        return item.state.value

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
