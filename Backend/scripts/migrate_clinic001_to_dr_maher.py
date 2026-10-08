from __future__ import annotations

import argparse
from uuid import (
    NAMESPACE_URL,
    uuid5,
)

from sqlalchemy import text

from app.db.session import SessionLocal


# ============================================================
# TARGET TENANT
# ============================================================

TENANT_KEY = "clinic-001"


# ============================================================
# VERIFIED PROVIDER DATA
# ============================================================

PROVIDER_NAME = (
    "Dr. Maher Mahmoud Dermatology Clinic"
)

PROVIDER_SLUG = (
    "dr-maher-mahmoud-dermatology-clinic"
)

PROVIDER_PHONE = (
    "+201000000000"
)

PROVIDER_EMAIL = (
    "drmaher@medmind.local"
)

PROVIDER_ADDRESS = (
    "Cairo, Egypt"
)


# ============================================================
# EXISTING CATALOG RECORDS TO KEEP
# ============================================================

DERMATOLOGY_CODE = (
    "DERMATOLOGY"
)

DERMATOLOGY_SERVICE_CODE = (
    "SKIN_CONSULT"
)


# ============================================================
# NEW DETERMINISTIC IDS
#
# uuid5 makes the migration safe to run again.
# ============================================================

DR_MAHER_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:doctor:dr-maher-mahmoud",
)

CAIRO_MEDICAL_CENTER_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:branch:cairo-medical-center",
)

SERIDAR_DOKKI_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:branch:tower-of-seridar-dokki",
)

DR_MAHER_CMC_LINK_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:doctor-branch:"
    "dr-maher:cairo-medical-center",
)

DR_MAHER_SERIDAR_LINK_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:doctor-branch:"
    "dr-maher:tower-of-seridar",
)

DR_MAHER_SERVICE_LINK_ID = uuid5(
    NAMESPACE_URL,
    "medmind:clinic-001:doctor-service:"
    "dr-maher:skin-consult",
)


# ============================================================
# HELPERS
# ============================================================

def scalar(
    session,
    sql: str,
    params: dict,
) -> int:

    return int(
        session.execute(
            text(sql),
            params,
        ).scalar_one()
    )


def exists(
    session,
    sql: str,
    params: dict,
) -> bool:

    return (
        scalar(
            session,
            sql,
            params,
        )
        > 0
    )


def get_provider(
    session,
):

    provider = (
        session.execute(
            text(
                """
                SELECT
                    id,
                    tenant_key,
                    name,
                    slug
                FROM dbo.providers
                WHERE tenant_key = :tenant_key;
                """
            ),
            {
                "tenant_key":
                    TENANT_KEY,
            },
        )
        .mappings()
        .one_or_none()
    )

    if provider is None:

        raise RuntimeError(
            f"Provider not found: {TENANT_KEY}"
        )

    return provider


def get_dermatology_specialty(
    session,
    provider_id: str,
):

    row = (
        session.execute(
            text(
                """
                SELECT
                    id,
                    code,
                    name_en
                FROM dbo.specialties
                WHERE
                    provider_id = :provider_id
                    AND code = :code;
                """
            ),
            {
                "provider_id":
                    provider_id,

                "code":
                    DERMATOLOGY_CODE,
            },
        )
        .mappings()
        .one_or_none()
    )

    if row is None:

        raise RuntimeError(
            "DERMATOLOGY specialty not found."
        )

    return row


def get_dermatology_service(
    session,
    provider_id: str,
):

    row = (
        session.execute(
            text(
                """
                SELECT
                    id,
                    code,
                    name_en
                FROM dbo.services
                WHERE
                    provider_id = :provider_id
                    AND code = :code;
                """
            ),
            {
                "provider_id":
                    provider_id,

                "code":
                    DERMATOLOGY_SERVICE_CODE,
            },
        )
        .mappings()
        .one_or_none()
    )

    if row is None:

        raise RuntimeError(
            "SKIN_CONSULT service not found."
        )

    return row


# ============================================================
# DRY RUN
# ============================================================

def preview(
    session,
    *,
    provider_id: str,
) -> None:

    params = {
        "provider_id":
            provider_id,

        "new_doctor_id":
            str(DR_MAHER_ID),
    }

    print()
    print(
        "=== DR MAHER MIGRATION DRY RUN ==="
    )

    print()
    print(
        "Tenant:",
        TENANT_KEY,
    )

    print(
        "Target provider:",
        PROVIDER_NAME,
    )

    print()
    print(
        "=== RECORDS TO DEACTIVATE ==="
    )

    print(
        "old doctors:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.doctors
            WHERE
                provider_id = :provider_id
                AND is_active = 1
                AND id <> :new_doctor_id
            """,
            params,
        ),
    )

    print(
        "non-dermatology specialties:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.specialties
            WHERE
                provider_id = :provider_id
                AND is_active = 1
                AND code <> 'DERMATOLOGY'
            """,
            params,
        ),
    )

    print(
        "other services:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.services
            WHERE
                provider_id = :provider_id
                AND is_active = 1
                AND code <> 'SKIN_CONSULT'
            """,
            params,
        ),
    )

    print(
        "old branches:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.branches
            WHERE
                provider_id = :provider_id
                AND is_active = 1
                AND id NOT IN (
                    :cmc_id,
                    :seridar_id
                )
            """,
            {
                **params,

                "cmc_id":
                    str(
                        CAIRO_MEDICAL_CENTER_ID
                    ),

                "seridar_id":
                    str(
                        SERIDAR_DOKKI_ID
                    ),
            },
        ),
    )

    print(
        "old working hours:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.doctor_working_hours
            WHERE
                provider_id = :provider_id
                AND is_active = 1
                AND doctor_id <> :new_doctor_id
            """,
            params,
        ),
    )

    print()
    print(
        "=== SLOT CLEANUP ==="
    )

    print(
        "future AVAILABLE old slots to delete:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.doctor_availability_slots AS slot
            WHERE
                slot.provider_id = :provider_id
                AND slot.doctor_id <> :new_doctor_id
                AND slot.slot_date >= CAST(GETDATE() AS date)
                AND slot.status = 'available'

                AND NOT EXISTS (
                    SELECT 1
                    FROM dbo.appointments AS appointment
                    WHERE appointment.slot_id = slot.id
                )

                AND NOT EXISTS (
                    SELECT 1
                    FROM dbo.appointment_status_history AS history
                    WHERE
                        history.old_slot_id = slot.id
                        OR
                        history.new_slot_id = slot.id
                )
            """,
            params,
        ),
    )

    print(
        "booked slots preserved:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.doctor_availability_slots
            WHERE
                provider_id = :provider_id
                AND status = 'booked'
            """,
            params,
        ),
    )

    print()
    print(
        "=== HISTORICAL DATA ==="
    )

    print(
        "appointments preserved:",
        scalar(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.appointments
            WHERE provider_id = :provider_id
            """,
            params,
        ),
    )

    print()
    print(
        "=== NEW ACTIVE CATALOG ==="
    )

    print(
        "Doctor:",
        "Dr. Maher Mahmoud",
    )

    print(
        "Specialty:",
        "Dermatology",
    )

    print(
        "Booking service:",
        "Dermatology Consultation",
    )

    print(
        "Branch 1:",
        "Cairo Medical Center",
    )

    print(
        "Branch 2:",
        "Tower Of Seridar, Dokki",
    )

    print()
    print(
        "DATABASE NOT MODIFIED"
    )


# ============================================================
# APPLY MIGRATION
# ============================================================

def apply_migration(
    session,
    *,
    provider_id: str,
    specialty_id: str,
    service_id: str,
) -> None:

    common = {
        "provider_id":
            provider_id,

        "doctor_id":
            str(DR_MAHER_ID),
    }

    # --------------------------------------------------------
    # Provider identity
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.providers
            SET
                name = :name,
                slug = :slug,
                phone = :phone,
                email = :email,
                address = :address,
                updated_at = SYSUTCDATETIME()
            WHERE id = :provider_id;
            """
        ),
        {
            "provider_id":
                provider_id,

            "name":
                PROVIDER_NAME,

            "slug":
                PROVIDER_SLUG,

            "phone":
                PROVIDER_PHONE,

            "email":
                PROVIDER_EMAIL,

            "address":
                PROVIDER_ADDRESS,
        },
    )

    # --------------------------------------------------------
    # Specialties
    #
    # Keep Dermatology only.
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.specialties
            SET is_active = 0
            WHERE provider_id = :provider_id;
            """
        ),
        common,
    )

    session.execute(
        text(
            """
            UPDATE dbo.specialties
            SET is_active = 1
            WHERE
                provider_id = :provider_id
                AND id = :specialty_id;
            """
        ),
        {
            **common,

            "specialty_id":
                specialty_id,
        },
    )

    # --------------------------------------------------------
    # Old doctors
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.doctors
            SET is_active = 0
            WHERE
                provider_id = :provider_id
                AND id <> :doctor_id;
            """
        ),
        common,
    )

    # --------------------------------------------------------
    # Old doctor relations
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.doctor_branches
            SET is_active = 0
            WHERE provider_id = :provider_id;
            """
        ),
        common,
    )

    session.execute(
        text(
            """
            UPDATE dbo.doctor_services
            SET is_active = 0
            WHERE provider_id = :provider_id;
            """
        ),
        common,
    )

    # --------------------------------------------------------
    # Old working hours
    #
    # Do not deactivate future Dr. Maher schedule
    # if this migration is run again later.
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.doctor_working_hours
            SET
                is_active = 0,
                updated_at = SYSUTCDATETIME()
            WHERE
                provider_id = :provider_id
                AND doctor_id <> :doctor_id;
            """
        ),
        common,
    )

    # --------------------------------------------------------
    # Old future AVAILABLE slots
    #
    # BOOKED slots are intentionally preserved.
    # --------------------------------------------------------

    session.execute(
        text(
            """
            DELETE FROM dbo.doctor_availability_slots
            WHERE
                provider_id = :provider_id
                AND doctor_id <> :doctor_id
                AND slot_date >= CAST(GETDATE() AS date)
                AND status = 'available'

                AND NOT EXISTS (
                    SELECT 1
                    FROM dbo.appointments AS appointment
                    WHERE
                        appointment.slot_id =
                            dbo.doctor_availability_slots.id
                )

                AND NOT EXISTS (
                    SELECT 1
                    FROM dbo.appointment_status_history AS history
                    WHERE
                        history.old_slot_id =
                            dbo.doctor_availability_slots.id
                        OR
                        history.new_slot_id =
                            dbo.doctor_availability_slots.id
                );
            """
        ),
        common,
    )

    # --------------------------------------------------------
    # Services
    #
    # Keep only Dermatology Consultation active.
    # Official consultation fee is not stored because
    # we have not verified a published price.
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.services
            SET is_active = 0
            WHERE provider_id = :provider_id;
            """
        ),
        common,
    )

    session.execute(
        text(
            """
            UPDATE dbo.services
            SET
                name_ar = N'كشف جلدية',
                name_en = 'Dermatology Consultation',
                description_ar =
                    N'استشارة في الأمراض الجلدية',
                description_en =
                    'Dermatology consultation',
                duration_minutes = 30,
                price = NULL,
                service_type = 'consultation',
                requires_preparation = 0,
                preparation_instructions_ar = NULL,
                preparation_instructions_en = NULL,
                is_active = 1
            WHERE
                provider_id = :provider_id
                AND id = :service_id;
            """
        ),
        {
            **common,

            "service_id":
                service_id,
        },
    )

    # --------------------------------------------------------
    # Old branches
    # --------------------------------------------------------

    session.execute(
        text(
            """
            UPDATE dbo.branches
            SET is_active = 0
            WHERE provider_id = :provider_id;
            """
        ),
        common,
    )

    # --------------------------------------------------------
    # Dr. Maher
    # --------------------------------------------------------

    doctor_exists = exists(
        session,
        """
        SELECT COUNT(*)
        FROM dbo.doctors
        WHERE id = :doctor_id
        """,
        {
            "doctor_id":
                str(DR_MAHER_ID),
        },
    )

    doctor_params = {
        "doctor_id":
            str(DR_MAHER_ID),

        "provider_id":
            provider_id,

        "specialty_id":
            specialty_id,

        "full_name_ar":
            "د. ماهر محمود",

        "full_name_en":
            "Dr. Maher Mahmoud",

        "bio_ar":
            (
                "استشاري الأمراض الجلدية "
                "والتجميل والعلاج بالليزر."
            ),

        "bio_en":
            (
                "Consultant of Dermatology, "
                "Cosmetic Medicine and Laser Therapy."
            ),
    }

    if doctor_exists:

        session.execute(
            text(
                """
                UPDATE dbo.doctors
                SET
                    provider_id = :provider_id,
                    specialty_id = :specialty_id,
                    full_name_ar = :full_name_ar,
                    full_name_en = :full_name_en,
                    bio_ar = :bio_ar,
                    bio_en = :bio_en,
                    consultation_fee = NULL,
                    teleconsultation_fee = NULL,
                    experience_years = NULL,
                    rating_avg = NULL,
                    review_count = 0,
                    accepting_new_patients = 1,
                    verification_status = 'verified',
                    is_active = 1
                WHERE id = :doctor_id;
                """
            ),
            doctor_params,
        )

    else:

        session.execute(
            text(
                """
                INSERT INTO dbo.doctors (
                    id,
                    provider_id,
                    specialty_id,
                    full_name_ar,
                    full_name_en,
                    license_number,
                    bio_ar,
                    bio_en,
                    consultation_fee,
                    teleconsultation_fee,
                    experience_years,
                    gender,
                    photo_url,
                    rating_avg,
                    review_count,
                    accepting_new_patients,
                    verification_status,
                    is_active
                )
                VALUES (
                    :doctor_id,
                    :provider_id,
                    :specialty_id,
                    :full_name_ar,
                    :full_name_en,
                    NULL,
                    :bio_ar,
                    :bio_en,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    0,
                    1,
                    'verified',
                    1
                );
                """
            ),
            doctor_params,
        )

    # --------------------------------------------------------
    # Branches
    # --------------------------------------------------------

    branches = [
    {
        "id":
            str(
                CAIRO_MEDICAL_CENTER_ID
            ),

        "code":
            "CMC",

        "mrn_code":
            "CMC",

        "name_ar":
            "مركز القاهرة الطبي",

        "name_en":
            "Cairo Medical Center",

        "address_ar":
            "القاهرة، مصر",

        "address_en":
            "Cairo Medical Center, Cairo, Egypt",

        "is_primary":
            True,
    },
    {
        "id":
            str(
                SERIDAR_DOKKI_ID
            ),

        "code":
            "SERIDAR",

        "mrn_code":
            "SER",

        "name_ar":
            "برج سيريدار - الدقي",

        "name_en":
            "Tower Of Seridar - Dokki",

        "address_ar":
            "الدقي، القاهرة، مصر",

        "address_en":
            "Tower Of Seridar, Dokki, Cairo, Egypt",

        "is_primary":
            False,
    },
]

    for branch in branches:

        branch_exists = exists(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.branches
            WHERE id = :id
            """,
            {
                "id":
                    branch["id"],
            },
        )

        params = {
            "id":
                branch["id"],

            "provider_id":
                provider_id,

            "code":
                branch["code"],

            "mrn_code":
                branch["mrn_code"],

            "name_ar":
                branch["name_ar"],

            "name_en":
                branch["name_en"],

            "address_ar":
                branch["address_ar"],

            "address_en":
                branch["address_en"],

            "phone":
                PROVIDER_PHONE,
        }

        if branch_exists:

            session.execute(
                text(
                    """
                    UPDATE dbo.branches
                    SET
                        provider_id = :provider_id,
                        code = :code,
                        mrn_code = :mrn_code,
                        name_ar = :name_ar,
                        name_en = :name_en,
                        address_ar = :address_ar,
                        address_en = :address_en,
                        governorate = N'Cairo',
                        phone = :phone,
                        whatsapp = NULL,
                        timezone = 'Africa/Cairo',
                        is_active = 1
                    WHERE id = :id;
                    """
                ),
                params,
            )

        else:

            session.execute(
                text(
                    """
                    INSERT INTO dbo.branches (
                        id,
                        provider_id,
                        code,
                        mrn_code,
                        name_ar,
                        name_en,
                        address_ar,
                        address_en,
                        governorate,
                        latitude,
                        longitude,
                        phone,
                        whatsapp,
                        timezone,
                        is_active
                    )
                    VALUES (
                        :id,
                        :provider_id,
                        :code,
                        :mrn_code,
                        :name_ar,
                        :name_en,
                        :address_ar,
                        :address_en,
                        N'Cairo',
                        NULL,
                        NULL,
                        :phone,
                        NULL,
                        'Africa/Cairo',
                        1
                    );
                    """
                ),
                params,
            )

    # --------------------------------------------------------
    # Doctor ↔ Branch
    # --------------------------------------------------------

    doctor_branch_links = [
        (
            str(
                DR_MAHER_CMC_LINK_ID
            ),
            str(
                CAIRO_MEDICAL_CENTER_ID
            ),
            1,
        ),
        (
            str(
                DR_MAHER_SERIDAR_LINK_ID
            ),
            str(
                SERIDAR_DOKKI_ID
            ),
            0,
        ),
    ]

    for (
        link_id,
        branch_id,
        is_primary,
    ) in doctor_branch_links:

        link_exists = exists(
            session,
            """
            SELECT COUNT(*)
            FROM dbo.doctor_branches
            WHERE id = :id
            """,
            {
                "id":
                    link_id,
            },
        )

        params = {
            "id":
                link_id,

            "provider_id":
                provider_id,

            "doctor_id":
                str(
                    DR_MAHER_ID
                ),

            "branch_id":
                branch_id,

            "is_primary":
                is_primary,
        }

        if link_exists:

            session.execute(
                text(
                    """
                    UPDATE dbo.doctor_branches
                    SET
                        provider_id = :provider_id,
                        doctor_id = :doctor_id,
                        branch_id = :branch_id,
                        is_primary = :is_primary,
                        is_active = 1
                    WHERE id = :id;
                    """
                ),
                params,
            )

        else:

            session.execute(
                text(
                    """
                    INSERT INTO dbo.doctor_branches (
                        id,
                        provider_id,
                        doctor_id,
                        branch_id,
                        is_primary,
                        is_active
                    )
                    VALUES (
                        :id,
                        :provider_id,
                        :doctor_id,
                        :branch_id,
                        :is_primary,
                        1
                    );
                    """
                ),
                params,
            )

    # --------------------------------------------------------
    # Doctor ↔ Dermatology Consultation
    # --------------------------------------------------------

    doctor_service_exists = exists(
        session,
        """
        SELECT COUNT(*)
        FROM dbo.doctor_services
        WHERE id = :id
        """,
        {
            "id":
                str(
                    DR_MAHER_SERVICE_LINK_ID
                ),
        },
    )

    doctor_service_params = {
        "id":
            str(
                DR_MAHER_SERVICE_LINK_ID
            ),

        "provider_id":
            provider_id,

        "doctor_id":
            str(
                DR_MAHER_ID
            ),

        "service_id":
            service_id,
    }

    if doctor_service_exists:

        session.execute(
            text(
                """
                UPDATE dbo.doctor_services
                SET
                    provider_id = :provider_id,
                    doctor_id = :doctor_id,
                    service_id = :service_id,
                    fee_override = NULL,
                    duration_override_minutes = NULL,
                    is_active = 1
                WHERE id = :id;
                """
            ),
            doctor_service_params,
        )

    else:

        session.execute(
            text(
                """
                INSERT INTO dbo.doctor_services (
                    id,
                    provider_id,
                    doctor_id,
                    service_id,
                    fee_override,
                    duration_override_minutes,
                    is_active
                )
                VALUES (
                    :id,
                    :provider_id,
                    :doctor_id,
                    :service_id,
                    NULL,
                    NULL,
                    1
                );
                """
            ),
            doctor_service_params,
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually apply the migration. "
            "Without this flag the script is read-only."
        ),
    )

    args = parser.parse_args()

    session = SessionLocal()

    try:

        provider = get_provider(
            session
        )

        provider_id = str(
            provider["id"]
        )

        specialty = (
            get_dermatology_specialty(
                session,
                provider_id,
            )
        )

        service = (
            get_dermatology_service(
                session,
                provider_id,
            )
        )

        if not args.apply:

            preview(
                session,
                provider_id=
                    provider_id,
            )

            return

        print(
            "Applying migration..."
        )

        apply_migration(
            session,

            provider_id=
                provider_id,

            specialty_id=
                str(
                    specialty["id"]
                ),

            service_id=
                str(
                    service["id"]
                ),
        )

        session.commit()

        print()
        print(
            "MIGRATION APPLIED SUCCESSFULLY"
        )

        print(
            "New provider:",
            PROVIDER_NAME,
        )

        print(
            "New doctor ID:",
            DR_MAHER_ID,
        )

        print()
        print(
            "No new booking schedule was created yet."
        )

        print(
            "Historical appointments and booked slots "
            "were preserved."
        )

    except Exception:

        session.rollback()

        raise

    finally:

        session.close()


if __name__ == "__main__":
    main()