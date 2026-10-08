from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.telegram_reader import TelegramReader


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def load_followups(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT id, message_ids_json, composition_json
        FROM candidates
        WHERE source_id=? AND kind='followup'
        ORDER BY id
        """,
        (source_id,),
    ).fetchall()


def telegram_composition(messages) -> tuple[str, ...]:
    result: list[str] = []
    for message in messages:
        if message.has_video:
            result.append("video")
        elif message.has_image:
            result.append("image")
    return tuple(result) + ("link",)


async def collect_repairs(reader: TelegramReader, source_id: int, conn: sqlite3.Connection):
    repairs: list[tuple[int, tuple[str, ...], tuple[str, ...]]] = []

    for row in load_followups(conn, source_id):
        message_ids = tuple(json.loads(row["message_ids_json"]))
        raw = await reader.client.get_messages(source_id, ids=list(message_ids))
        raw_messages = raw if isinstance(raw, list) else [raw]
        messages = [
            reader._convert(source_id, message)
            for message in raw_messages
            if message is not None
        ]

        actual_ids = tuple(message.message_id for message in messages)
        if set(actual_ids) != set(message_ids) or len(messages) != 2:
            raise RuntimeError(
                f"candidate={row['id']} não pôde ser validado pelos message_ids"
            )
        if not messages[0].has_video or not messages[1].urls:
            raise RuntimeError(
                f"candidate={row['id']} não satisfaz followup video -> link"
            )

        stored = tuple(json.loads(row["composition_json"]))
        actual = telegram_composition(messages)
        if stored != actual:
            repairs.append((int(row["id"]), stored, actual))

    return repairs


async def main() -> None:
    config = load_config(ROOT)
    session_dir = ROOT / "credentials" / "telegram"
    reader = TelegramReader(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )

    total_repairs = 0
    try:
        await reader.connect()

        for source_id in config.sources:
            path = database_path(int(source_id))
            conn = sqlite3.connect(path)
            try:
                repairs = await collect_repairs(reader, int(source_id), conn)
                print(f"SOURCE {source_id}: divergências={len(repairs)}")

                if not repairs:
                    conn.close()
                    continue

                backup = path.with_suffix(".before-followup-composition-repair.db")
                if not backup.exists():
                    with sqlite3.connect(backup) as backup_conn:
                        conn.backup(backup_conn)
                    print(f"  backup={backup.name}")

                conn.execute("BEGIN")
                for candidate_id, stored, actual in repairs:
                    conn.execute(
                        """
                        UPDATE candidates
                        SET composition_json=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND kind='followup'
                        """,
                        (json.dumps(list(actual), ensure_ascii=False), candidate_id),
                    )
                    print(
                        f"  repaired candidate={candidate_id}: "
                        f"{list(stored)} -> {list(actual)}"
                    )
                conn.commit()
                total_repairs += len(repairs)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    finally:
        await reader.close()

    print("\n" + "=" * 72)
    print(f"REPAROS APLICADOS: {total_repairs}")
    print("Somente composition_json foi alterado; message_ids/URLs/evidence permanecem intactos.")
    print("Próximo passo obrigatório: executar audit_followup_compositions.py e audit_traceability.py.")


if __name__ == "__main__":
    asyncio.run(main())
