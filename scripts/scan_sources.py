from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.pattern_analyzer import PATTERNS, classify_messages
from src.reports import ReportWriter
from src.telegram_reader import TelegramReader


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)

    session_dir = root / "credentials" / "telegram"
    session_dir.mkdir(parents=True, exist_ok=True)

    reader = TelegramReader(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )
    report = ReportWriter(root, config.sources)

    print("=" * 64)
    print("TELEGRAM SOURCE ANALYZER — HISTÓRICO / SOMENTE LEITURA")
    print("=" * 64)

    try:
        await reader.connect()

        for source_id in config.sources:
            title = await reader.source_title(source_id)
            print()
            print(f"SOURCE: {source_id} — {title}")
            print("-" * 64)
            print("Lendo histórico...")

            messages = [message async for message in reader.iter_source(source_id)]
            matches = classify_messages(messages)

            for match in matches:
                report.write(match)

            counts = {pattern: 0 for pattern in PATTERNS}
            for match in matches:
                counts[match.pattern] += 1

            print(f"Mensagens analisadas: {len(messages)}")
            for pattern in PATTERNS:
                print(f"  {pattern:<36}: {counts[pattern]}")

        print()
        print("=" * 64)
        print("TOTAL")
        print("=" * 64)

        for pattern in PATTERNS:
            print(f"{pattern:<36}: {report.total[pattern]}")

        print()
        print(f"Evidence JSONL : {report.evidence_path}")
        print(f"Evidence CSV   : {report.csv_path}")
        print(f"Summary JSON   : {report.summary_path}")
        print()
        print("Nenhum vídeo foi baixado. Nenhuma mensagem foi modificada.")

    finally:
        report.close()
        await reader.close()


if __name__ == "__main__":
    asyncio.run(main())
