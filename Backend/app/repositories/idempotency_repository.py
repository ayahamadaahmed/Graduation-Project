import hashlib
import json

from datetime import (
    datetime,
    timezone,
)

from typing import Any

from uuid import uuid4

from sqlalchemy import (
    select,
    text,
)

from sqlalchemy.orm import (
    Session,
)

from app.models.idempotency import (
    IdempotencyRequest,
)


class IdempotencyRepository:

    # =====================================
    # Transaction-scoped SQL Server lock
    # =====================================

    def acquire_lock(
        self,
        db: Session,
        *,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        timeout_ms: int = 5000,
    ) -> None:

        raw_resource = (
            f"idempotency:"
            f"{tenant_id}:"
            f"{operation}:"
            f"{idempotency_key}"
        )

        # Keep the SQL Server application
        # lock resource compact and stable.
        resource = hashlib.sha256(
            raw_resource.encode(
                "utf-8"
            )
        ).hexdigest()

        statement = text(
            """
            DECLARE @result INT;

            EXEC @result = sys.sp_getapplock
                @Resource = :resource,
                @LockMode = 'Exclusive',
                @LockOwner = 'Transaction',
                @LockTimeout = :timeout_ms;

            SELECT @result;
            """
        )

        result = (
            db.execute(
                statement,
                {
                    "resource":
                        resource,

                    "timeout_ms":
                        timeout_ms,
                },
            )
            .scalar_one()
        )

        # SQL Server sp_getapplock:
        # >= 0 means success.
        # < 0 means timeout/failure.
        if result < 0:

            raise RuntimeError(
                "IDEMPOTENCY_LOCK_FAILED"
            )

    # =====================================
    # Read
    # =====================================

    def get(
        self,
        db: Session,
        *,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRequest | None:

        statement = (
            select(
                IdempotencyRequest
            )
            .where(
                IdempotencyRequest.tenant_id
                == tenant_id,

                IdempotencyRequest.operation
                == operation,

                IdempotencyRequest.idempotency_key
                == idempotency_key,
            )
        )

        return (
            db.execute(
                statement
            )
            .scalar_one_or_none()
        )

    # =====================================
    # Create pending operation
    # =====================================

    def create_pending(
        self,
        db: Session,
        *,
        tenant_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> IdempotencyRequest:

        record = IdempotencyRequest(
            id=str(uuid4()),
            tenant_id=tenant_id,
            operation=operation,
            idempotency_key=(
                idempotency_key
            ),
            request_hash=(
                request_hash
            ),
            status="pending",
        )

        db.add(
            record
        )

        # IMPORTANT:
        #
        # flush only.
        # Appointment + idempotency
        # are committed together later.
        db.flush()

        return record

    # =====================================
    # Reset previously failed operation
    # =====================================

    def reset_failed(
        self,
        record: IdempotencyRequest,
    ) -> None:

        record.status = "pending"

        record.response_body = None
        record.error_code = None
        record.completed_at = None

    # =====================================
    # Complete operation
    # =====================================

    def mark_completed(
        self,
        record: IdempotencyRequest,
        *,
        response: dict[str, Any],
    ) -> None:

        record.status = "completed"

        record.response_body = (
            json.dumps(
                response,
                ensure_ascii=False,
                default=str,
            )
        )

        record.error_code = None

        record.completed_at = (
            datetime.now(
                timezone.utc
            )
        )

    # =====================================
    # Read cached response
    # =====================================

    @staticmethod
    def load_response(
        record: IdempotencyRequest,
    ) -> dict[str, Any] | None:

        if not record.response_body:
            return None

        try:

            result = json.loads(
                record.response_body
            )

        except json.JSONDecodeError:

            return None

        if not isinstance(
            result,
            dict,
        ):

            return None

        return result


idempotency_repository = (
    IdempotencyRepository()
)