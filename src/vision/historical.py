from __future__ import annotations

from types import SimpleNamespace

from ..historical_database import HistoricalDatabase
from .service import ArmoredVision
from .contracts import VisionUnresolvedError


class HistoricalVisionRunner:
    """Drain the historical Vision stage without downloading media."""

    def __init__(self, db: HistoricalDatabase, vision: ArmoredVision | None = None):
        self.db = db
        self.vision = vision or ArmoredVision()

    def process_one(self, row) -> str:
        candidate_id = int(row["id"])
        self.db.set_vision_processing(candidate_id)
        item = SimpleNamespace(
            content_id=str(candidate_id),
            original_url=str(row["original_url"]),
        )

        try:
            result = self.vision.identify(item)
        except VisionUnresolvedError as exc:
            self.db.set_vision_waiting(candidate_id, str(exc))
            return "WAITING_VISION"
        except Exception as exc:
            # Network/API/resolver failures are retryable. They never become
            # terminal FAILED and never advance the historical stage.
            self.db.set_vision_retryable_error(candidate_id, str(exc))
            return "VISION_PROCESSING"

        self.db.set_vision_accepted(candidate_id, result)
        return "VISION_ACCEPTED"

    def drain(self, limit: int | None = None) -> dict[str, int]:
        counts = {
            "VISION_ACCEPTED": 0,
            "WAITING_VISION": 0,
            "VISION_PROCESSING": 0,
        }
        processed = 0

        while limit is None or processed < limit:
            row = self.db.next_vision_candidate()
            if row is None:
                break
            status = self.process_one(row)
            counts[status] += 1
            processed += 1
            if status == "VISION_PROCESSING":
                # A transient API/resolver failure is retryable, but do not
                # hot-loop the same candidate in one invocation.
                break

        counts["processed"] = processed
        return counts
