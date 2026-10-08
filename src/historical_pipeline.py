from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Iterable

from .config import load_config
from .core.database import Database
from .core.models import PublicationCheck, State
from .core.storage import Storage
from .historical_database import HistoricalDatabase
from . import historical_database as _hd
from .vision.service import ArmoredVision
from .vision.contracts import VisionUnresolvedError
from .vision.historical import HistoricalVisionRunner
from .stock.historical import HistoricalStockRunner
from .sync import TelethonTelegramGateway, discover_sync_candidates
from ArmoredIA.service import ArmoredIA
from ArmoredStudio.service import ArmoredStudio
from ArmoredHub.service import ArmoredHub


def database_path(root: Path, source_id: int) -> Path:
    return root / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def core_database_path(root: Path) -> Path:
    return root / "storage" / "database" / "armoredcreator.db"


def content_id(row) -> str:
    return f"{int(row['source_id'])}_{int(row['selected_message_id'])}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HistoricalToolDrain:
    """Logical stage drain: SQLite is the backlog; no physical queue exists."""

    def __init__(self, root: Path, source_ids: Iterable[int]):
        self.root = Path(root).resolve()
        self.source_ids = tuple(int(x) for x in source_ids)
        self.storage = Storage(self.root)
        self.core = Database(core_database_path(self.root))

    def close(self) -> None:
        self.core.close()
    async def ensure_sync_inventory(self) -> dict[str, int]:
        """Sync is the first logical stage; SQLite inventory is its durable output."""
        config = load_config(self.root)
        session_dir = self.root / "credentials" / "telegram"
        session_dir.mkdir(parents=True, exist_ok=True)
        gateway = TelethonTelegramGateway(
            api_id=config.api_id,
            api_hash=config.api_hash,
            session_path=session_dir / "armoredsync",
        )
        totals = {"seen": 0, "inserted": 0}
        try:
            await gateway.connect()
            for sid in self.source_ids:
                db = HistoricalDatabase(database_path(self.root, sid), sid)
                try:
                    if db.has_completed_run():
                        continue
                    title = await gateway.source_title(sid)
                    mode = await gateway.source_mode(sid)
                    db.set_source(title, mode)
                    run_id = db.start_run()
                    try:
                        async for candidate in discover_sync_candidates(gateway, sid):
                            totals["seen"] += 1
                            db.record_seen(run_id)
                            if db.insert_candidate(candidate, run_id):
                                totals["inserted"] += 1
                        db.finish_run(run_id, "COMPLETED")
                    except Exception as exc:
                        db.finish_run(run_id, "FAILED", str(exc))
                        raise
                finally:
                    db.close()
        finally:
            await gateway.close()
        return totals


    def _dbs(self):
        return [HistoricalDatabase(database_path(self.root, sid), sid) for sid in self.source_ids]

    def _ensure_core_item(self, row) -> object:
        cid = content_id(row)
        original = self.storage.original(cid)
        try:
            return self.core.get(cid)
        except KeyError:
            self.core.reserve_item(
                cid,
                source_id=str(row["source_id"]),
                topic_id=int(row["topic_id"]),
                topic_name=str(row["topic_name"] or ""),
                original_url=str(row["original_url"]),
                original_path=original,
            )
            self.core.finalize_original_path(cid, original, sha256_file(original))
            vision = None
            # The historical Vision record is authoritative for this stage.
            hdb = HistoricalDatabase(database_path(self.root, int(row["source_id"])), int(row["source_id"]))
            try:
                vision = hdb.vision_result(int(row["id"]))
            finally:
                hdb.close()
            if vision is None or str(vision["status"]) != "VISION_ACCEPTED":
                raise RuntimeError(f"core-item-requires-vision-accepted:{cid}")
            links = tuple(__import__("json").loads(vision["affiliate_urls_json"] or "[]"))
            self.core.set_vision(
                cid,
                str(vision["affiliate_name"] or ""),
                str(vision["affiliate_url"] or ""),
                affiliate_urls=links,
                ia_context=__import__("json").loads(vision["ia_context_json"] or "{}"),
            )
            self.core.transition(cid, State.VISION, "historical-vision-already-accepted")
        item = self.core.get(cid)
        if item.state == State.VISION:
            self.core.transition(cid, State.IA, "historical-stock-ready")
            item = self.core.get(cid)
        return item

    def drain_vision(self, limit: int | None = None) -> dict[str, int]:
        total = {"VISION_ACCEPTED": 0, "WAITING_VISION": 0, "VISION_PROCESSING": 0, "processed": 0}
        for sid in self.source_ids:
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            try:
                result = HistoricalVisionRunner(db, ArmoredVision()).drain(limit=limit)
                for key in total:
                    total[key] += result.get(key, 0)
            finally:
                db.close()
        return total

    async def drain_stock(self, limit: int | None = None) -> dict[str, int]:
        total = {"STOCK_READY": 0, "STOCK_PROCESSING": 0, "processed": 0}
        for sid in self.source_ids:
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            try:
                result = await HistoricalStockRunner(db, self.root).drain(limit=limit)
                for key in total:
                    total[key] += result.get(key, 0)
            finally:
                db.close()
        return total

    def _next(self, statuses: tuple[str, ...]):
        for sid in self.source_ids:
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            row = db.next_stage_candidate(statuses)
            db.close()
            if row is not None:
                return sid, row
        return None

    def drain_ia(self, limit: int | None = None) -> dict[str, int]:
        counts = {"IA_READY": 0, "IA_PROCESSING": 0, "processed": 0}
        ia = ArmoredIA()
        while limit is None or counts["processed"] < limit:
            found = self._next(("STOCK_READY", "IA_PROCESSING"))
            if found is None:
                break
            sid, row = found
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            cid = content_id(row)
            try:
                db.set_stage_status(int(row["id"]), "IA_PROCESSING")
                item = self._ensure_core_item(row)
                if item.state == State.RECOVERY:
                    self.core.transition(cid, State.IA, "historical-ia-retry")
                    item = self.core.get(cid)
                if item.state != State.IA:
                    raise RuntimeError(f"ia-invalid-core-state:{item.state.value}")
                generated = ia.generate_caption_with_evidence(dict(item.ia_context or {}))
                self.core.record_caption_candidates(cid, generated.batch_id, generated.evaluations)
                self.core.set_caption(cid, generated.caption)
                self.core.transition(cid, State.STUDIO, "historical-ia-complete")
                db.set_stage_status(int(row["id"]), "IA_READY")
                counts["IA_READY"] += 1
            except Exception as exc:
                try:
                    if self.core.get(cid).state != State.RECOVERY:
                        self.core.transition(cid, State.RECOVERY, f"IA: {type(exc).__name__}: {exc}")
                except Exception:
                    pass
                db.set_stage_status(int(row["id"]), "IA_PROCESSING", str(exc))
                counts["IA_PROCESSING"] += 1
                counts["processed"] += 1
                break
            finally:
                db.close()
            counts["processed"] += 1
        return counts

    def drain_studio(self, limit: int | None = None) -> dict[str, int]:
        counts = {"STUDIO_READY": 0, "STUDIO_PROCESSING": 0, "processed": 0}
        studio = ArmoredStudio(self.root)
        while limit is None or counts["processed"] < limit:
            found = self._next(("IA_READY", "STUDIO_PROCESSING"))
            if found is None:
                break
            sid, row = found
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            cid = content_id(row)
            try:
                db.set_stage_status(int(row["id"]), "STUDIO_PROCESSING")
                item = self.core.get(cid)
                if item.state == State.RECOVERY:
                    self.core.transition(cid, State.STUDIO, "historical-studio-retry")
                    item = self.core.get(cid)
                if item.state != State.STUDIO:
                    raise RuntimeError(f"studio-invalid-core-state:{item.state.value}")
                result = studio.process(item)
                if result.working_path and not Path(result.working_path).is_file():
                    raise FileNotFoundError("studio-working-file-missing")
                if not Path(result.result_path).is_file():
                    raise FileNotFoundError("studio-result-file-missing")
                if result.working_path:
                    self.core.set_working(cid, result.working_path)
                self.core.set_result(cid, result.result_path)
                self.core.transition(cid, State.PUBLISHING, "historical-studio-complete")
                db.set_stage_status(int(row["id"]), "STUDIO_READY")
                counts["STUDIO_READY"] += 1
            except Exception as exc:
                try:
                    if self.core.get(cid).state != State.RECOVERY:
                        self.core.transition(cid, State.RECOVERY, f"STUDIO: {type(exc).__name__}: {exc}")
                except Exception:
                    pass
                db.set_stage_status(int(row["id"]), "STUDIO_PROCESSING", str(exc))
                counts["STUDIO_PROCESSING"] += 1
                counts["processed"] += 1
                break
            finally:
                db.close()
            counts["processed"] += 1
        return counts

    def _topic_for_source(self, sid: int) -> str:
        index = self.source_ids.index(int(sid)) + 1
        return (
            os.getenv(f"ARMORED_HUB_TOPIC_{index}")
            or os.getenv(f"HUB_TOPIC_{index}")
            or os.getenv("ARMORED_HUB_TOPIC_ID")
            or ""
        ).strip()

    def _cleanup(self, cid: str) -> None:
        item = self.core.get(cid)
        if item.state != State.PUBLISHED:
            raise RuntimeError("cleanup-is-allowed-only-after-PUBLISHED")
        workspace = item.workspace.resolve()
        original = item.original_path.resolve()
        if workspace != original.parent.resolve():
            raise RuntimeError("cleanup-workspace-mismatch")
        if workspace.is_dir():
            for path in workspace.iterdir():
                if path.resolve() == original:
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        self.core.mark_cleanup_completed(cid)

    def drain_hub(self, limit: int | None = None) -> dict[str, int]:
        counts = {"PUBLISHED": 0, "HUB_PROCESSING": 0, "RECOVERY": 0, "processed": 0}
        while limit is None or counts["processed"] < limit:
            found = self._next(("STUDIO_READY", "HUB_PROCESSING"))
            if found is None:
                break
            sid, row = found
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            cid = content_id(row)
            old_topic = os.environ.get("ARMORED_HUB_TOPIC_ID")
            try:
                db.set_stage_status(int(row["id"]), "HUB_PROCESSING")
                item = self.core.get(cid)
                if item.state == State.RECOVERY:
                    self.core.transition(cid, State.PUBLISHING, "historical-hub-retry")
                    item = self.core.get(cid)
                if item.state != State.PUBLISHING:
                    raise RuntimeError(f"hub-invalid-core-state:{item.state.value}")
                topic = self._topic_for_source(int(row["source_id"]))
                if not topic:
                    raise RuntimeError(f"missing-hub-topic-for-source:{row['source_id']}")
                os.environ["ARMORED_HUB_TOPIC_ID"] = topic
                hub = ArmoredHub(self.root, self.core)
                check = hub.check_publication(item)
                if check == PublicationCheck.UNKNOWN:
                    self.core.transition(cid, State.RECOVERY, "publication-check-uncertain-refusing-to-publish")
                    counts["RECOVERY"] += 1
                    db.set_stage_status(int(row["id"]), "HUB_PROCESSING", "publication-check-unknown")
                    counts["processed"] += 1
                    break
                if check == PublicationCheck.ABSENT:
                    result = hub.publish(item)
                    if not result.confirmed or not result.message_id:
                        raise RuntimeError("publication-not-confirmed")
                    self.core.publication_confirmed(cid, str(result.message_id))
                else:
                    pub = self.core.publication(cid)
                    if not pub or not pub["published_message_id"]:
                        raise RuntimeError("confirmed-publication-without-real-message-id")
                self.core.transition(cid, State.PUBLISHED, "publication-confirmed")
                self._cleanup(cid)
                db.set_stage_status(int(row["id"]), "PUBLISHED")
                counts["PUBLISHED"] += 1
            except Exception as exc:
                try:
                    if self.core.get(cid).state != State.RECOVERY:
                        self.core.transition(cid, State.RECOVERY, f"HUB: {type(exc).__name__}: {exc}")
                except Exception:
                    pass
                db.set_stage_status(int(row["id"]), "HUB_PROCESSING", str(exc))
                counts["HUB_PROCESSING"] += 1
                counts["processed"] += 1
                break
            finally:
                if old_topic is None:
                    os.environ.pop("ARMORED_HUB_TOPIC_ID", None)
                else:
                    os.environ["ARMORED_HUB_TOPIC_ID"] = old_topic
                db.close()
            counts["processed"] += 1
        return counts

    def status(self) -> dict[int, dict[str, int]]:
        result = {}
        for sid in self.source_ids:
            db = HistoricalDatabase(database_path(self.root, sid), sid)
            try:
                result[sid] = db.counts()
            finally:
                db.close()
        return result

    def catchup_complete(self) -> bool:
        active = {
            "DISCOVERED", "VISION_PROCESSING", "VISION_ACCEPTED",
            "STOCK_PROCESSING", "STOCK_READY", "IA_PROCESSING",
            "IA_READY", "STUDIO_PROCESSING", "STUDIO_READY", "HUB_PROCESSING",
        }
        for statuses in self.status().values():
            if any(statuses.get(key, 0) for key in active):
                return False
        return True


async def run_catchup(root: Path | None = None, *, limit: int | None = None) -> dict:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    config = load_config(root)
    runner = HistoricalToolDrain(root, config.sources)
    try:
        print("=" * 72)
        print("ARMORED CREATOR — CATCH-UP HISTÓRICO POR FERRAMENTA")
        print("=" * 72)
        print("SYNC -> VISION -> STOCK -> IA -> STUDIO -> HUB")
        print("SQLite é o estado; não existe fila física.")
        print()

        sync = await runner.ensure_sync_inventory()
        print("[SYNC]", sync)

        vision = runner.drain_vision(limit)
        print("[VISION]", vision)
        if any(
            values.get("VISION_PROCESSING", 0)
            for values in runner.status().values()
        ):
            print("[BARRIER] Vision ainda possui item retryable; próximas ferramentas não iniciam.")
            return {"sync": sync, "vision": vision, "status": runner.status(), "complete": False}

        stock = await runner.drain_stock(limit)
        print("[STOCK]", stock)
        if any(
            values.get("STOCK_PROCESSING", 0)
            for values in runner.status().values()
        ):
            print("[BARRIER] Stock ainda possui item retryable; próximas ferramentas não iniciam.")
            return {"sync": sync, "vision": vision, "stock": stock, "status": runner.status(), "complete": False}

        ia = runner.drain_ia(limit)
        print("[IA]", ia)
        if any(
            values.get("IA_PROCESSING", 0)
            for values in runner.status().values()
        ):
            print("[BARRIER] IA ainda possui item retryable; próximas ferramentas não iniciam.")
            return {"sync": sync, "vision": vision, "stock": stock, "ia": ia, "status": runner.status(), "complete": False}

        studio = runner.drain_studio(limit)
        print("[STUDIO]", studio)
        if any(
            values.get("STUDIO_PROCESSING", 0)
            for values in runner.status().values()
        ):
            print("[BARRIER] Studio ainda possui item retryable; Hub não inicia.")
            return {"sync": sync, "vision": vision, "stock": stock, "ia": ia, "studio": studio, "status": runner.status(), "complete": False}

        hub = runner.drain_hub(limit)
        print("[HUB]", hub)

        status = runner.status()
        print("[STATUS]", status)
        complete = runner.catchup_complete()
        print("[CATCH-UP]", "COMPLETE" if complete else "PENDING")
        return {"vision": vision, "stock": stock, "ia": ia, "studio": studio, "hub": hub, "status": status, "complete": complete}
    finally:
        runner.close()
