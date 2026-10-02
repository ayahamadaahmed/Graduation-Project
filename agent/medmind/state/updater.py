from __future__ import annotations

from typing import Any

from medmind.state.models import (
    DoctorSnapshot,
    ServiceSnapshot,
    SessionState,
    SlotSnapshot,
    SpecialtySnapshot,
)

def _ensure_list(
    data: Any,
) -> list:

    if data is None:
        return []

    if isinstance(
        data,
        list,
    ):
        return data

    return [
        data
    ]


# ============================================================
# SPECIALTIES
# ============================================================

def _save_specialties(
    *,
    state: SessionState,
    data,
) -> None:

    items = _ensure_list(
        data
    )

    specialties = []

    for item in items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if not item.get(
            "id"
        ):
            continue

        if not item.get(
            "code"
        ):
            continue

        specialties.append(
            SpecialtySnapshot(
                id=item[
                    "id"
                ],

                code=item[
                    "code"
                ],

                name_ar=item.get(
                    "name_ar"
                ),

                name_en=item.get(
                    "name_en"
                ),

                voice_label_ar=item.get(
                    "voice_label_ar"
                ),

                voice_label_en=item.get(
                    "voice_label_en"
                ),

                voice_featured_rank=item.get(
                    "voice_featured_rank"
                ),

                price=item.get(
                    "price"
                ),
            )
        )

    state.recent_specialties = (
        specialties
    )


# ============================================================
# DOCTORS
# ============================================================

def _save_doctors(
    *,
    state: SessionState,
    data,
) -> None:

    items = _ensure_list(
        data
    )

    doctors = []

    for item in items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        doctor_id = item.get(
            "id"
        )

        specialty_id = item.get(
            "specialty_id"
        )

        if (
            not doctor_id
            or not specialty_id
        ):
            continue

        doctors.append(
            DoctorSnapshot(
                id=doctor_id,

                specialty_id=
                    specialty_id,

                full_name_ar=
                    item.get(
                        "full_name_ar"
                    ),

                full_name_en=
                    item.get(
                        "full_name_en"
                    ),

                specialty_name_ar=
                    item.get(
                        "specialty_name_ar"
                    ),

                specialty_name_en=
                    item.get(
                        "specialty_name_en"
                    ),

                consultation_fee=
                    item.get(
                        "consultation_fee"
                    ),

                experience_years=
                    item.get(
                        "experience_years"
                    ),

                rating_avg=
                    item.get(
                        "rating_avg"
                    ),

                review_count=
                    item.get(
                        "review_count"
                    ),
            )
        )

    state.recent_doctors = (
        doctors
    )

    # --------------------------------------------------------
    # If all returned doctors belong
    # to one specialty, remember it.
    # --------------------------------------------------------

    specialty_ids = {
        doctor.specialty_id
        for doctor
        in doctors
    }

    if len(
        specialty_ids
    ) == 1:

        state.specialty_id = (
            next(
                iter(
                    specialty_ids
                )
            )
        )

        first = doctors[0]

        state.specialty_name = (
            first.specialty_name_ar
            or
            first.specialty_name_en
        )


# ============================================================
# SERVICES
# ============================================================

def _save_services(
    *,
    state: SessionState,
    data,
) -> None:

    items = _ensure_list(
        data
    )

    services = []

    for item in items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if (
            not item.get("id")
            or not item.get("code")
        ):
            continue

        services.append(
            ServiceSnapshot(
                id=item[
                    "id"
                ],

                code=item[
                    "code"
                ],

                name_ar=item.get(
                    "name_ar"
                ),

                name_en=item.get(
                    "name_en"
                ),

                voice_label_ar=item.get(
                    "voice_label_ar"
                ),

                voice_label_en=item.get(
                    "voice_label_en"
                ),

                voice_featured_rank=item.get(
                    "voice_featured_rank"
                ),

                price=item.get(
                    "price"
                ),

                service_type=
                    item.get(
                        "service_type"
                    ),
            )
        )

    state.recent_services = (
        services
    )


# ============================================================
# SLOTS
# ============================================================

def _save_slots(
    *,
    state: SessionState,
    data,
) -> None:

    items = _ensure_list(
        data
    )

    slots = []

    for item in items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        slot_id = item.get(
            "id"
        )

        doctor_id = item.get(
            "doctor_id"
        )

        branch_id = item.get(
            "branch_id"
        )

        slot_date = item.get(
            "slot_date"
        )

        start_time = item.get(
            "start_time"
        )

        end_time = item.get(
            "end_time"
        )

        status = item.get(
            "status"
        )

        if not all(
            [
                slot_id,
                doctor_id,
                branch_id,
                slot_date,
                start_time,
                end_time,
                status,
            ]
        ):
            continue

        slots.append(
            SlotSnapshot(
                id=slot_id,

                doctor_id=
                    doctor_id,

                branch_id=
                    branch_id,

                slot_date=
                    slot_date,

                start_time=
                    start_time,

                end_time=
                    end_time,

                status=
                    status,
            )
        )

    state.recent_slots = [
        slot
        for slot
        in slots
        if slot.status
        == "available"
    ]

# ============================================================
# PUBLIC UPDATER
# ============================================================

def apply_tool_observation(
    *,
    state: SessionState,
    tool_name: str,
    data,
) -> None:

    if tool_name == (
        "list_specialties"
    ):

        _save_specialties(
            state=state,
            data=data,
        )

        return

    if tool_name == (
        "list_doctors"
    ):

        _save_doctors(
            state=state,
            data=data,
        )

        return

    if tool_name == (
        "list_services"
    ):

        _save_services(
            state=state,
            data=data,
        )

    if tool_name == (
        "list_available_slots"
    ):

        _save_slots(
            state=state,
            data=data,
        )

        return    
