from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .pattern_analyzer import Match, PATTERNS


class ReportWriter:
    def __init__(self, root: Path):
        self.report_dir = root / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_path = self.report_dir / "pattern_evidence.jsonl"
        self.csv_path = self.report_dir / "pattern_evidence.csv"
        self.summary_path = self.report_dir / "pattern_summary.json"

        for path in (self.evidence_path, self.csv_path, self.summary_path):
            if path.exists():
                path.unlink()

        self._csv_file = self.csv_path.open("w", encoding="utf-8", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=[
                "source_id",
                "pattern",
                "message_ids",
                "grouped_ids",
                "urls",
                "composition",
            ],
        )
        self._csv_writer.writeheader()

        self.counts: dict[int, Counter[str]] = defaultdict(Counter)
        self.total = Counter()

    def write(self, match: Match) -> None:
        record = {
            "source_id": match.source_id,
            "pattern": match.pattern,
            "message_ids": list(match.message_ids),
            "grouped_ids": list(match.grouped_ids),
            "urls": list(match.urls),
            "composition": list(match.composition),
        }

        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._csv_writer.writerow(
            {
                "source_id": match.source_id,
                "pattern": match.pattern,
                "message_ids": ",".join(map(str, match.message_ids)),
                "grouped_ids": ",".join(map(str, match.grouped_ids)),
                "urls": " | ".join(match.urls),
                "composition": " | ".join(match.composition),
            }
        )
        self._csv_file.flush()

        self.counts[match.source_id][match.pattern] += 1
        self.total[match.pattern] += 1

    def close(self) -> None:
        self._csv_file.close()

        summary = {
            "sources": {
                str(source_id): {
                    pattern: self.counts[source_id][pattern]
                    for pattern in PATTERNS
                }
                for source_id in sorted(self.counts)
            },
            "total": {pattern: self.total[pattern] for pattern in PATTERNS},
        }

        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
