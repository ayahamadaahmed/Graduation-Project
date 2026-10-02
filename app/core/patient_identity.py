import hashlib
import hmac
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


@dataclass(frozen=True, slots=True)
class ProtectedNationalId:
    hash_value: str
    encrypted_value: bytes
    last4: str


def normalize_national_id(value: str) -> str:
    normalized = (
        value.strip()
        .translate(_DIGIT_TRANSLATION)
    )

    if (
        len(normalized) != 14
        or not normalized.isascii()
        or not normalized.isdigit()
    ):
        raise ValueError(
            "National ID must contain exactly 14 digits."
        )

    return normalized


class PatientIdentityProtector:
    def __init__(
        self,
        *,
        hash_key: str,
        encryption_key: str,
    ) -> None:
        normalized_hash_key = hash_key.strip()

        if len(
            normalized_hash_key.encode("utf-8")
        ) < 32:
            raise RuntimeError(
                "NATIONAL_ID_HASH_KEY must contain "
                "at least 32 bytes."
            )

        try:
            self._fernet = Fernet(
                encryption_key.strip().encode("ascii")
            )

        except (
            ValueError,
            UnicodeEncodeError,
        ) as exc:
            raise RuntimeError(
                "NATIONAL_ID_ENCRYPTION_KEY is not "
                "a valid Fernet key."
            ) from exc

        self._hash_key = (
            normalized_hash_key.encode("utf-8")
        )

    def protect(
        self,
        national_id: str,
    ) -> ProtectedNationalId:
        normalized = normalize_national_id(
            national_id
        )

        return ProtectedNationalId(
            hash_value=self._hash_normalized(
                normalized
            ),
            encrypted_value=self._fernet.encrypt(
                normalized.encode("ascii")
            ),
            last4=normalized[-4:],
        )

    def hash_national_id(
        self,
        national_id: str,
    ) -> str:
        normalized = normalize_national_id(
            national_id
        )

        return self._hash_normalized(
            normalized
        )

    def decrypt_national_id(
        self,
        encrypted_value: bytes,
    ) -> str:
        try:
            decrypted = self._fernet.decrypt(
                encrypted_value
            )

            value = decrypted.decode("ascii")

        except (
            InvalidToken,
            UnicodeDecodeError,
        ) as exc:
            raise ValueError(
                "Unable to decrypt national ID."
            ) from exc

        return normalize_national_id(value)

    def _hash_normalized(
        self,
        normalized: str,
    ) -> str:
        return hmac.new(
            self._hash_key,
            normalized.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()