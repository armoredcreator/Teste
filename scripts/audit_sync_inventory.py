from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    -1003788989075,
    -1002698134896,
    -1002039708059,
)
STRICT = re.compile(r"^[A-Za-z0-9]+$")


def valid_shopee_short_url(value: str) -> bool:
    try:
        parsed = urlparse((value or "").strip())
    except ValueError:
        return False

    return (
        parsed.scheme == "https"
        and parsed.hostname == "s.shopee.com.br"
        and not parsed.query
        and not parsed.fragment
        and parsed.path.startswith("/")
        and len(parsed.path) > 1
        and STRICT.fullmatch(parsed.path[1:]) is not None
    )


def audit(source_id: int) -> tuple[int, int, list[tuple[int, str]]]:
    db_path = ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, original_url FROM candidates ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    invalid = [(int(row_id), str(url)) for row_id, url in rows if not valid_shopee_short_url(str(url))]
    return len(rows), len(invalid), invalid


def main() -> int:
    print("=" * 72)
    print("ARMORED CREATOR — AUDITORIA DO CONTRATO DE URL DO ARMOREDSYNC")
    print("=" * 72)

    total_all = 0
    invalid_all = 0

    for source_id in SOURCES:
        total, invalid_count, invalid = audit(source_id)
        total_all += total
        invalid_all += invalid_count
        status = "PASS" if invalid_count == 0 else "FAIL"
        print(f"[{status}] {source_id}: total={total} invalidos={invalid_count}")
        for row_id, url in invalid[:20]:
            print(f"    id={row_id} url={url}")
        if invalid_count > 20:
            print(f"    ... mais {invalid_count - 20} inválidos")

    print("-" * 72)
    print(f"TOTAL: {total_all} | INVALIDOS: {invalid_all}")
    print("=" * 72)

    return 0 if invalid_all == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
