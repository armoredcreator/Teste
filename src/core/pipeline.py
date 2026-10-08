from __future__ import annotations

import logging
import os
import shutil

from .database import Database
from .models import PublicationCheck, State
from .services import (
    AIService,
    PublicationUnknownError,
    Publisher,
    StudioService,
    VisionService,
    VisionUnresolvedError,
)
from .storage import Storage


class Pipeline:
    """Native ArmoredCreator processing state machine.

    Historical execution may resolve Vision before media materialization; when
    an immutable ORIGINAL already exists, this pipeline resumes from the
    persisted state without redoing completed stages.
    """

    def __init__(
        self,
        db: Database,
        storage: Storage,
        vision: VisionService,
        studio: StudioService,
        publisher: Publisher,
        ia: AIService | None = None,
    ) -> None:
        self.db = db
        self.storage = storage
        self.vision = vision
        self.studio = studio
        self.publisher = publisher
        self.ia = ia
        self.log = logging.getLogger(__name__)
        self._shutdown_checker = lambda: False

    def set_shutdown_checker(self, checker) -> None:
        self._shutdown_checker = checker

    def run(self, item_id: str) -> None:
        item = self.db.get(item_id)

        if item.state == State.PUBLISHED:
            if not item.cleanup_completed:
                self.cleanup(item_id)
            return

        try:
            self.db.record_attempt(item_id)

            if not item.original_path.is_file():
                raise FileNotFoundError(
                    f"immutable-original-missing: {item.original_path}"
                )

            if item.state == State.RECEIVED:
                self.db.transition(item_id, State.VISION, "pipeline-start")

            elif item.state == State.RECOVERY:
                result = item.result_path
                if not result and item.affiliate_url:
                    result = self.storage.result(
                        item_id, item.affiliate_url, item.affiliate_name
                    )

                if result and result.is_file():
                    if item.result_path is None:
                        self.db.set_result(item_id, result)
                    self.db.transition(
                        item_id, State.PUBLISHING, "recovery-resume-publication"
                    )
                elif item.working_path and item.working_path.is_file() and item.affiliate_name:
                    self.db.transition(
                        item_id, State.STUDIO, "recovery-resume-studio"
                    )
                elif item.affiliate_name:
                    self.db.transition(
                        item_id, State.STUDIO, "recovery-rebuild-working"
                    )
                else:
                    self.db.transition(
                        item_id, State.VISION, "recovery-rebuild-vision"
                    )

            item = self.db.get(item_id)

            if item.state == State.WAITING_VISION:
                return

            if item.state == State.FAILED:
                raise RuntimeError(
                    "FAILED item requires deterministic recovery before pipeline.run"
                )

            if item.state == State.VISION:
                try:
                    result = self.vision.identify(item)
                except VisionUnresolvedError as exc:
                    self.db.mark_vision_waiting(item_id, str(exc))
                    return

                self.db.set_vision(
                    item_id,
                    result.affiliate_name,
                    result.affiliate_url,
                    affiliate_urls=getattr(result, "affiliate_urls", ()),
                    publication_caption=getattr(
                        result, "publication_caption", None
                    ),
                    ia_context=getattr(result, "ia_context", None),
                )

                if (
                    self.ia is not None
                    and os.getenv("ARMORED_IA_ENABLED", "1") == "1"
                    and os.getenv("ARMORED_IA_CAPTION_ENABLED", "1") == "1"
                ):
                    self.db.transition(item_id, State.IA, "vision-complete")
                else:
                    self.db.transition(item_id, State.STUDIO, "vision-complete")

            item = self.db.get(item_id)

            if item.state == State.IA:
                if self.ia is None:
                    raise RuntimeError("armored-ia-service-not-configured")
                if not item.ia_context:
                    raise RuntimeError("armored-ia-context-missing")

                generate_with_evidence = getattr(
                    self.ia, "generate_caption_with_evidence", None
                )
                if callable(generate_with_evidence):
                    generated = generate_with_evidence(dict(item.ia_context))
                    self.db.record_caption_candidates(
                        item_id,
                        generated.batch_id,
                        generated.evaluations,
                    )
                    caption = generated.caption
                else:
                    caption = self.ia.generate_caption(dict(item.ia_context))

                if not str(caption or "").strip():
                    raise RuntimeError("armored-ia-empty-caption")

                self.db.set_caption(item_id, str(caption))
                self.db.transition(item_id, State.STUDIO, "ia-complete")

            item = self.db.get(item_id)

            if item.state == State.STUDIO:
                if not item.affiliate_name:
                    raise RuntimeError("studio-requires-affiliate-metadata")

                studio = self.studio.process(item)

                if studio.working_path is not None:
                    if not studio.working_path.is_file():
                        raise FileNotFoundError("studio-working-file-missing")
                    self.db.set_working(item_id, studio.working_path)

                if not studio.result_path.is_file():
                    raise FileNotFoundError("studio-result-file-missing")

                self.db.set_result(item_id, studio.result_path)
                self.db.transition(item_id, State.PUBLISHING, "studio-complete")

            item = self.db.get(item_id)

            if item.state == State.PUBLISHING:
                if not item.result_path or not item.result_path.is_file():
                    raise FileNotFoundError("publication-result-missing")

                publish_once = getattr(self.publisher, "publish_once", None)

                if callable(publish_once):
                    try:
                        result = publish_once(item)
                    except PublicationUnknownError as exc:
                        self.db.transition(item_id, State.RECOVERY, str(exc))
                        return

                    if not result.confirmed or not result.message_id:
                        raise RuntimeError("publication-not-confirmed")

                    self.db.publication_confirmed(
                        item_id, str(result.message_id)
                    )

                else:
                    self.db.publication_started(item_id)

                    check = self.publisher.check_publication(item)

                    if check == PublicationCheck.UNKNOWN:
                        self.db.transition(
                            item_id,
                            State.RECOVERY,
                            "publication-check-uncertain-refusing-to-publish",
                        )
                        return

                    if check == PublicationCheck.ABSENT:
                        try:
                            result = self.publisher.publish(item)
                        except PublicationUnknownError as exc:
                            self.db.transition(item_id, State.RECOVERY, str(exc))
                            return

                        if not result.confirmed or not result.message_id:
                            raise RuntimeError("publication-not-confirmed")

                        self.db.publication_confirmed(
                            item_id, str(result.message_id)
                        )

                    elif check == PublicationCheck.CONFIRMED:
                        publication = self.db.publication(item_id)
                        message_id = (
                            publication["published_message_id"]
                            if publication
                            else None
                        )
                        if not message_id:
                            self.db.transition(
                                item_id,
                                State.RECOVERY,
                                "confirmed-publication-without-real-message-id",
                            )
                            return

                        self.db.publication_confirmed(item_id, str(message_id))

                self.db.transition(
                    item_id, State.PUBLISHED, "publication-confirmed"
                )
                self.cleanup(item_id)

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            current = self.db.get(item_id)

            if current.state == State.PUBLISHED:
                raise

            if self._shutdown_checker():
                raise KeyboardInterrupt from exc

            self.db.transition(
                item_id,
                State.RECOVERY,
                f"{type(exc).__name__}: {exc}",
            )
            raise

    def cleanup(self, item_id: str) -> None:
        item = self.db.get(item_id)

        if item.state != State.PUBLISHED:
            raise RuntimeError("cleanup-is-allowed-only-after-PUBLISHED")

        workspace = item.workspace.resolve()
        original = item.original_path.resolve()

        if workspace != original.parent.resolve():
            raise RuntimeError("cleanup-workspace-mismatch")

        if not workspace.is_dir():
            self.db.mark_cleanup_completed(item_id)
            return

        for path in workspace.iterdir():
            if path.resolve() == original:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

        self.db.mark_cleanup_completed(item_id)
