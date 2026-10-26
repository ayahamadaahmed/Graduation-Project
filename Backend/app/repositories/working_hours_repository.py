from datetime import date, time
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session
from typing import List
from app.models import (
    Branch,
    Doctor,
    DoctorBranch,
    DoctorWorkingHour,
    Provider,
)

def slot_owner_key(
    doctor_id: object | None,
    branch_id: object,
) -> str:
    """
    Uniqueness owner of a slot: the doctor, or the branch for
    branch-level lab slots (matches the filtered unique indexes).
    """
    if doctor_id is not None:
        return str(doctor_id).lower()

    return f"branch:{str(branch_id).lower()}"


class WorkingHoursRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def provider_is_lab(
        self,
        provider_id: UUID,
    ) -> bool:
        statement = select(Provider.id).where(
            Provider.id == provider_id,
            Provider.org_type == "diagnostic_lab",
        )
        return self.session.scalar(statement) is not None

    def doctor_exists(
        self,
        provider_id: UUID,
        doctor_id: UUID,
    ) -> bool:
        statement = select(Doctor.id).where(
            Doctor.id == doctor_id,
            Doctor.provider_id == provider_id,
            Doctor.is_active == 1,
        )

        return self.session.scalar(statement) is not None

    def branch_exists(
        self,
        provider_id: UUID,
        branch_id: UUID,
    ) -> bool:
        statement = select(Branch.id).where(
            Branch.id == branch_id,
            Branch.provider_id == provider_id,
            Branch.is_active == 1,
        )

        return self.session.scalar(statement) is not None

    def doctor_works_at_branch(
        self,
        provider_id: UUID,
        doctor_id: UUID,
        branch_id: UUID,
    ) -> bool:
        statement = select(DoctorBranch.id).where(
            DoctorBranch.provider_id == provider_id,
            DoctorBranch.doctor_id == doctor_id,
            DoctorBranch.branch_id == branch_id,
            DoctorBranch.is_active == 1,
        )

        return self.session.scalar(statement) is not None

    def find_overlapping_schedule(
        self,
        provider_id: UUID,
        doctor_id: UUID | None,
        branch_id: UUID,
        day_of_week: int,
        start_time: time,
        end_time: time,
    ) -> DoctorWorkingHour | None:
        statement = select(DoctorWorkingHour).where(
            DoctorWorkingHour.provider_id == provider_id,
            DoctorWorkingHour.doctor_id == doctor_id,
            DoctorWorkingHour.branch_id == branch_id,
            DoctorWorkingHour.day_of_week == day_of_week,
            DoctorWorkingHour.is_active == 1,

            # Existing schedule starts before the new one ends
            DoctorWorkingHour.start_time < end_time,

            # Existing schedule ends after the new one starts
            DoctorWorkingHour.end_time > start_time,
        )

        return self.session.scalar(statement)

    def add(
        self,
        working_hour: DoctorWorkingHour,
    ) -> DoctorWorkingHour:
        self.session.add(working_hour)
        self.session.flush()

        return working_hour

    def list(
        self,
        provider_id: UUID,
        doctor_id: UUID | None = None,
        branch_id: UUID | None = None,
        day_of_week: int | None = None,
    ) -> list[DoctorWorkingHour]:
        statement = select(DoctorWorkingHour).where(
            DoctorWorkingHour.provider_id == provider_id,
            DoctorWorkingHour.is_active == 1,
        )

        if doctor_id is not None:
            statement = statement.where(
                DoctorWorkingHour.doctor_id == doctor_id
            )

        if branch_id is not None:
            statement = statement.where(
                DoctorWorkingHour.branch_id == branch_id
            )

        if day_of_week is not None:
            statement = statement.where(
                DoctorWorkingHour.day_of_week == day_of_week
            )

        statement = statement.order_by(
            DoctorWorkingHour.doctor_id,
            DoctorWorkingHour.day_of_week,
            DoctorWorkingHour.start_time,
        )

        return list(
            self.session.scalars(statement).all()
        )

    def list_schedulable(
        self,
        provider_id: UUID,
        doctor_id: UUID | None = None,
        branch_id: UUID | None = None,
    ) -> List[DoctorWorkingHour]:
        statement = (
            select(DoctorWorkingHour)
            # Outer joins: lab schedules are branch-level (doctor_id IS NULL).
            .outerjoin(
                Doctor,
                Doctor.id == DoctorWorkingHour.doctor_id,
            )
            .join(
                Branch,
                Branch.id == DoctorWorkingHour.branch_id,
            )
            .join(
                Provider,
                Provider.id == DoctorWorkingHour.provider_id,
            )
            .outerjoin(
                DoctorBranch,
                (
                    (DoctorBranch.provider_id == provider_id)
                    & (
                        DoctorBranch.doctor_id
                        == DoctorWorkingHour.doctor_id
                    )
                    & (
                        DoctorBranch.branch_id
                        == DoctorWorkingHour.branch_id
                    )
                ),
            )
            .where(
                DoctorWorkingHour.provider_id == provider_id,
                DoctorWorkingHour.is_active == 1,
                Branch.provider_id == provider_id,
                Branch.is_active == 1,
                or_(
                    and_(
                        DoctorWorkingHour.doctor_id.is_(None),
                        Provider.org_type == "diagnostic_lab",
                    ),
                    and_(
                        Doctor.provider_id == provider_id,
                        Doctor.is_active == 1,
                        DoctorBranch.is_active == 1,
                    ),
                ),
            )
        )

        if doctor_id is not None:
            statement = statement.where(
                DoctorWorkingHour.doctor_id == doctor_id
            )

        if branch_id is not None:
            statement = statement.where(
                DoctorWorkingHour.branch_id == branch_id
            )

        statement = statement.order_by(
            DoctorWorkingHour.doctor_id,
            DoctorWorkingHour.day_of_week,
            DoctorWorkingHour.start_time,
        )

        return list(
            self.session.scalars(statement).all()
        )

    def existing_slot_keys(
    self,
    provider_id: UUID,
    date_from: date,
    date_to: date,
    doctor_id: UUID | None = None,
    branch_id: UUID | None = None,
) -> set[tuple[str, date, time]]:
        sql_parts = [
            """
            SELECT
                doctor_id,
                branch_id,
                slot_date,
                start_time
            FROM dbo.doctor_availability_slots
            WHERE
                provider_id = :provider_id
                AND slot_date >= :date_from
                AND slot_date <= :date_to
            """
        ]

        parameters: dict[str, object] = {
            "provider_id": str(provider_id),
            "date_from": date_from,
            "date_to": date_to,
        }

        if doctor_id is not None:
            sql_parts.append(
                "AND doctor_id = :doctor_id"
            )
            parameters["doctor_id"] = str(doctor_id)

        if branch_id is not None:
            sql_parts.append(
                "AND branch_id = :branch_id"
            )
            parameters["branch_id"] = str(branch_id)

        rows = self.session.execute(
            text("\n".join(sql_parts)),
            parameters,
        ).mappings().all()

        return {
            (
                slot_owner_key(
                    row["doctor_id"],
                    row["branch_id"],
                ),
                row["slot_date"],
                row["start_time"],
            )
            for row in rows
        }

    def insert_slot(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID | None,
        branch_id: UUID,
        working_hours_id: UUID,
        slot_date: date,
        start_time: time,
        end_time: time,
    ) -> None:
        statement = text(
            """
            INSERT INTO dbo.doctor_availability_slots (
                id,
                provider_id,
                doctor_id,
                branch_id,
                working_hours_id,
                slot_date,
                start_time,
                end_time,
                status,
                hold_expires_at,
                hold_reference,
                is_waitlist_fill,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :provider_id,
                :doctor_id,
                :branch_id,
                :working_hours_id,
                :slot_date,
                :start_time,
                :end_time,
                'available',
                NULL,
                NULL,
                0,
                SYSDATETIMEOFFSET(),
                SYSDATETIMEOFFSET()
            )
            """
        )

        self.session.execute(
            statement,
            {
                "id": str(uuid4()),
                "provider_id": str(provider_id),
                "doctor_id": (
                    str(doctor_id)
                    if doctor_id is not None
                    else None
                ),
                "branch_id": str(branch_id),
                "working_hours_id": str(
                    working_hours_id
                ),
                "slot_date": slot_date,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

