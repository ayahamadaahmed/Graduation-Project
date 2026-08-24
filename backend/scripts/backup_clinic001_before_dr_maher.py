from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal


TENANT_KEY = "clinic-001"

TABLES = [
    "providers",
    "specialties",
    "doctors",
    "services",
    "branches",
    "doctor_branches",
    "doctor_services",
    "doctor_working_hours",
    "doctor_availability_slots",
    "appointments",
]


def main() -> None:
    session = SessionLocal()

    try:
        provider_id = session.execute(
            text(
                """
                SELECT id
                FROM dbo.providers
                WHERE tenant_key = :tenant_key
                """
            ),
            {
                "tenant_key": TENANT_KEY,
            },
        ).scalar_one()

        backup = {
            "tenant_key": TENANT_KEY,
            "provider_id": str(provider_id),
            "created_at": datetime.now().isoformat(),
            "tables": {},
        }

        for table in TABLES:

            if table == "providers":

                sql = """
                SELECT *
                FROM dbo.providers
                WHERE id = :provider_id
                """

            else:

                sql = f"""
                SELECT *
                FROM dbo.{table}
                WHERE provider_id = :provider_id
                """

            rows = (
                session.execute(
                    text(sql),
                    {
                        "provider_id":
                            str(provider_id),
                    },
                )
                .mappings()
                .all()
            )

            backup["tables"][table] = [
                dict(row)
                for row in rows
            ]

            print(
                f"{table}: {len(rows)}"
            )

        output_dir = Path(
            "backups"
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_dir
            / "clinic001_before_dr_maher.json"
        )

        output_path.write_text(
            json.dumps(
                backup,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print()
        print(
            "BACKUP CREATED:"
        )

        print(
            output_path.resolve()
        )

    finally:
        session.close()


if __name__ == "__main__":
    main()