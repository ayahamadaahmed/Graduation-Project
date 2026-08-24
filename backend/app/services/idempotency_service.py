from dataclasses import (
    dataclass,
)

from typing import Any

from sqlalchemy.orm import (
    Session,
)

from app.core.idempotency import (
    build_request_hash,
)

from app.core.idempotency_exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)

from app.models.idempotency import (
    IdempotencyRequest,
)

from app.repositories.idempotency_repository import (
    idempotency_repository,
)


@dataclass
class IdempotencyResult:

    record: (
        IdempotencyRequest | None
    )

    cached_response: (
        dict[str, Any] | None
    )

    is_replay: bool


class IdempotencyService:

    def begin(
        self,
        db: Session,
        *,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> IdempotencyResult:

        key = (
            idempotency_key
            .strip()
        )

        if not key:

            raise ValueError(
                "Idempotency key "
                "cannot be empty."
            )

        if len(key) > 128:

            raise ValueError(
                "Idempotency key "
                "is too long."
            )

        # =================================
        # Serialize requests using the
        # same tenant + operation + key.
        # =================================

        idempotency_repository.acquire_lock(
            db,
            tenant_id=tenant_id,
            operation=operation,
            idempotency_key=key,
        )

        request_hash = (
            build_request_hash(
                payload
            )
        )

        existing = (
            idempotency_repository
            .get(
                db,
                tenant_id=tenant_id,
                operation=operation,
                idempotency_key=key,
            )
        )

        # =================================
        # Existing request
        # =================================

        if existing:

            # Same key but different request
            if (
                existing.request_hash
                != request_hash
            ):

                raise (
                    IdempotencyConflictError(
                        (
                            "The same "
                            "idempotency key "
                            "was reused with "
                            "different data."
                        )
                    )
                )

            # ---------------------------------
            # Already completed
            # ---------------------------------

            if (
                existing.status
                == "completed"
            ):

                cached = (
                    idempotency_repository
                    .load_response(
                        existing
                    )
                )

                if cached is None:

                    raise RuntimeError(
                        "IDEMPOTENCY_RESPONSE_INVALID"
                    )

                return (
                    IdempotencyResult(
                        record=existing,
                        cached_response=(
                            cached
                        ),
                        is_replay=True,
                    )
                )

            # ---------------------------------
            # Previous operation failed
            # ---------------------------------

            if (
                existing.status
                == "failed"
            ):

                idempotency_repository.reset_failed(
                    existing
                )

                return (
                    IdempotencyResult(
                        record=existing,
                        cached_response=None,
                        is_replay=False,
                    )
                )

            # ---------------------------------
            # Pending
            # ---------------------------------

            if (
                existing.status
                == "pending"
            ):

                raise (
                    IdempotencyInProgressError(
                        (
                            "This operation "
                            "is already "
                            "being processed."
                        )
                    )
                )

        # =================================
        # First request
        # =================================

        record = (
            idempotency_repository
            .create_pending(
                db,
                tenant_id=tenant_id,
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
            )
        )

        return (
            IdempotencyResult(
                record=record,
                cached_response=None,
                is_replay=False,
            )
        )


idempotency_service = (
    IdempotencyService()
)