from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class AppointmentRepository:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def get_patient_for_provider(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                patient.id,
                patient.patient_code,
                patient.full_name_ar,
                patient.full_name_en,
                patient.phone,
                patient.is_active,
                profile.id AS provider_profile_id,
                profile.is_active AS profile_is_active
            FROM dbo.patients AS patient

            INNER JOIN dbo.patient_provider_profiles AS profile
                ON profile.patient_id = patient.id
                AND profile.provider_id = :provider_id

            WHERE
                patient.id = :patient_id
                AND patient.is_active = 1
                AND profile.is_active = 1;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "patient_id": str(patient_id),
            },
        ).mappings().first()

        return dict(row) if row else None

    def lock_slot(
        self,
        *,
        provider_id: UUID,
        slot_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                slot.id,
                slot.provider_id,
                slot.doctor_id,
                slot.branch_id,
                slot.slot_date,
                slot.start_time,
                slot.end_time,
                slot.status
            FROM dbo.doctor_availability_slots AS slot
                WITH (
                    UPDLOCK,
                    HOLDLOCK,
                    ROWLOCK
                )
            WHERE
                slot.id = :slot_id
                AND slot.provider_id = :provider_id;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "slot_id": str(slot_id),
            },
        ).mappings().first()

        return dict(row) if row else None

    def doctor_branch_is_valid(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        branch_id: UUID,
    ) -> bool:
        statement = text(
            """
            SELECT TOP 1
                doctor_branch.id
            FROM dbo.doctor_branches AS doctor_branch

            INNER JOIN dbo.doctors AS doctor
                ON doctor.id = doctor_branch.doctor_id
                AND doctor.provider_id = :provider_id
                AND doctor.is_active = 1

            INNER JOIN dbo.branches AS branch
                ON branch.id = doctor_branch.branch_id
                AND branch.provider_id = :provider_id
                AND branch.is_active = 1

            WHERE
                doctor_branch.provider_id = :provider_id
                AND doctor_branch.doctor_id = :doctor_id
                AND doctor_branch.branch_id = :branch_id
                AND doctor_branch.is_active = 1;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "doctor_id": str(doctor_id),
                "branch_id": str(branch_id),
            },
        ).first()

        return row is not None

    def doctor_service_is_valid(
        self,
        *,
        provider_id: UUID,
        doctor_id: UUID,
        service_id: UUID,
    ) -> bool:
        statement = text(
            """
            SELECT TOP 1
                doctor_service.id
            FROM dbo.doctor_services AS doctor_service

            INNER JOIN dbo.services AS service
                ON service.id = doctor_service.service_id
                AND service.provider_id = :provider_id
                AND service.is_active = 1

            INNER JOIN dbo.doctors AS doctor
                ON doctor.id = doctor_service.doctor_id
                AND doctor.provider_id = :provider_id
                AND doctor.is_active = 1

            WHERE
                doctor_service.provider_id = :provider_id
                AND doctor_service.doctor_id = :doctor_id
                AND doctor_service.service_id = :service_id
                AND doctor_service.is_active = 1;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "doctor_id": str(doctor_id),
                "service_id": str(service_id),
            },
        ).first()

        return row is not None

    def insert_appointment(
        self,
        *,
        appointment_id: UUID,
        provider_id: UUID,
        appointment_reference: str,
        patient_id: UUID,
        patient_name: str,
        phone: str,
        slot_id: UUID,
        doctor_id: UUID,
        branch_id: UUID,
        service_id: UUID,
        scheduled_date: Any,
        start_time: Any,
        end_time: Any,
        channel: str,
        notes: str | None,
        created_by_type: str,
        created_by_reference: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO dbo.appointments (
                id,
                provider_id,
                appointment_reference,

                patient_id,
                patient_name,
                phone,

                slot_id,
                doctor_id,
                branch_id,
                service_id,

                scheduled_date,
                start_time,
                end_time,

                channel,
                status,
                notes,

                cancellation_reason,
                confirmed_at,
                cancelled_at,

                created_at,
                updated_at,

                created_by_type,
                created_by_reference,
                reschedule_count
            )
            VALUES (
                :id,
                :provider_id,
                :appointment_reference,

                :patient_id,
                :patient_name,
                :phone,

                :slot_id,
                :doctor_id,
                :branch_id,
                :service_id,

                :scheduled_date,
                :start_time,
                :end_time,

                :channel,
                'confirmed',
                :notes,

                NULL,
                SYSUTCDATETIME(),
                NULL,

                SYSUTCDATETIME(),
                SYSUTCDATETIME(),

                :created_by_type,
                :created_by_reference,
                0
            );
            """
        )

        self.session.execute(
            statement,
            {
                "id": str(appointment_id),
                "provider_id": str(provider_id),
                "appointment_reference": (
                    appointment_reference
                ),
                "patient_id": str(patient_id),
                "patient_name": patient_name,
                "phone": phone,
                "slot_id": str(slot_id),
                "doctor_id": str(doctor_id),
                "branch_id": str(branch_id),
                "service_id": str(service_id),
                "scheduled_date": scheduled_date,
                "start_time": start_time,
                "end_time": end_time,
                "channel": channel,
                "notes": notes,
                "created_by_type": created_by_type,
                "created_by_reference": (
                    created_by_reference
                ),
            },
        )

    def mark_slot_booked(
        self,
        *,
        provider_id: UUID,
        slot_id: UUID,
    ) -> bool:
        statement = text(
            """
            UPDATE dbo.doctor_availability_slots
            SET
                status = 'booked',
                hold_expires_at = NULL,
                hold_reference = NULL,
                updated_at = SYSUTCDATETIME()
            WHERE
                id = :slot_id
                AND provider_id = :provider_id
                AND status = 'available';
            """
        )

        result = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "slot_id": str(slot_id),
            },
        )

        return result.rowcount == 1

    def insert_status_history(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        slot_id: UUID,
        changed_by: str,
        actor_reference: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO dbo.appointment_status_history (
                provider_id,
                appointment_id,
                event_type,
                previous_status,
                new_status,
                old_slot_id,
                new_slot_id,
                changed_by,
                actor_reference,
                reason,
                changed_at
            )
            VALUES (
                :provider_id,
                :appointment_id,
                'created',
                NULL,
                'confirmed',
                NULL,
                :new_slot_id,
                :changed_by,
                :actor_reference,
                NULL,
                SYSUTCDATETIME()
            );
            """
        )

        self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "new_slot_id": str(slot_id),
                "changed_by": changed_by,
                "actor_reference": actor_reference,
            },
        )

    def get_appointment_by_id(
        self,
        appointment_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                appointment.id,
                appointment.provider_id,
                appointment.appointment_reference,

                appointment.patient_id,
                appointment.patient_name,
                appointment.phone,

                appointment.slot_id,
                appointment.doctor_id,
                appointment.branch_id,
                appointment.service_id,

                branch_profile.medical_record_number
                    AS branch_medical_record_number,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        doctor.full_name_en,
                        doctor.full_name_ar
                    )
                    ELSE COALESCE(
                        doctor.full_name_ar,
                        doctor.full_name_en
                    )
                END AS doctor_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        service.name_en,
                        service.name_ar
                    )
                    ELSE COALESCE(
                        service.name_ar,
                        service.name_en
                    )
                END AS service_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        specialty.name_en,
                        specialty.name_ar
                    )
                    ELSE COALESCE(
                        specialty.name_ar,
                        specialty.name_en
                    )
                END AS specialty_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        branch.name_en,
                        branch.name_ar
                    )
                    ELSE COALESCE(
                        branch.name_ar,
                        branch.name_en
                    )
                END AS branch_name,

                appointment.scheduled_date,
                appointment.start_time,
                appointment.end_time,

                appointment.channel,
                appointment.status,
                appointment.notes,

                appointment.cancellation_reason,
                appointment.confirmed_at,
                appointment.cancelled_at,

                appointment.created_at,
                appointment.updated_at,

                appointment.created_by_type,
                appointment.created_by_reference,
                appointment.reschedule_count

            FROM dbo.appointments AS appointment

            INNER JOIN dbo.patients AS patient
                ON patient.id = appointment.patient_id

            INNER JOIN dbo.doctors AS doctor
                ON doctor.id = appointment.doctor_id
                AND doctor.provider_id =
                    appointment.provider_id

            INNER JOIN dbo.branches AS branch
                ON branch.id = appointment.branch_id
                AND branch.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.services AS service
                ON service.id = appointment.service_id
                AND service.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.specialties AS specialty
                ON specialty.id = doctor.specialty_id
                AND specialty.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.patient_branch_profiles
                AS branch_profile
                ON branch_profile.provider_id =
                    appointment.provider_id
                AND branch_profile.branch_id =
                    appointment.branch_id
                AND branch_profile.patient_id =
                    appointment.patient_id
                AND branch_profile.is_active = 1

            WHERE
                appointment.id = :appointment_id;
            """
        )

        row = self.session.execute(
            statement,
            {
                "appointment_id": str(
                    appointment_id
                ),
            },
        ).mappings().first()

        return dict(row) if row else None

    def lock_appointment_by_reference(
        self,
        *,
        provider_id: UUID,
        appointment_reference: str,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                appointment.id,
                appointment.provider_id,
                appointment.appointment_reference,
                appointment.patient_id,
                appointment.patient_name,
                appointment.phone,
                appointment.slot_id,
                appointment.doctor_id,
                appointment.branch_id,
                appointment.service_id,
                appointment.scheduled_date,
                appointment.start_time,
                appointment.end_time,
                appointment.status,
                appointment.cancellation_reason,
                appointment.cancelled_at
            FROM dbo.appointments AS appointment
                WITH (
                    UPDLOCK,
                    HOLDLOCK,
                    ROWLOCK
                )
            WHERE
                appointment.provider_id = :provider_id
                AND appointment.appointment_reference =
                    :appointment_reference;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_reference": (
                    appointment_reference
                ),
            },
        ).mappings().first()

        return dict(row) if row else None

    def mark_appointment_cancelled(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        reason: str | None,
    ) -> bool:
        statement = text(
            """
            UPDATE dbo.appointments
            SET
                status = 'cancelled',
                cancellation_reason = :reason,
                cancelled_at = SYSUTCDATETIME(),
                updated_at = SYSUTCDATETIME()
            WHERE
                id = :appointment_id
                AND provider_id = :provider_id
                AND status IN (
                    'pending',
                    'confirmed'
                );
            """
        )

        result = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "reason": reason,
            },
        )

        return result.rowcount == 1

    def release_slot(
        self,
        *,
        provider_id: UUID,
        slot_id: UUID,
    ) -> bool:
        statement = text(
            """
            UPDATE dbo.doctor_availability_slots
            SET
                status = 'available',
                hold_expires_at = NULL,
                hold_reference = NULL,
                updated_at = SYSUTCDATETIME()
            WHERE
                id = :slot_id
                AND provider_id = :provider_id
                AND status = 'booked';
            """
        )

        result = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "slot_id": str(slot_id),
            },
        )

        return result.rowcount == 1

    def insert_cancellation_history(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        slot_id: UUID,
        previous_status: str,
        changed_by: str,
        actor_reference: str | None,
        reason: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO dbo.appointment_status_history (
                provider_id,
                appointment_id,

                event_type,
                previous_status,
                new_status,

                old_slot_id,
                new_slot_id,

                changed_by,
                actor_reference,
                reason,

                changed_at
            )
            VALUES (
                :provider_id,
                :appointment_id,

                'cancelled',
                :previous_status,
                'cancelled',

                :old_slot_id,
                NULL,

                :changed_by,
                :actor_reference,
                :reason,

                SYSUTCDATETIME()
            );
            """
        )

        self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "previous_status": (
                    previous_status
                ),
                "old_slot_id": str(slot_id),
                "changed_by": changed_by,
                "actor_reference": (
                    actor_reference
                ),
                "reason": reason,
            },
        )


    def get_cancellation_result(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                appointment.appointment_reference,
                appointment.status,
                appointment.slot_id,
                appointment.cancelled_at,
                appointment.cancellation_reason,
                slot.status AS slot_status
            FROM dbo.appointments AS appointment

            INNER JOIN dbo.doctor_availability_slots AS slot
                ON slot.id = appointment.slot_id

            WHERE
                appointment.id = :appointment_id
                AND appointment.provider_id = :provider_id;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
            },
        ).mappings().first()

        return dict(row) if row else None

    def update_appointment_for_reschedule(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        old_slot_id: UUID,
        new_slot_id: UUID,
        doctor_id: UUID,
        branch_id: UUID,
        scheduled_date: Any,
        start_time: Any,
        end_time: Any,
    ) -> bool:
        statement = text(
            """
            UPDATE dbo.appointments
            SET
                slot_id = :new_slot_id,
                doctor_id = :doctor_id,
                branch_id = :branch_id,

                scheduled_date = :scheduled_date,
                start_time = :start_time,
                end_time = :end_time,

                reschedule_count =
                    reschedule_count + 1,

                updated_at =
                    SYSUTCDATETIME()

            WHERE
                id = :appointment_id
                AND provider_id = :provider_id
                AND slot_id = :old_slot_id
                AND status IN (
                    'pending',
                    'confirmed'
                );
            """
        )

        result = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "old_slot_id": str(old_slot_id),
                "new_slot_id": str(new_slot_id),
                "doctor_id": str(doctor_id),
                "branch_id": str(branch_id),
                "scheduled_date": scheduled_date,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

        return result.rowcount == 1

    def insert_reschedule_history(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        old_slot_id: UUID,
        new_slot_id: UUID,
        previous_status: str,
        changed_by: str,
        actor_reference: str | None,
        reason: str | None,
    ) -> None:
        statement = text(
            """
            INSERT INTO dbo.appointment_status_history (
                provider_id,
                appointment_id,

                event_type,
                previous_status,
                new_status,

                old_slot_id,
                new_slot_id,

                changed_by,
                actor_reference,
                reason,

                changed_at
            )
            VALUES (
                :provider_id,
                :appointment_id,

                'rescheduled',
                :previous_status,
                :new_status,

                :old_slot_id,
                :new_slot_id,

                :changed_by,
                :actor_reference,
                :reason,

                SYSUTCDATETIME()
            );
            """
        )

        self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "previous_status": (
                    previous_status
                ),
                "new_status": previous_status,
                "old_slot_id": str(old_slot_id),
                "new_slot_id": str(new_slot_id),
                "changed_by": changed_by,
                "actor_reference": (
                    actor_reference
                ),
                "reason": reason,
            },
        )

    def get_reschedule_result(
        self,
        *,
        provider_id: UUID,
        appointment_id: UUID,
        old_slot_id: UUID,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                appointment.appointment_reference,
                appointment.status,

                appointment.slot_id
                    AS new_slot_id,

                appointment.doctor_id,
                appointment.branch_id,
                appointment.service_id,

                appointment.scheduled_date,
                appointment.start_time,
                appointment.end_time,

                appointment.reschedule_count,
                appointment.updated_at,

                old_slot.status
                    AS old_slot_status,

                new_slot.status
                    AS new_slot_status

            FROM dbo.appointments AS appointment

            INNER JOIN
                dbo.doctor_availability_slots
                AS new_slot
                ON new_slot.id =
                    appointment.slot_id

            INNER JOIN
                dbo.doctor_availability_slots
                AS old_slot
                ON old_slot.id =
                    :old_slot_id

            WHERE
                appointment.id =
                    :appointment_id
                AND appointment.provider_id =
                    :provider_id;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(provider_id),
                "appointment_id": str(
                    appointment_id
                ),
                "old_slot_id": str(old_slot_id),
            },
        ).mappings().first()

        return dict(row) if row else None

    def get_appointment_by_reference(
        self,
        *,
        provider_id: UUID,
        appointment_reference: str,
    ) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                appointment.id,
                appointment.provider_id,
                appointment.appointment_reference,

                appointment.patient_id,
                appointment.patient_name,
                appointment.phone,

                appointment.slot_id,
                appointment.doctor_id,
                appointment.branch_id,
                appointment.service_id,

                branch_profile.medical_record_number
                    AS branch_medical_record_number,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        doctor.full_name_en,
                        doctor.full_name_ar
                    )
                    ELSE COALESCE(
                        doctor.full_name_ar,
                        doctor.full_name_en
                    )
                END AS doctor_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        service.name_en,
                        service.name_ar
                    )
                    ELSE COALESCE(
                        service.name_ar,
                        service.name_en
                    )
                END AS service_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        specialty.name_en,
                        specialty.name_ar
                    )
                    ELSE COALESCE(
                        specialty.name_ar,
                        specialty.name_en
                    )
                END AS specialty_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        branch.name_en,
                        branch.name_ar
                    )
                    ELSE COALESCE(
                        branch.name_ar,
                        branch.name_en
                    )
                END AS branch_name,

                appointment.scheduled_date,
                appointment.start_time,
                appointment.end_time,

                appointment.channel,
                appointment.status,
                appointment.notes,

                appointment.cancellation_reason,
                appointment.confirmed_at,
                appointment.cancelled_at,

                appointment.created_at,
                appointment.updated_at,

                appointment.created_by_type,
                appointment.created_by_reference,
                appointment.reschedule_count

            FROM dbo.appointments AS appointment

            INNER JOIN dbo.patients AS patient
                ON patient.id = appointment.patient_id

            INNER JOIN dbo.doctors AS doctor
                ON doctor.id = appointment.doctor_id
                AND doctor.provider_id =
                    appointment.provider_id

            INNER JOIN dbo.branches AS branch
                ON branch.id = appointment.branch_id
                AND branch.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.services AS service
                ON service.id = appointment.service_id
                AND service.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.specialties AS specialty
                ON specialty.id = doctor.specialty_id
                AND specialty.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.patient_branch_profiles
                AS branch_profile
                ON branch_profile.provider_id =
                    appointment.provider_id
                AND branch_profile.branch_id =
                    appointment.branch_id
                AND branch_profile.patient_id =
                    appointment.patient_id
                AND branch_profile.is_active = 1

            WHERE
                appointment.provider_id =
                    :provider_id

                AND appointment.appointment_reference =
                    :appointment_reference;
            """
        )

        row = self.session.execute(
            statement,
            {
                "provider_id": str(
                    provider_id
                ),
                "appointment_reference": (
                    appointment_reference
                ),
            },
        ).mappings().first()

        return dict(row) if row else None

    def list_appointments_by_patient(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        include_cancelled: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT TOP (:limit)
                appointment.id,
                appointment.provider_id,
                appointment.appointment_reference,

                appointment.patient_id,
                appointment.patient_name,
                appointment.phone,

                appointment.slot_id,
                appointment.doctor_id,
                appointment.branch_id,
                appointment.service_id,

                branch_profile.medical_record_number
                    AS branch_medical_record_number,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        doctor.full_name_en,
                        doctor.full_name_ar
                    )
                    ELSE COALESCE(
                        doctor.full_name_ar,
                        doctor.full_name_en
                    )
                END AS doctor_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        service.name_en,
                        service.name_ar
                    )
                    ELSE COALESCE(
                        service.name_ar,
                        service.name_en
                    )
                END AS service_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        specialty.name_en,
                        specialty.name_ar
                    )
                    ELSE COALESCE(
                        specialty.name_ar,
                        specialty.name_en
                    )
                END AS specialty_name,

                CASE
                    WHEN patient.preferred_language = 'en'
                    THEN COALESCE(
                        branch.name_en,
                        branch.name_ar
                    )
                    ELSE COALESCE(
                        branch.name_ar,
                        branch.name_en
                    )
                END AS branch_name,

                appointment.scheduled_date,
                appointment.start_time,
                appointment.end_time,

                appointment.channel,
                appointment.status,
                appointment.notes,

                appointment.cancellation_reason,
                appointment.confirmed_at,
                appointment.cancelled_at,

                appointment.created_at,
                appointment.updated_at,

                appointment.created_by_type,
                appointment.created_by_reference,
                appointment.reschedule_count

            FROM dbo.appointments AS appointment

            INNER JOIN dbo.patients AS patient
                ON patient.id = appointment.patient_id

            INNER JOIN dbo.doctors AS doctor
                ON doctor.id = appointment.doctor_id
                AND doctor.provider_id =
                    appointment.provider_id

            INNER JOIN dbo.branches AS branch
                ON branch.id = appointment.branch_id
                AND branch.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.services AS service
                ON service.id = appointment.service_id
                AND service.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.specialties AS specialty
                ON specialty.id = doctor.specialty_id
                AND specialty.provider_id =
                    appointment.provider_id

            LEFT JOIN dbo.patient_branch_profiles
                AS branch_profile
                ON branch_profile.provider_id =
                    appointment.provider_id
                AND branch_profile.branch_id =
                    appointment.branch_id
                AND branch_profile.patient_id =
                    appointment.patient_id
                AND branch_profile.is_active = 1

            WHERE
                appointment.provider_id =
                    :provider_id

                AND appointment.patient_id =
                    :patient_id

                AND (
                    :include_cancelled = 1
                    OR appointment.status
                        <> 'cancelled'
                )

            ORDER BY
                appointment.scheduled_date DESC,
                appointment.start_time DESC,
                appointment.created_at DESC;
            """
        )

        rows = self.session.execute(
            statement,
            {
                "provider_id": str(
                    provider_id
                ),
                "patient_id": str(
                    patient_id
                ),
                "include_cancelled": (
                    1
                    if include_cancelled
                    else 0
                ),
                "limit": limit,
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]