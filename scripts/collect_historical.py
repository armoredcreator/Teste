from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.historical_database import HistoricalDatabase
from src.sync import TelethonTelegramGateway, discover_sync_candidates


def database_path(root: Path, source_id: int) -> Path:
    return root / "batch" / "sources" / str(source_id) / "database" / "historical.db"


async def collect_source(reader: TelethonTelegramGateway, root: Path, source_id: int) -> tuple[int, int]:
    title = await reader.source_title(source_id)
    mode = await reader.source_mode(source_id)
    db = HistoricalDatabase(database_path(root, source_id), source_id)
    db.set_source(title, mode)

    if db.has_completed_run():
        print(
            f"  [{source_id}] histórico já concluído; "
            f"mantendo banco={db.total()} e pulando nova leitura.",
            flush=True,
        )
        db.close()
        return 0, 0

    existing_before = db.total()
    run_id = db.start_run()
    if existing_before:
        print(
            f"  [{source_id}] retomada idempotente: "
            f"banco_existente={existing_before}; "
            f"URLs existentes serão preservadas sem duplicação.",
            flush=True,
        )

    inserted = 0
    seen = 0
    try:
        async for candidate in discover_sync_candidates(reader, source_id):
            seen += 1
            db.record_seen(run_id)
            if db.insert_candidate(candidate, run_id):
                inserted += 1
            if seen % 250 == 0:
                db.commit()
                print(
                    f"  [{source_id}] candidatos vistos={seen} "
                    f"novos={inserted} banco={db.total()}",
                    flush=True,
                )

        db.finish_run(run_id, "COMPLETED")
        print(
            f"  [{source_id}] concluído: vistos={seen} "
            f"novos={inserted} total_banco={db.total()}",
            flush=True,
        )
        return seen, inserted
    except Exception as exc:
        db.finish_run(run_id, "FAILED", str(exc))
        raise
    finally:
        db.close()


async def main(source_number: int | None = None) -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    session_dir = root / "credentials" / "telegram"
    session_dir.mkdir(parents=True, exist_ok=True)

    if source_number is not None:
        if source_number < 1 or source_number > len(config.sources):
            raise ValueError(f"--source deve estar entre 1 e {len(config.sources)}")
        source_ids = (config.sources[source_number - 1],)
    else:
        source_ids = config.sources

    reader = TelethonTelegramGateway(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )

    print("=" * 72)
    print("ARMORED CREATOR — CATCH-UP HISTÓRICO / INVENTÁRIO SQLITE")
    print("=" * 72)
    print("Modo: somente leitura no Telegram; nenhum vídeo é baixado.")
    print("Destino: batch/sources/<source_id>/database/historical.db")
    print()

    try:
        await reader.connect()
        totals = 0
        inserted = 0

        for index, source_id in enumerate(source_ids, start=1):
            print(f"[{index}/{len(source_ids)}] SOURCE {source_id}")
            seen, added = await collect_source(reader, root, source_id)
            totals += seen
            inserted += added
            print()

        print("=" * 72)
        print(f"CATCH-UP COLETADO: vistos={totals} novos={inserted}")
        print("Nenhuma mídia foi baixada. Nenhuma mensagem foi modificada.")
        print("=" * 72)
    finally:
        await reader.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=int,
        choices=(1, 2, 3),
        help="reconstrói somente a fonte indicada; sem --source processa 1, 2 e 3",
    )
    args = parser.parse_args()
    asyncio.run(main(args.source))
