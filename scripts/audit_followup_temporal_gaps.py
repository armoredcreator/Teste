from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def database_path(source_id: int) -> Path:
    return ROOT / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def audit_source(source_id: int) -> dict[str, int | float | None]:
    conn = sqlite3.connect(database_path(source_id))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, message_ids_json, evidence_json, original_url
        FROM candidates
        WHERE source_id=? AND kind='followup'
        ORDER BY id
        """,
        (source_id,),
    ).fetchall()
    conn.close()

    gaps: list[float] = []
    malformed = 0

    for row in rows:
        try:
            evidence = json.loads(row["evidence_json"])
            dates = [parse_date(item.get("date")) for item in evidence]
            if len(dates) != 2 or any(value is None for value in dates):
                malformed += 1
                continue
            gap_hours = abs((dates[0] - dates[1]).total_seconds()) / 3600.0
            gaps.append(gap_hours)
        except (TypeError, ValueError, json.JSONDecodeError):
            malformed += 1

    suspicious_1h = sum(gap > 1 for gap in gaps)
    suspicious_6h = sum(gap > 6 for gap in gaps)
    suspicious_24h = sum(gap > 24 for gap in gaps)

    return {
        "followups": len(rows),
        "with_valid_dates": len(gaps),
        "malformed": malformed,
        "gt_1h": suspicious_1h,
        "gt_6h": suspicious_6h,
        "gt_24h": suspicious_24h,
        "max_gap_hours": round(max(gaps), 2) if gaps else None,
    }


def main() -> None:
    total_followups = 0
    total_gt_1h = 0
    total_gt_6h = 0
    total_gt_24h = 0
    print("=" * 72)
    print("ARMORED CREATOR — AUDITORIA DE DISTÂNCIA TEMPORAL DOS FOLLOWUPS")
    print("=" * 72)
    print("Somente leitura do SQLite. Nenhum banco é alterado.")
    print()

    for source_id in ( -1003788989075, -1002698134896, -1002039708059 ):
        result = audit_source(source_id)
        print(f"SOURCE {source_id}")
        print(f"  followups={result['followups']}")
        print(f"  datas_validas={result['with_valid_dates']}")
        print(f"  datas_invalidas={result['malformed']}")
        print(f"  gap_>_1h={result['gt_1h']}")
        print(f"  gap_>_6h={result['gt_6h']}")
        print(f"  gap_>_24h={result['gt_24h']}")
        print(f"  maior_gap_horas={result['max_gap_hours']}")
        print()

        total_followups += int(result["followups"])
        total_gt_1h += int(result["gt_1h"])
        total_gt_6h += int(result["gt_6h"])
        total_gt_24h += int(result["gt_24h"])

    print("=" * 72)
    print(f"TOTAL FOLLOWUPS: {total_followups}")
    print(f"TOTAL GAP > 1h: {total_gt_1h}")
    print(f"TOTAL GAP > 6h: {total_gt_6h}")
    print(f"TOTAL GAP > 24h: {total_gt_24h}")
    print("=" * 72)


if __name__ == "__main__":
    main()
