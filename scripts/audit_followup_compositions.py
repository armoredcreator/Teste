from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.telegram_reader import TelegramReader


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def load_followups(source_id: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(database_path(source_id))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, message_ids_json, composition_json, evidence_json, original_url
        FROM candidates
        WHERE source_id=? AND kind='followup'
        ORDER BY id
        """,
        (source_id,),
    ).fetchall()
    conn.close()
    return rows


def telegram_composition(messages) -> tuple[str, ...]:
    result: list[str] = []
    for message in messages:
        if message.has_video:
            result.append("video")
        elif message.has_image:
            result.append("image")
    return tuple(result) + ("link",)


async def audit_source(reader: TelegramReader, source_id: int) -> tuple[int, int]:
    rows = load_followups(source_id)
    passed = failed = 0
    print(f"\nSOURCE {source_id}: followups={len(rows)}")

    for row in rows:
        message_ids = tuple(json.loads(row["message_ids_json"]))
        stored = tuple(json.loads(row["composition_json"]))
        raw = await reader.client.get_messages(source_id, ids=list(message_ids))
        raw_messages = raw if isinstance(raw, list) else [raw]
        messages = [
            reader._convert(source_id, message)
            for message in raw_messages
            if message is not None
        ]

        errors: list[str] = []
        actual_ids = tuple(message.message_id for message in messages)
        if set(actual_ids) != set(message_ids):
            errors.append(f"message_ids DB={list(message_ids)} Telegram={list(actual_ids)}")

        if len(messages) != 2:
            errors.append(f"esperado 2 mensagens, encontrado={len(messages)}")
        else:
            if not messages[0].has_video:
                errors.append("primeira mensagem não é vídeo")
            if not messages[1].urls:
                errors.append("segunda mensagem não contém URL Shopee")

        actual_composition = telegram_composition(messages)
        if stored != actual_composition:
            errors.append(
                f"composição DB={list(stored)} Telegram={list(actual_composition)}"
            )

        if errors:
            failed += 1
            print(f"  FAIL candidate={row['id']} url={row['original_url']}")
            for error in errors:
                print(f"       - {error}")
        else:
            passed += 1

    return passed, failed


async def main() -> None:
    config = load_config(ROOT)
    session_dir = ROOT / "credentials" / "telegram"
    reader = TelegramReader(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )

    total_passed = total_failed = 0
    try:
        await reader.connect()
        for source_id in config.sources:
            passed, failed = await audit_source(reader, int(source_id))
            total_passed += passed
            total_failed += failed
    finally:
        await reader.close()

    print("\n" + "=" * 72)
    print(f"FOLLOWUP COMPOSITION: PASS={total_passed} FAIL={total_failed}")
    if total_failed:
        print("Auditoria falhou: não reparar o banco ainda.")
        raise SystemExit(1)
    print("Auditoria aprovada: composição persistida corresponde ao Telegram.")


if __name__ == "__main__":
    asyncio.run(main())
