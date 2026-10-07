from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from telethon import functions
from telethon.errors import RPCError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.telegram_reader import TelegramReader


SOURCE_ID = -1002039708059
SAMPLE_LIMIT = 200


def entity_kind(entity) -> str:
    name = type(entity).__name__
    flags = []
    for attr in ("broadcast", "megagroup", "forum", "gigagroup"):
        if hasattr(entity, attr):
            flags.append(f"{attr}={getattr(entity, attr)!r}")
    return f"{name} ({', '.join(flags)})" if flags else name


def classify(message):
    return (
        bool(message.has_video),
        bool(message.has_image),
        bool(message.urls),
        message.grouped_id is not None,
    )


async def main() -> None:
    config = load_config(ROOT)
    if SOURCE_ID not in config.sources:
        raise SystemExit(
            f"Fonte {SOURCE_ID} não está configurada em credentials/project.env."
        )

    session_path = ROOT / "credentials" / "telegram" / "armoredsync"
    reader = TelegramReader(config.api_id, config.api_hash, session_path)

    print("=" * 72)
    print("SOURCE 3 — INVESTIGAÇÃO TELEGRAM / SOMENTE LEITURA")
    print("=" * 72)
    print(f"SOURCE: {SOURCE_ID}")
    print(f"AMOSTRA: até {SAMPLE_LIMIT} mensagens cronológicas")
    print("Mídia: NÃO será baixada")
    print("Banco de produção: NÃO será acessado")
    print()

    try:
        await reader.connect()

        entity = await reader.client.get_entity(SOURCE_ID)
        print("[1] ENTIDADE")
        print(f"    classe: {entity_kind(entity)}")
        print(f"    id: {getattr(entity, 'id', None)}")
        print(f"    title: {getattr(entity, 'title', None)!r}")
        print(f"    username: {getattr(entity, 'username', None)!r}")
        print()

        print("[2] TESTE DE FÓRUM")
        try:
            result = await reader.client(
                functions.messages.GetForumTopicsRequest(
                    peer=SOURCE_ID,
                    q=None,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=10,
                )
            )
            topics = getattr(result, "topics", []) or []
            print(f"    GetForumTopicsRequest: OK ({len(topics)} tópicos retornados)")
            for topic in topics[:10]:
                print(
                    f"      topic_id={getattr(topic, 'id', None)} "
                    f"title={getattr(topic, 'title', None)!r}"
                )
        except Exception as exc:
            print(f"    GetForumTopicsRequest: {type(exc).__name__}: {exc}")
        print()

        print("[3] HISTÓRICO DIRETO")
        stats = {
            "messages": 0,
            "video": 0,
            "image": 0,
            "url": 0,
            "video_url": 0,
            "video_no_url": 0,
            "grouped": 0,
            "grouped_video": 0,
            "grouped_url": 0,
        }
        last_id = None
        first_id = None

        async for message in reader.iter_source(SOURCE_ID):
            stats["messages"] += 1
            last_id = message.message_id
            if first_id is None:
                first_id = message.message_id
            if message.has_video:
                stats["video"] += 1
            if message.has_image:
                stats["image"] += 1
            if message.urls:
                stats["url"] += 1
            if message.has_video and message.urls:
                stats["video_url"] += 1
            if message.has_video and not message.urls:
                stats["video_no_url"] += 1
            if message.grouped_id is not None:
                stats["grouped"] += 1
                if message.has_video:
                    stats["grouped_video"] += 1
                if message.urls:
                    stats["grouped_url"] += 1

            if stats["messages"] >= SAMPLE_LIMIT:
                break

        print(f"    mensagens lidas: {stats['messages']}")
        print(f"    primeiro id da amostra: {first_id}")
        print(f"    último id da amostra: {last_id}")
        print(f"    vídeo: {stats['video']}")
        print(f"    imagem: {stats['image']}")
        print(f"    Shopee URL: {stats['url']}")
        print(f"    vídeo + URL: {stats['video_url']}")
        print(f"    vídeo sem URL: {stats['video_no_url']}")
        print(f"    grouped_id: {stats['grouped']}")
        print(f"    grouped + vídeo: {stats['grouped_video']}")
        print(f"    grouped + URL: {stats['grouped_url']}")
        print()

        print("[4] AMOSTRA DE MENSAGENS")
        sample_reader = reader.client.iter_messages(
            SOURCE_ID, limit=SAMPLE_LIMIT, reverse=True
        )
        count = 0
        async for raw in sample_reader:
            converted = reader._convert(SOURCE_ID, raw)
            preview = (converted.text or "").replace("\n", " ")[:100]
            print(
                f"    id={converted.message_id} "
                f"date={converted.date} "
                f"grouped={converted.grouped_id} "
                f"video={converted.has_video} "
                f"image={converted.has_image} "
                f"urls={len(converted.urls)} "
                f"text={preview!r}"
            )
            count += 1
            if count >= min(30, SAMPLE_LIMIT):
                break

        print()
        print("=" * 72)
        print("INVESTIGAÇÃO CONCLUÍDA")
        print("=" * 72)

    finally:
        await reader.close()


if __name__ == "__main__":
    asyncio.run(main())
