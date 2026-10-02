import hashlib
import json
from typing import Any


def build_request_hash(
    payload: dict[str, Any],
) -> str:
    """
    Create a deterministic SHA-256 hash.

    Sensitive raw payload values are not
    stored in the idempotency table.
    Only the resulting hash is stored.
    """

    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
        default=str,
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()