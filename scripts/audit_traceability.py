from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.telegram_reader import TelegramReader, TelegramMessage


@dataclass(frozen=True)
class AuditCase:
    source_id: int
    candidate_id: int
    kind: str
    composition: tuple[str, ...]
    selected_message_id: int
    message_ids: tuple[int, ...]
    grouped_ids: tuple[int, ...]
    urls: tuple[str, ...]


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def select_cases(source_id: int) -> list[AuditCase]:
    path = database_path(source_id)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    rows = []
    # Prefer one representative of each discovery form actually present.
    for kind in ("direct", "followup", "group"):
        row = conn.execute(
            """
            SELECT id, kind, composition_json, selected_message_id,
                   message_ids_json, grouped_ids_json, urls_json
            FROM candidates
            WHERE kind=?
            ORDER BY id
            LIMIT 1
            """,
            (kind,),
        ).fetchone()
        if row:
            rows.append(row)

    # If no group was found, deliberately include a multi-message candidate
    # when available so the audit still exercises message_ids_json.
    if not any(row["kind"] == "group" for row in rows):
        row = conn.execute(
            """
            SELECT id, kind, composition_json, selected_message_id,
                   message_ids_json, grouped_ids_json, urls_json
            FROM candidates
            WHERE json_array_length(message_ids_json) > 1
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if row and not any(row["id"] == row["id"] for row in rows):
            rows.append(row)

    conn.close()

    return [
        AuditCase(
            source_id=source_id,
            candidate_id=int(row["id"]),
            kind=str(row["kind"]),
            composition=tuple(json.loads(row["composition_json"])),
            selected_message_id=int(row["selected_message_id"]),
            message_ids=tuple(json.loads(row["message_ids_json"])),
            grouped_ids=tuple(json.loads(row["grouped_ids_json"])),
            urls=tuple(json.loads(row["urls_json"])),
        )
        for row in rows
    ]


def normalized_urls(messages: list[TelegramMessage]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for message in messages:
        for url in message.urls:
            seen.setdefault(url.casefold(), url)
    return tuple(seen.values())


def validate_case(case: AuditCase, messages: list[TelegramMessage]) -> list[str]:
    errors: list[str] = []
    by_id = {message.message_id: message for message in messages}

    missing = [message_id for message_id in case.message_ids if message_id not in by_id]
    if missing:
        errors.append(f"message_ids ausentes no Telegram: {missing}")
        return errors

    selected = by_id.get(case.selected_message_id)
    if selected is None:
        errors.append("selected_message_id não foi encontrado")
    elif not selected.has_video:
        errors.append(
            f"selected_message_id={case.selected_message_id} não é vídeo"
        )

    actual_ids = tuple(message.message_id for message in messages)
    expected_ids = case.message_ids
    if set(actual_ids) != set(expected_ids):
        errors.append(
            f"message_ids divergentes: DB={list(expected_ids)} Telegram={list(actual_ids)}"
        )

    actual_grouped = tuple(
        sorted(
            {
                int(message.grouped_id)
                for message in messages
                if message.grouped_id is not None
            }
        )
    )
    if actual_grouped != tuple(sorted(case.grouped_ids)):
        errors.append(
            f"grouped_ids divergentes: DB={list(case.grouped_ids)} "
            f"Telegram={list(actual_grouped)}"
        )

    actual_urls = normalized_urls(messages)
    expected_urls = tuple(case.urls)
    if {url.casefold() for url in actual_urls} != {url.casefold() for url in expected_urls}:
        errors.append(
            f"URLs divergentes: DB={list(expected_urls)} Telegram={list(actual_urls)}"
        )

    actual_composition = tuple(
        ("video" if message.has_video else "image" if message.has_image else "other")
        for message in messages
    )
    # The stored composition ends with the logical link marker.
    expected_media_composition = case.composition[:-1]
    if sorted(actual_composition) != sorted(expected_media_composition):
        errors.append(
            f"composição divergente: DB={list(expected_media_composition)} "
            f"Telegram={list(actual_composition)}"
        )

    if case.kind == "direct" and len(case.message_ids) != 1:
        errors.append("candidato direct deveria ter exatamente 1 message_id")

    if case.kind == "followup":
        if len(case.message_ids) != 2:
            errors.append("candidato followup deveria ter 2 message_ids")
        elif not by_id[case.message_ids[0]].has_video:
            errors.append("followup: primeira mensagem não é vídeo")
        elif not by_id[case.message_ids[1]].urls:
            errors.append("followup: segunda mensagem não contém URL Shopee")

    if case.kind == "group":
        grouped_values = {
            message.grouped_id for message in messages if message.grouped_id is not None
        }
        if not grouped_values:
            errors.append("group sem grouped_id no Telegram")

    return errors


async def audit_source(
    reader: TelegramReader,
    source_id: int,
) -> tuple[int, int]:
    cases = select_cases(source_id)
    passed = 0
    failed = 0

    print(f"\nSOURCE {source_id}")
    if not cases:
        print("  AVISO: nenhum caso disponível para auditoria.")
        return 0, 0

    for case in cases:
        messages_raw = await reader.client.get_messages(
            source_id,
            ids=list(case.message_ids),
        )
        messages = [
            reader._convert(source_id, message)
            for message in (messages_raw if isinstance(messages_raw, list) else [messages_raw])
            if message is not None
        ]

        errors = validate_case(case, messages)
        label = f"candidate={case.candidate_id} kind={case.kind}"
        if errors:
            failed += 1
            print(f"  FAIL  {label}")
            for error in errors:
                print(f"        - {error}")
        else:
            passed += 1
            print(
                f"  PASS  {label} "
                f"selected={case.selected_message_id} "
                f"messages={list(case.message_ids)} "
                f"urls={len(case.urls)}"
            )

    return passed, failed


async def main() -> None:
    config = load_config(ROOT)
    session_dir = ROOT / "credentials" / "telegram"
    reader = TelegramReader(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )

    print("=" * 72)
    print("ARMORED CREATOR — AUDITORIA DE RASTREABILIDADE HISTÓRICA")
    print("=" * 72)
    print("Somente leitura. Nenhuma mídia é baixada.")
    print("Nenhum historical.db é alterado.")
    print("Nenhuma mensagem Telegram é modificada.")

    total_passed = 0
    total_failed = 0

    try:
        await reader.connect()
        for source_id in config.sources:
            passed, failed = await audit_source(reader, int(source_id))
            total_passed += passed
            total_failed += failed
    finally:
        await reader.close()

    print("\n" + "=" * 72)
    print(f"RESULTADO: PASS={total_passed} FAIL={total_failed}")
    if total_failed:
        print("RASTREABILIDADE: FALHOU — corrigir antes de materializar mídia.")
        raise SystemExit(1)

    print("RASTREABILIDADE: APROVADA")
    print("Os casos auditados podem ser reencontrados no Telegram pelos IDs persistidos.")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
