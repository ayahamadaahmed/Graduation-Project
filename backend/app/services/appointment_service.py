from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.exc import (
    IntegrityError,
    SQLAlchemyError,
)
from app.services.idempotency_service import (
    IdempotencyService,
)
from app.repositories.idempotency_repository import (
    idempotency_repository,
)

from app.core.idempotency_exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from app.core.patient_identity import (
    PatientIdentityProtector,
)

from app.repositories.patient_repository import (
    PatientRepository,
)

from app.services.patient_branch_profile_service import (
    PatientBranchProfileService,
)

from app.repositories.appointment_repository import (
    AppointmentRepository,
)
from app.schemas.appointment import (
    AppointmentCancelRequest,
    AppointmentCancelResponse,
    AppointmentCreateRequest,
    AppointmentCreateResponse,
    AppointmentDetails,
    AppointmentRead,
    AppointmentRescheduleRequest,
    AppointmentRescheduleResponse,
    AppointmentSearchByNationalIdRequest,
    AppointmentSearchItem,
    AppointmentsByNationalIdResponse,
    PatientAppointmentsResponse,
    AppointmentLookupRequest,
    AppointmentLookupResponse,
)

class AppointmentService:

    def __init__(
        self,
        repository: AppointmentRepository,
        patient_repository: PatientRepository,
        identity_protector: PatientIdentityProtector,
        branch_profile_service: PatientBranchProfileService,
        idempotency_service: IdempotencyService,
    ) -> None:
        self.repository = repository
        self.patient_repository = patient_repository
        self.identity_protector = identity_protector
        self.branch_profile_service = branch_profile_service
        self.idempotency_service = idempotency_service

    def create_confirmed_booking(
        self,
        *,
        provider_id: UUID,
        provider_timezone: str,
        data: AppointmentCreateRequest,
        idempotency_key: str | None = None,
    ) -> AppointmentCreateResponse:
        session = self.repository.session

        try:
            patient = (
                self
                ._resolve_patient_by_national_id(
                    provider_id=provider_id,
                    national_id=(
                        data.national_id
                    ),
                )
            )

            patient_id = patient.id


            # =====================================
            # Idempotency
            # =====================================

            idempotency_record = None

            if idempotency_key:

                # Never store/hash the raw national ID
                # as the request identity.
                #
                # Resolve it first, then use the
                # internal patient UUID.
                idempotency_payload = (
                    data.model_dump(
                        mode="json",
                        exclude={
                            "national_id",
                        },
                    )
                )

                idempotency_payload[
                    "patient_id"
                ] = str(
                    patient_id
                )

                try:

                    idem = (
                        self.idempotency_service.begin(
                            session,
                            # Use the validated internal
                            # provider scope, not the raw
                            # X-Tenant-ID header.
                            tenant_id=str(
                                provider_id
                            ),
                            operation=(
                                "create_booking"
                            ),
                            idempotency_key=(
                                idempotency_key
                            ),
                            payload=(
                                idempotency_payload
                            ),
                        )
                    )

                except IdempotencyConflictError as exc:

                    raise HTTPException(
                        status_code=(
                            status.HTTP_409_CONFLICT
                        ),
                        detail={
                            "code":
                                "IDEMPOTENCY_CONFLICT",

                            "message":
                                (
                                    "The Idempotency-Key "
                                    "was already used with "
                                    "different booking data."
                                ),
                        },
                    ) from exc

                except IdempotencyInProgressError as exc:

                    raise HTTPException(
                        status_code=(
                            status.HTTP_409_CONFLICT
                        ),
                        detail={
                            "code":
                                "IDEMPOTENCY_IN_PROGRESS",

                            "message":
                                (
                                    "The booking request "
                                    "is already being processed."
                                ),
                        },
                    ) from exc

                except RuntimeError as exc:

                    raise HTTPException(
                        status_code=(
                            status.HTTP_503_SERVICE_UNAVAILABLE
                        ),
                        detail={
                            "code":
                                "IDEMPOTENCY_UNAVAILABLE",

                            "message":
                                (
                                    "The booking request could "
                                    "not be safely processed."
                                ),
                        },
                    ) from exc

                # =================================
                # Replay previous successful result
                # =================================

                if idem.is_replay:
                    cached_response = (
                        AppointmentCreateResponse
                        .model_validate(
                            idem.cached_response
                        )
                    )

                    # sp_getapplock uses LockOwner=Transaction.
                    # Release the replay transaction immediately.
                    session.rollback()

                    return cached_response

                idempotency_record = (
                    idem.record
                )


            # The row is locked until commit or rollback.
            slot = self.repository.lock_slot(
                provider_id=provider_id,
                slot_id=data.slot_id,
            )

            if slot is None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                    ),
                    detail={
                        "code": "SLOT_NOT_FOUND",
                        "message": (
                            "The slot was not found "
                            "for this provider."
                        ),
                    },
                )

            if slot["status"] != "available":
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": "SLOT_UNAVAILABLE",
                        "message": (
                            "The selected slot is "
                            "no longer available."
                        ),
                    },
                )

            provider_now = datetime.now(
                ZoneInfo(provider_timezone)
            )

            slot_start = datetime.combine(
                slot["slot_date"],
                slot["start_time"],
                tzinfo=ZoneInfo(
                    provider_timezone
                ),
            )

            if slot_start <= provider_now:
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": "PAST_SLOT",
                        "message": (
                            "A past slot cannot "
                            "be booked."
                        ),
                    },
                )

            doctor_id = UUID(
                str(slot["doctor_id"])
            )

            branch_id = UUID(
                str(slot["branch_id"])
            )

            if not (
                self.repository
                .doctor_branch_is_valid(
                    provider_id=provider_id,
                    doctor_id=doctor_id,
                    branch_id=branch_id,
                )
            ):
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "DOCTOR_BRANCH_MISMATCH"
                        ),
                        "message": (
                            "The slot doctor is not "
                            "active at this branch."
                        ),
                    },
                )
            branch_profile = (
                self.branch_profile_service
                .resolve(
                    provider_id=provider_id,
                    branch_id=branch_id,
                    patient_id=patient_id,
                    year=provider_now.year,
                )
            )
            if not (
                self.repository
                .doctor_service_is_valid(
                    provider_id=provider_id,
                    doctor_id=doctor_id,
                    service_id=data.service_id,
                )
            ):
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": (
                            "DOCTOR_SERVICE_MISMATCH"
                        ),
                        "message": (
                            "The selected doctor does "
                            "not provide this service."
                        ),
                    },
                )

            appointment_id = uuid4()

            appointment_reference = (
                self._generate_reference(
                    provider_timezone
                )
            )

            patient_name = (
                patient.full_name_ar
                or patient.full_name_en
            )
            self.repository.insert_appointment(
                appointment_id=appointment_id,
                provider_id=provider_id,
                appointment_reference=(
                    appointment_reference
                ),

                patient_id=patient_id,
                patient_name=patient.full_name_ar,
                phone=patient.phone,

                slot_id=data.slot_id,
                doctor_id=doctor_id,
                branch_id=branch_id,
                service_id=data.service_id,

                scheduled_date=(
                    slot["slot_date"]
                ),
                start_time=(
                    slot["start_time"]
                ),
                end_time=(
                    slot["end_time"]
                ),

                channel=data.channel,
                notes=data.notes,

                created_by_type=(
                    data.created_by_type
                ),
                created_by_reference=(
                    data.created_by_reference
                ),
            )

            slot_updated = (
                self.repository.mark_slot_booked(
                    provider_id=provider_id,
                    slot_id=data.slot_id,
                )
            )

            if not slot_updated:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": "SLOT_UNAVAILABLE",
                        "message": (
                            "The selected slot became "
                            "unavailable."
                        ),
                    },
                )

            self.repository.insert_status_history(
                provider_id=provider_id,
                appointment_id=appointment_id,
                slot_id=data.slot_id,
                changed_by=(
                    data.created_by_type
                ),
                actor_reference=(
                    data.created_by_reference
                ),
            )

            appointment = (
                self.repository
                .get_appointment_by_id(
                    appointment_id
                )
            )

            if appointment is None:
                raise RuntimeError(
                    "Appointment was inserted but "
                    "could not be read."
                )

            appointment[
                "branch_medical_record_number"
            ] = (
                branch_profile.medical_record_number
            )



            response = AppointmentCreateResponse(
                appointment_reference=(
                    appointment[
                        "appointment_reference"
                    ]
                ),
                patient_code=(
                    patient.patient_code
                ),
                patient_name=(
                    patient.full_name_ar
                ),
                branch_medical_record_number=(
                    branch_profile
                    .medical_record_number
                ),
                scheduled_date=(
                    appointment[
                        "scheduled_date"
                    ]
                ),
                start_time=(
                    appointment[
                        "start_time"
                    ]
                ),
                end_time=(
                    appointment[
                        "end_time"
                    ]
                ),
                channel=(
                    appointment["channel"]
                ),
                status=(
                    appointment["status"]
                ),
                notes=(
                    appointment["notes"]
                ),
                confirmed_at=(
                    appointment[
                        "confirmed_at"
                    ]
                ),
                reschedule_count=(
                    appointment[
                        "reschedule_count"
                    ]
                ),
                doctor_name=(
                    appointment.get(
                        "doctor_name"
                    )
                ),

                service_name=(
                    appointment.get(
                        "service_name"
                    )
                ),

                specialty_name=(
                    appointment.get(
                        "specialty_name"
                    )
                ),

                branch_name=(
                    appointment.get(
                        "branch_name"
                    )
                ),
            )

            if idempotency_record is not None:

                idempotency_repository.mark_completed(
                    idempotency_record,
                    response=(
                        response.model_dump(
                            mode="json"
                        )
                    ),
                )

            # =====================================
            # ONE atomic commit
            # =====================================

            session.commit()

            return response




        except HTTPException:
            session.rollback()
            raise

        except IntegrityError as exc:
            session.rollback()

            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": "BOOKING_CONFLICT",
                    "message": (
                        "The booking conflicted with "
                        "another active booking."
                    ),
                },
            ) from exc

        except SQLAlchemyError:
            session.rollback()
            raise

        except Exception:
            session.rollback()
            raise


    def cancel_booking(
    self,
    *,
    provider_id: UUID,
    appointment_reference: str,
    data: AppointmentCancelRequest,
    idempotency_key: str | None = None,
) -> AppointmentCancelResponse:

        session = self.repository.session

        try:
            # =====================================
            # 1. Resolve patient securely
            # =====================================

            patient = (
                self
                ._resolve_patient_by_national_id(
                    provider_id=provider_id,
                    national_id=data.national_id,
                )
            )

            normalized_reference = (
                appointment_reference
                .strip()
                .upper()
            )

            # =====================================
            # 2. Idempotency
            # =====================================

            idempotency_record = None

            if idempotency_key:

                # Do NOT include raw national ID
                # inside the idempotency payload.
                idempotency_payload = (
                    data.model_dump(
                        mode="json",
                        exclude={
                            "national_id",
                        },
                    )
                )

                # Use internal patient UUID instead.
                idempotency_payload[
                    "patient_id"
                ] = str(
                    patient.id
                )

                # Reference is part of the operation.
                idempotency_payload[
                    "appointment_reference"
                ] = normalized_reference

                try:
                    idem = (
                        self.idempotency_service.begin(
                            session,
                            tenant_id=str(
                                provider_id
                            ),
                            operation=(
                                "cancel_booking"
                            ),
                            idempotency_key=(
                                idempotency_key
                            ),
                            payload=(
                                idempotency_payload
                            ),
                        )
                    )

                except (
                    IdempotencyConflictError
                ) as exc:

                    raise HTTPException(
                        status_code=(
                            status.HTTP_409_CONFLICT
                        ),
                        detail={
                            "code": (
                                "IDEMPOTENCY_CONFLICT"
                            ),
                            "message": (
                                "The Idempotency-Key "
                                "was already used with "
                                "different cancellation "
                                "data."
                            ),
                        },
                    ) from exc

                except (
                    IdempotencyInProgressError
                ) as exc:

                    raise HTTPException(
                        status_code=(
                            status.HTTP_409_CONFLICT
                        ),
                        detail={
                            "code": (
                                "IDEMPOTENCY_IN_PROGRESS"
                            ),
                            "message": (
                                "The cancellation "
                                "request is already "
                                "being processed."
                            ),
                        },
                    ) from exc

                except RuntimeError as exc:

                    raise HTTPException(
                        status_code=(
                            status
                            .HTTP_503_SERVICE_UNAVAILABLE
                        ),
                        detail={
                            "code": (
                                "IDEMPOTENCY_UNAVAILABLE"
                            ),
                            "message": (
                                "The cancellation "
                                "could not be safely "
                                "processed."
                            ),
                        },
                    ) from exc

                # =================================
                # Replay previous successful result
                # =================================

                if idem.is_replay:

                    cached_response = (
                        AppointmentCancelResponse
                        .model_validate(
                            idem.cached_response
                        )
                    )

                    # Releases SQL Server
                    # transaction-scoped applock
                    # immediately.
                    session.rollback()

                    return cached_response

                idempotency_record = (
                    idem.record
                )

            # =====================================
            # 3. Lock appointment
            # =====================================

            appointment = (
                self.repository
                .lock_appointment_by_reference(
                    provider_id=provider_id,
                    appointment_reference=normalized_reference,
                )
            )

            if appointment is None:

                raise HTTPException(
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_NOT_FOUND"
                        ),
                        "message": (
                            "The appointment was not "
                            "found for this provider."
                        ),
                    },
                )

            # =====================================
            # 4. Verify appointment belongs
            #    to this patient
            # =====================================

            self._verify_appointment_patient(
                appointment=appointment,
                patient_id=patient.id,
            )

            previous_status = str(
                appointment["status"]
            )

            # =====================================
            # 5. Validate cancellation state
            # =====================================

            if previous_status == "cancelled":

                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_ALREADY_CANCELLED"
                        ),
                        "message": (
                            "The appointment is "
                            "already cancelled."
                        ),
                    },
                )

            if previous_status not in {
                "pending",
                "confirmed",
            }:

                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_NOT_CANCELLABLE"
                        ),
                        "message": (
                            "The appointment cannot "
                            "be cancelled in its "
                            "current status."
                        ),
                    },
                )

            appointment_id = UUID(
                str(
                    appointment["id"]
                )
            )

            slot_id = UUID(
                str(
                    appointment["slot_id"]
                )
            )

            # =====================================
            # 6. Cancel appointment
            # =====================================

            appointment_updated = (
                self.repository
                .mark_appointment_cancelled(
                    provider_id=provider_id,
                    appointment_id=(
                        appointment_id
                    ),
                    reason=data.reason,
                )
            )

            if not appointment_updated:

                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "CANCELLATION_CONFLICT"
                        ),
                        "message": (
                            "The appointment status "
                            "changed during "
                            "cancellation."
                        ),
                    },
                )

            # =====================================
            # 7. Release appointment slot
            # =====================================

            slot_released = (
                self.repository
                .release_slot(
                    provider_id=provider_id,
                    slot_id=slot_id,
                )
            )

            if not slot_released:

                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "SLOT_RELEASE_CONFLICT"
                        ),
                        "message": (
                            "The appointment was not "
                            "cancelled because its "
                            "slot could not be "
                            "released."
                        ),
                    },
                )

            # =====================================
            # 8. Save cancellation history
            # =====================================

            self.repository.insert_cancellation_history(
                provider_id=provider_id,
                appointment_id=appointment_id,
                slot_id=slot_id,
                previous_status=previous_status,
                changed_by=data.changed_by,
                actor_reference=(
                    data.actor_reference
                ),
                reason=data.reason,
            )

            # =====================================
            # 9. Read final result
            # =====================================

            result = (
                self.repository
                .get_cancellation_result(
                    provider_id=provider_id,
                    appointment_id=(
                        appointment_id
                    ),
                )
            )

            if result is None:

                raise RuntimeError(
                    "Cancellation succeeded but "
                    "the appointment could not "
                    "be read."
                )

            # =====================================
            # 10. Build response BEFORE commit
            # =====================================

            response = (
                AppointmentCancelResponse(
                    appointment_reference=(
                        result[
                            "appointment_reference"
                        ]
                    ),
                    previous_status=(
                        previous_status
                    ),
                    status=(
                        result["status"]
                    ),
                    slot_id=UUID(
                        str(
                            result["slot_id"]
                        )
                    ),
                    slot_status=(
                        result[
                            "slot_status"
                        ]
                    ),
                    cancelled_at=(
                        result[
                            "cancelled_at"
                        ]
                    ),
                    cancellation_reason=(
                        result[
                            "cancellation_reason"
                        ]
                    ),
                )
            )

            # =====================================
            # 11. Save idempotency result
            #     BEFORE commit
            # =====================================

            if idempotency_record is not None:

                idempotency_repository.mark_completed(
                    idempotency_record,
                    response=(
                        response.model_dump(
                            mode="json"
                        )
                    ),
                )

            # =====================================
            # 12. ONE atomic commit
            # =====================================

            session.commit()

            return response

        # =========================================
        # Error handling
        # =========================================

        except HTTPException:

            session.rollback()

            raise

        except IntegrityError as exc:

            session.rollback()

            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": (
                        "CANCELLATION_CONFLICT"
                    ),
                    "message": (
                        "The cancellation "
                        "conflicted with another "
                        "operation."
                    ),
                },
            ) from exc

        except SQLAlchemyError:

            session.rollback()

            raise

        except Exception:

            session.rollback()

            raise

    def reschedule_booking(
    self,
    *,
    provider_id: UUID,
    provider_timezone: str,
    appointment_reference: str,
    data: AppointmentRescheduleRequest,
    idempotency_key: str | None = None,
) -> AppointmentRescheduleResponse:
        session = self.repository.session

        try:
            patient = (
                self
                ._resolve_patient_by_national_id(
                    provider_id=provider_id,
                    national_id=data.national_id,
                )
            )

            normalized_reference = (
                appointment_reference
                .strip()
                .upper()
            )

            idempotency_record = None

            if idempotency_key:

                idempotency_payload = (
                    data.model_dump(
                        mode="json",
                        exclude={
                            "national_id",
                        },
                    )
                )

                # Never use the raw national ID
                # as part of idempotency identity.
                idempotency_payload[
                    "patient_id"
                ] = str(patient.id)

                idempotency_payload[
                    "appointment_reference"
                ] = normalized_reference

                try:
                    idem = (
                        self.idempotency_service.begin(
                            session,
                            tenant_id=str(provider_id),
                            operation="reschedule_booking",
                            idempotency_key=idempotency_key,
                            payload=idempotency_payload,
                        )
                    )

                except IdempotencyConflictError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": (
                                "The Idempotency-Key was already "
                                "used with different reschedule data."
                            ),
                        },
                    ) from exc

                except IdempotencyInProgressError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "IDEMPOTENCY_IN_PROGRESS",
                            "message": (
                                "The reschedule request is already "
                                "being processed."
                            ),
                        },
                    ) from exc

                except RuntimeError as exc:
                    raise HTTPException(
                        status_code=(
                            status.HTTP_503_SERVICE_UNAVAILABLE
                        ),
                        detail={
                            "code": "IDEMPOTENCY_UNAVAILABLE",
                            "message": (
                                "The reschedule request could "
                                "not be safely processed."
                            ),
                        },
                    ) from exc

                if idem.is_replay:
                    cached_response = (
                        AppointmentRescheduleResponse
                        .model_validate(
                            idem.cached_response
                        )
                    )

                    # sp_getapplock uses LockOwner=Transaction.
                    # Release the replay transaction immediately.
                    session.rollback()

                    return cached_response

                idempotency_record = idem.record
            # 1. Lock the appointment.
            appointment = (
                self.repository
                .lock_appointment_by_reference(
                    provider_id=provider_id,
                    appointment_reference=normalized_reference,
                )
            )

            if appointment is None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_NOT_FOUND"
                        ),
                        "message": (
                            "The appointment was not "
                            "found for this provider."
                        ),
                    },
                )
            self._verify_appointment_patient(
                appointment=appointment,
                patient_id=patient.id,
            )
            previous_status = str(
                appointment["status"]
            )

            if previous_status == "cancelled":
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "CANCELLED_APPOINTMENT"
                        ),
                        "message": (
                            "A cancelled appointment "
                            "cannot be rescheduled."
                        ),
                    },
                )

            if previous_status not in {
                "pending",
                "confirmed",
            }:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_NOT_"
                            "RESCHEDULABLE"
                        ),
                        "message": (
                            "The appointment cannot "
                            "be rescheduled in its "
                            "current status."
                        ),
                    },
                )

            appointment_id = UUID(
                str(appointment["id"])
            )

            old_slot_id = UUID(
                str(appointment["slot_id"])
            )

            if data.new_slot_id == old_slot_id:
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": "SAME_SLOT",
                        "message": (
                            "The new slot must be "
                            "different from the "
                            "current slot."
                        ),
                    },
                )

            service_id_value = appointment[
                "service_id"
            ]

            if service_id_value is None:
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": (
                            "APPOINTMENT_SERVICE_MISSING"
                        ),
                        "message": (
                            "The appointment has no "
                            "service to validate."
                        ),
                    },
                )

            service_id = UUID(
                str(service_id_value)
            )

            # 2. Lock the new slot.
            new_slot = self.repository.lock_slot(
                provider_id=provider_id,
                slot_id=data.new_slot_id,
            )

            if new_slot is None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_404_NOT_FOUND
                    ),
                    detail={
                        "code": "NEW_SLOT_NOT_FOUND",
                        "message": (
                            "The new slot was not "
                            "found for this provider."
                        ),
                    },
                )

            if new_slot["status"] != "available":
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "NEW_SLOT_UNAVAILABLE"
                        ),
                        "message": (
                            "The selected new slot "
                            "is no longer available."
                        ),
                    },
                )

            provider_zone = ZoneInfo(
                provider_timezone
            )

            new_slot_start = datetime.combine(
                new_slot["slot_date"],
                new_slot["start_time"],
                tzinfo=provider_zone,
            )

            if new_slot_start <= datetime.now(
                provider_zone
            ):
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": "PAST_NEW_SLOT",
                        "message": (
                            "The new slot must be "
                            "in the future."
                        ),
                    },
                )

            new_doctor_id = UUID(
                str(new_slot["doctor_id"])
            )

            new_branch_id = UUID(
                str(new_slot["branch_id"])
            )

            # 3. Validate doctor and branch.
            doctor_branch_valid = (
                self.repository
                .doctor_branch_is_valid(
                    provider_id=provider_id,
                    doctor_id=new_doctor_id,
                    branch_id=new_branch_id,
                )
            )

            if not doctor_branch_valid:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "DOCTOR_BRANCH_MISMATCH"
                        ),
                        "message": (
                            "The new slot doctor is "
                            "not active at its branch."
                        ),
                    },
                )

            # 4. Validate existing service
            # against the new doctor.
            doctor_service_valid = (
                self.repository
                .doctor_service_is_valid(
                    provider_id=provider_id,
                    doctor_id=new_doctor_id,
                    service_id=service_id,
                )
            )

            if not doctor_service_valid:
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_422_UNPROCESSABLE_ENTITY
                    ),
                    detail={
                        "code": (
                            "DOCTOR_SERVICE_MISMATCH"
                        ),
                        "message": (
                            "The new slot doctor does "
                            "not provide the current "
                            "appointment service."
                        ),
                    },
                )

            # 5. Release the old slot.
            old_slot_released = (
                self.repository.release_slot(
                    provider_id=provider_id,
                    slot_id=old_slot_id,
                )
            )

            if not old_slot_released:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "OLD_SLOT_RELEASE_CONFLICT"
                        ),
                        "message": (
                            "The current slot could "
                            "not be released."
                        ),
                    },
                )

            # 6. Mark new slot as booked.
            new_slot_booked = (
                self.repository.mark_slot_booked(
                    provider_id=provider_id,
                    slot_id=data.new_slot_id,
                )
            )

            if not new_slot_booked:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "NEW_SLOT_UNAVAILABLE"
                        ),
                        "message": (
                            "The new slot became "
                            "unavailable."
                        ),
                    },
                )

            # 7. Update the existing appointment.
            appointment_updated = (
                self.repository
                .update_appointment_for_reschedule(
                    provider_id=provider_id,
                    appointment_id=(
                        appointment_id
                    ),
                    old_slot_id=old_slot_id,
                    new_slot_id=(
                        data.new_slot_id
                    ),
                    doctor_id=new_doctor_id,
                    branch_id=new_branch_id,
                    scheduled_date=(
                        new_slot["slot_date"]
                    ),
                    start_time=(
                        new_slot["start_time"]
                    ),
                    end_time=(
                        new_slot["end_time"]
                    ),
                )
            )

            if not appointment_updated:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail={
                        "code": (
                            "RESCHEDULE_UPDATE_CONFLICT"
                        ),
                        "message": (
                            "The appointment changed "
                            "during rescheduling."
                        ),
                    },
                )

            # 8. Save the audit history.
            self.repository.insert_reschedule_history(
                provider_id=provider_id,
                appointment_id=appointment_id,
                old_slot_id=old_slot_id,
                new_slot_id=data.new_slot_id,
                previous_status=previous_status,
                changed_by=data.changed_by,
                actor_reference=(
                    data.actor_reference
                ),
                reason=data.reason,
            )

            result = (
                self.repository
                .get_reschedule_result(
                    provider_id=provider_id,
                    appointment_id=(
                        appointment_id
                    ),
                    old_slot_id=old_slot_id,
                )
            )

            if result is None:
                raise RuntimeError(
                    "Reschedule succeeded but "
                    "the result could not be read."
                )

            # 9. All changes are committed together.
            response = AppointmentRescheduleResponse(
                appointment_reference=(
                    result["appointment_reference"]
                ),
                previous_status=previous_status,
                status=result["status"],
                old_slot_id=old_slot_id,
                new_slot_id=UUID(
                    str(result["new_slot_id"])
                ),
                doctor_id=UUID(
                    str(result["doctor_id"])
                ),
                branch_id=UUID(
                    str(result["branch_id"])
                ),
                service_id=(
                    UUID(
                        str(result["service_id"])
                    )
                    if result["service_id"]
                    else None
                ),
                scheduled_date=(
                    result["scheduled_date"]
                ),
                start_time=(
                    result["start_time"]
                ),
                end_time=result["end_time"],
                old_slot_status=(
                    result["old_slot_status"]
                ),
                new_slot_status=(
                    result["new_slot_status"]
                ),
                reschedule_count=(
                    result["reschedule_count"]
                ),
                updated_at=result["updated_at"],
            )

            if idempotency_record is not None:
                idempotency_repository.mark_completed(
                    idempotency_record,
                    response=(
                        response.model_dump(
                            mode="json"
                        )
                    ),
                )

            # Appointment changes, slot changes, history,
            # and the idempotency receipt commit atomically.
            session.commit()

            return response

        except HTTPException:
            session.rollback()
            raise

        except IntegrityError as exc:
            session.rollback()

            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail={
                    "code": (
                        "RESCHEDULE_CONFLICT"
                    ),
                    "message": (
                        "The reschedule conflicted "
                        "with another operation."
                    ),
                },
            ) from exc

        except SQLAlchemyError:
            session.rollback()
            raise

        except Exception:
            session.rollback()
            raise
    @staticmethod
    def _generate_reference(
        provider_timezone: str,
    ) -> str:
        local_now = datetime.now(
            ZoneInfo(provider_timezone)
        )

        random_part = (
            uuid4().hex[:8].upper()
        )

        return (
            f"APT-"
            f"{local_now:%y%m%d}-"
            f"{random_part}"
        )


    def get_booking_by_reference(
        self,
        *,
        provider_id: UUID,
        appointment_reference: str,
    ) -> AppointmentDetails:
        normalized_reference = (
            appointment_reference
            .strip()
            .upper()
        )

        appointment = (
            self.repository
            .get_appointment_by_reference(
                provider_id=provider_id,
                appointment_reference=(
                    normalized_reference
                ),
            )
        )

        if appointment is None:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail={
                    "code": "APPOINTMENT_NOT_FOUND",
                    "message": (
                        "The appointment was not "
                        "found for this provider."
                    ),
                },
            )

        return AppointmentDetails(
            **appointment
        )

    def list_patient_bookings(
        self,
        *,
        provider_id: UUID,
        patient_id: UUID,
        include_cancelled: bool,
        limit: int,
    ) -> PatientAppointmentsResponse:
        patient = (
            self.repository
            .get_patient_for_provider(
                provider_id=provider_id,
                patient_id=patient_id,
            )
        )

        if patient is None:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail={
                    "code": (
                        "PATIENT_NOT_FOUND_FOR_PROVIDER"
                    ),
                    "message": (
                        "The active patient or "
                        "provider profile was not found."
                    ),
                },
            )

        rows = (
            self.repository
            .list_appointments_by_patient(
                provider_id=provider_id,
                patient_id=patient_id,
                include_cancelled=(
                    include_cancelled
                ),
                limit=limit,
            )
        )

        appointments = [
            AppointmentDetails(**row)
            for row in rows
        ]

        return PatientAppointmentsResponse(
            patient_id=patient_id,
            count=len(appointments),
            appointments=appointments,
        )

    def _resolve_patient_by_national_id(
        self,
        *,
        provider_id: UUID,
        national_id: str,
    ):
        try:
            national_id_hash = (
                self.identity_protector
                .hash_national_id(
                    national_id
                )
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={
                    "code": (
                        "INVALID_NATIONAL_ID"
                    ),
                    "message": str(exc),
                },
            ) from exc

        patient = (
            self.patient_repository
            .get_active_by_national_id_hash(
                national_id_hash
            )
        )

        if patient is None:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail={
                    "code": "PATIENT_NOT_FOUND",
                    "message": (
                        "No active patient was found "
                        "for the provided national ID."
                    ),
                },
            )

        provider_profile = (
            self.patient_repository
            .get_provider_profile(
                patient_id=patient.id,
                provider_id=provider_id,
            )
        )

        if (
            provider_profile is None
            or not provider_profile.is_active
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail={
                    "code": (
                        "PATIENT_NOT_FOUND_FOR_PROVIDER"
                    ),
                    "message": (
                        "The patient does not have "
                        "an active profile for this "
                        "provider."
                    ),
                },
            )


        return patient

    def search_bookings_by_national_id(
        self,
        *,
        provider_id: UUID,
        data: AppointmentSearchByNationalIdRequest,
    ) -> AppointmentsByNationalIdResponse:

        patient = (
            self
            ._resolve_patient_by_national_id(
                provider_id=provider_id,
                national_id=data.national_id,
            )
        )

        rows = (
            self.repository
            .list_appointments_by_patient(
                provider_id=provider_id,
                patient_id=patient.id,
                include_cancelled=(
                    data.include_cancelled
                ),
                limit=data.limit,
            )
        )

        appointments = [
            AppointmentSearchItem(
                appointment_reference=(
                    row[
                        "appointment_reference"
                    ]
                ),
                patient_name=(
                    row["patient_name"]
                ),
                branch_medical_record_number=(
                    row.get(
                        "branch_medical_record_number"
                    )
                ),
                scheduled_date=(
                    row["scheduled_date"]
                ),
                start_time=(
                    row["start_time"]
                ),
                end_time=(
                    row["end_time"]
                ),
                status=row["status"],
                channel=row["channel"],
                notes=row["notes"],
                reschedule_count=(
                    row["reschedule_count"]
                ),
                cancellation_reason=(
                    row[
                        "cancellation_reason"
                    ]
                ),
                confirmed_at=(
                    row["confirmed_at"]
                ),
                cancelled_at=(
                    row["cancelled_at"]
                ),

                doctor_name=row.get(
                    "doctor_name"
                ),

                service_name=row.get(
                    "service_name"
                ),

                specialty_name=row.get(
                    "specialty_name"
                ),

                branch_name=row.get(
                    "branch_name"
                ),
            )
            for row in rows
        ]

        return AppointmentsByNationalIdResponse(
            patient_code=(
                patient.patient_code
            ),
            patient_name=(
                patient.full_name_ar
            ),
            count=len(appointments),
            appointments=appointments,

        )


    def _verify_appointment_patient(
        self,
        *,
        appointment: dict,
        patient_id: UUID,
    ) -> None:
        appointment_patient_id = UUID(
            str(
                appointment[
                    "patient_id"
                ]
            )
        )

        if appointment_patient_id != patient_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "APPOINTMENT_NOT_FOUND",
                    "message": (
                        "No appointment was found "
                        "for this patient."
                    ),
                },
            )

    def lookup_booking_for_patient(
    self,
    *,
    provider_id: UUID,
    data: AppointmentLookupRequest,
) -> AppointmentLookupResponse:

        patient = (
            self
            ._resolve_patient_by_national_id(
                provider_id=provider_id,
                national_id=data.national_id,
            )
        )

        reference = (
            data.appointment_reference
            .strip()
            .upper()
        )

        appointment = (
            self.repository
            .get_appointment_by_reference(
                provider_id=provider_id,
                appointment_reference=reference,
            )
        )

        if appointment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "APPOINTMENT_NOT_FOUND",
                    "message": (
                        "No appointment was found "
                        "for this patient."
                    ),
                },
            )

        self._verify_appointment_patient(
            appointment=appointment,
            patient_id=patient.id,
        )

        return AppointmentLookupResponse(
            appointment_reference=(
                appointment[
                    "appointment_reference"
                ]
            ),

            patient_code=(
                patient.patient_code
            ),

            patient_name=(
                appointment[
                    "patient_name"
                ]
            ),

            branch_medical_record_number=(
                appointment.get(
                    "branch_medical_record_number"
                )
            ),

            # ----------------------------------------------------
            # Trusted internal IDs
            # ----------------------------------------------------

            doctor_id=(
                appointment[
                    "doctor_id"
                ]
            ),

            branch_id=(
                appointment[
                    "branch_id"
                ]
            ),

            service_id=(
                appointment.get(
                    "service_id"
                )
            ),

            slot_id=(
                appointment[
                    "slot_id"
                ]
            ),

            # ----------------------------------------------------
            # Display values
            # ----------------------------------------------------

            doctor_name=(
                appointment.get(
                    "doctor_name"
                )
            ),

            specialty_name=(
                appointment.get(
                    "specialty_name"
                )
            ),

            service_name=(
                appointment.get(
                    "service_name"
                )
            ),

            branch_name=(
                appointment.get(
                    "branch_name"
                )
            ),

            scheduled_date=(
                appointment[
                    "scheduled_date"
                ]
            ),

            start_time=(
                appointment[
                    "start_time"
                ]
            ),

            end_time=(
                appointment[
                    "end_time"
                ]
            ),

            status=(
                appointment[
                    "status"
                ]
            ),

            channel=(
                appointment[
                    "channel"
                ]
            ),

            notes=(
                appointment[
                    "notes"
                ]
            ),

            reschedule_count=(
                appointment[
                    "reschedule_count"
                ]
            ),

            confirmed_at=(
                appointment[
                    "confirmed_at"
                ]
            ),

            cancellation_reason=(
                appointment[
                    "cancellation_reason"
                ]
            ),

            cancelled_at=(
                appointment[
                    "cancelled_at"
                ]
            ),
        )
