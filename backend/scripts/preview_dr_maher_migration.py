from __future__ import annotations

from sqlalchemy import text

from app.db.session import SessionLocal


TENANT_KEY = "clinic-001"


def scalar(session, sql: str, params: dict) -> int:
    return int(
        session.execute(
            text(sql),
            params,
        ).scalar_one()
    )


def main() -> None:
    session = SessionLocal()

    try:
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
            .one()
        )

        provider_id = str(
            provider["id"]
        )

        params = {
            "provider_id":
                provider_id,
        }

        print(
            "=== PROVIDER ==="
        )
        print(
            dict(provider)
        )

        print()
        print(
            "=== CURRENT ACTIVE CATALOG ==="
        )

        print(
            "specialties:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.specialties
                WHERE
                    provider_id = :provider_id
                    AND is_active = 1
                """,
                params,
            ),
        )

        print(
            "doctors:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.doctors
                WHERE
                    provider_id = :provider_id
                    AND is_active = 1
                """,
                params,
            ),
        )

        print(
            "services:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.services
                WHERE
                    provider_id = :provider_id
                    AND is_active = 1
                """,
                params,
            ),
        )

        print(
            "branches:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.branches
                WHERE
                    provider_id = :provider_id
                    AND is_active = 1
                """,
                params,
            ),
        )

        print(
            "working_hours:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.doctor_working_hours
                WHERE
                    provider_id = :provider_id
                    AND is_active = 1
                """,
                params,
            ),
        )

        print()
        print(
            "=== SLOT SAFETY ==="
        )

        print(
            "future_available_slots:",
            scalar(
                session,
                """
                SELECT COUNT(*)
                FROM dbo.doctor_availability_slots
                WHERE
                    provider_id = :provider_id
                    AND slot_date >= CAST(GETDATE() AS date)
                    AND status = 'available'
                """,
                params,
            ),
        )

        print(
            "booked_slots:",
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
            "=== APPOINTMENTS ==="
        )

        print(
            "appointments:",
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
            "DRY RUN ONLY - DATABASE NOT MODIFIED"
        )

    finally:
        session.close()


if __name__ == "__main__":
    main()