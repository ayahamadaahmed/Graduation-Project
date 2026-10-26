"""Which doctors are bookable: listed, exposing slots, and accepted by booking.

Always: active. Once DOCTOR_VERIFICATION_ENFORCED=true (off by default until
the doctor status review is approved): also verification_status = 'verified'.
Used by the catalog, global search and booking, so every path applies the
same rule. Lab slots without a doctor are not affected.
"""

from app.core.config import get_settings
from app.models import Doctor


def doctor_verification_enforced() -> bool:
    return get_settings().doctor_verification_enforced


def bookable_doctor_conditions() -> tuple:
    conditions = (Doctor.is_active == 1,)

    if doctor_verification_enforced():
        conditions += (Doctor.verification_status == "verified",)

    return conditions
