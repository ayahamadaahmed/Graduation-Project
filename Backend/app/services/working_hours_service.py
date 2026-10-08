from datetime import (
    date,
    datetime,
    time,
    timedelta,
    timezone,
)
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.models import DoctorWorkingHour
from app.repositories.working_hours_repository import (
    WorkingHoursRepository,
)

from app.schemas.working_hours import (
    SlotGenerationRequest,
    SlotGenerationResult,
    WorkingHourCreate,
)

def build_slot_intervals(
    start_time: time,
    end_time: time,
    duration_minutes: int,
) -> list[tuple[time, time]]:
    anchor_date = date(2000, 1, 1)

    current = datetime.combine(
        anchor_date,
        start_time,
    )

    finish = datetime.combine(
        anchor_date,
        end_time,
    )

    duration = timedelta(
        minutes=duration_minutes
    )

    intervals: list[tuple[time, time]] = []

    while current + duration <= finish:
        slot_end = current + duration

        intervals.append(
            (
                current.time(),
                slot_end.time(),
            )
        )

        current = slot_end

    return intervals

class WorkingHoursService:
    def __init__(
        self,
        repository: WorkingHoursRepository,
    ) -> None:
        self.repository = repository

    def create(
        self,
        provider_id: UUID,
        data: WorkingHourCreate,
    ) -> DoctorWorkingHour:
        if not self.repository.doctor_exists(
            provider_id,
            data.doctor_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DOCTOR_NOT_FOUND",
                    "message": (
                        "Doctor does not belong to this provider."
                    ),
                },
            )

        if not self.repository.branch_exists(
            provider_id,
            data.branch_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "BRANCH_NOT_FOUND",
                    "message": (
                        "Branch does not belong to this provider."
                    ),
                },
            )

        if not self.repository.doctor_works_at_branch(
            provider_id,
            data.doctor_id,
            data.branch_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "DOCTOR_BRANCH_MISMATCH",
                    "message": (
                        "Doctor is not assigned to this branch."
                    ),
                },
            )

        overlap = self.repository.find_overlapping_schedule(
            provider_id=provider_id,
            doctor_id=data.doctor_id,
            branch_id=data.branch_id,
            day_of_week=data.day_of_week,
            start_time=data.start_time,
            end_time=data.end_time,
        )

        if overlap is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "WORKING_HOURS_OVERLAP",
                    "message": (
                        "The requested working hours overlap "
                        "with an existing schedule."
                    ),
                },
            )

        now = datetime.now(timezone.utc)

        working_hour = DoctorWorkingHour(
            id=uuid4(),
            provider_id=provider_id,
            doctor_id=data.doctor_id,
            branch_id=data.branch_id,
            day_of_week=data.day_of_week,
            start_time=data.start_time,
            end_time=data.end_time,
            slot_duration_minutes=(
                data.slot_duration_minutes
            ),
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        try:
            self.repository.add(working_hour)
            self.repository.session.commit()
            self.repository.session.refresh(
                working_hour
            )

            return working_hour

        except IntegrityError as exc:
            self.repository.session.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "WORKING_HOURS_CONFLICT",
                    "message": (
                        "The working-hours record conflicts "
                        "with existing data."
                    ),
                },
            ) from exc

    def list(
        self,
        provider_id: UUID,
        doctor_id: UUID | None = None,
        branch_id: UUID | None = None,
        day_of_week: int | None = None,
    ) -> list[DoctorWorkingHour]:
        return self.repository.list(
            provider_id=provider_id,
            doctor_id=doctor_id,
            branch_id=branch_id,
            day_of_week=day_of_week,
        )

    def generate_slots(
    self,
    provider_id: UUID,
    provider_timezone: str,
    data: SlotGenerationRequest,
) -> SlotGenerationResult:
        provider_today = datetime.now(
            ZoneInfo(provider_timezone)
        ).date()

        if data.date_from < provider_today:
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": "PAST_GENERATION_DATE",
                    "message": (
                        "date_from must be today "
                        "or a future date."
                    ),
                },
            )

        working_hours = self.repository.list_schedulable(
            provider_id=provider_id,
            doctor_id=data.doctor_id,
            branch_id=data.branch_id,
        )

        if not working_hours:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "WORKING_HOURS_NOT_FOUND",
                    "message": (
                        "No active working hours "
                        "match this request."
                    ),
                },
            )

        existing_keys = (
            self.repository.existing_slot_keys(
                provider_id=provider_id,
                date_from=data.date_from,
                date_to=data.date_to,
                doctor_id=data.doctor_id,
                branch_id=data.branch_id,
            )
        )

        created_slots = 0
        skipped_slots = 0

        current_date = data.date_from

        try:
            while current_date <= data.date_to:
                current_weekday = (
                    current_date.weekday()
                )

                for schedule in working_hours:
                    if (
                        schedule.day_of_week
                        != current_weekday
                    ):
                        continue

                    intervals = build_slot_intervals(
                        start_time=schedule.start_time,
                        end_time=schedule.end_time,
                        duration_minutes=(
                            schedule
                            .slot_duration_minutes
                        ),
                    )

                    for slot_start, slot_end in intervals:
                        slot_key = (
                            str(
                                schedule.doctor_id
                            ).lower(),
                            current_date,
                            slot_start,
                        )

                        if slot_key in existing_keys:
                            skipped_slots += 1
                            continue

                        self.repository.insert_slot(
                            provider_id=provider_id,
                            doctor_id=(
                                schedule.doctor_id
                            ),
                            branch_id=(
                                schedule.branch_id
                            ),
                            working_hours_id=(
                                schedule.id
                            ),
                            slot_date=current_date,
                            start_time=slot_start,
                            end_time=slot_end,
                        )

                        existing_keys.add(slot_key)
                        created_slots += 1

                current_date += timedelta(days=1)

            self.repository.session.commit()

        except IntegrityError as exc:
            self.repository.session.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SLOT_GENERATION_CONFLICT",
                    "message": (
                        "A duplicate or conflicting "
                        "slot was detected."
                    ),
                },
            ) from exc

        return SlotGenerationResult(
            provider_id=provider_id,
            date_from=data.date_from,
            date_to=data.date_to,
            working_hours_used=len(
                working_hours
            ),
            created_slots=created_slots,
            skipped_existing_slots=(
                skipped_slots
            ),
        )