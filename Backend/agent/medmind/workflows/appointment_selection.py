from __future__ import annotations

import re
import unicodedata
from typing import Any

from medmind.core.tool_executor import (
    MCPToolExecutor,
)
from datetime import date
from medmind.state.models import (
    AppointmentSnapshot,
)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

_ARABIC_DIGITS = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)

def normalize_selection_text(
    value: str | None,
) -> str:

    if not value:
        return ""

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    value = (
        value
        .replace("ـ", "")
        .translate(_ARABIC_DIGITS)
        .lower()
        .strip()
    )

    value = (
        value
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
    )

    value = re.sub(
        r"[^\w\u0600-\u06ff\s]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()

_AR_WEEKDAY_NAMES = (
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)

_EN_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def appointment_day_label(
    scheduled_date: str | None,
    *,
    language: str,
) -> str:

    raw = (
        scheduled_date
        or ""
    ).strip()[:10]

    if not raw:
        return ""

    try:
        parsed = date.fromisoformat(
            raw
        )
    except ValueError:
        # Safe fallback if backend ever returns
        # a non-ISO date representation.
        return raw

    names = (
        _EN_WEEKDAY_NAMES
        if language == "en"
        else _AR_WEEKDAY_NAMES
    )

    return names[
        parsed.weekday()
    ]
# ============================================================
# AFFIRM / DENY
# ============================================================

_AFFIRMATIVE = {
    "ايوه",
    "ايوة",
    "اه",
    "نعم",
    "تمام",
    "ماشي",
    "صح",
    "yes",
    "yeah",
    "yep",
    "correct",
}


_NEGATIVE = {
    "لا",
    "لأ",
    "كلا",
    "مش ده",
    "مش هو",
    "no",
    "nope",
}


def is_affirmative(
    text: str | None,
) -> bool:

    normalized = (
        normalize_selection_text(
            text
        )
    )

    return normalized in _AFFIRMATIVE


def is_negative(
    text: str | None,
) -> bool:

    normalized = (
        normalize_selection_text(
            text
        )
    )

    return normalized in _NEGATIVE


# ============================================================
# MCP RESULT NORMALIZATION
# ============================================================

def _appointment_items_from_result(
    result: Any,
) -> list[dict[str, Any]]:

    if isinstance(
        result,
        list,
    ):

        return [
            item
            for item in result
            if isinstance(
                item,
                dict,
            )
        ]

    if not isinstance(
        result,
        dict,
    ):

        return []

    for key in (
        "appointments",
        "items",
        "results",
        "bookings",
    ):

        items = result.get(
            key
        )

        if isinstance(
            items,
            list,
        ):

            return [
                item
                for item in items
                if isinstance(
                    item,
                    dict,
                )
            ]

    if result.get(
        "appointment_reference"
    ):

        return [
            result
        ]

    return []


def _to_snapshot(
    value: dict[str, Any],
) -> AppointmentSnapshot | None:

    reference = str(
        value.get(
            "appointment_reference"
        )
        or value.get(
            "appointment_code"
        )
        or value.get(
            "booking_code"
        )
        or ""
    ).strip().upper()

    if not reference:
        return None

    return AppointmentSnapshot(
        appointment_reference=
            reference,

        doctor_name=(
            value.get(
                "doctor_name"
            )
            or value.get(
                "doctor_name_ar"
            )
            or value.get(
                "doctor_name_en"
            )
        ),

        service_name=(
            value.get(
                "service_name"
            )
            or value.get(
                "service_name_ar"
            )
            or value.get(
                "service_name_en"
            )
        ),

        specialty_name=(
            value.get(
                "specialty_name"
            )
            or value.get(
                "specialty_name_ar"
            )
            or value.get(
                "specialty_name_en"
            )
        ),

        branch_name=(
            value.get(
                "branch_name"
            )
            or value.get(
                "branch_name_ar"
            )
            or value.get(
                "branch_name_en"
            )
        ),

        scheduled_date=(
            str(
                value.get(
                    "scheduled_date"
                )
                or value.get(
                    "appointment_date"
                )
                or ""
            )
            or None
        ),

        start_time=(
            str(
                value.get(
                    "start_time"
                )
                or value.get(
                    "appointment_time"
                )
                or ""
            )
            or None
        ),

        end_time=(
            str(
                value.get(
                    "end_time"
                )
                or ""
            )
            or None
        ),

        status=(
            str(
                value.get(
                    "status"
                )
                or ""
            )
            or None
        ),
    )


# ============================================================
# SEARCH BOOKINGS
# ============================================================

async def search_patient_appointments(
    *,
    tools: MCPToolExecutor,
    national_id: str,
    action: str,
    limit: int = 10,
) -> list[AppointmentSnapshot]:

    result = await tools.call(
        "search_patient_bookings",

        future_only=(
            action in {
                "cancel",
                "reschedule",
            }
        ),

        national_id=
            national_id,

        include_cancelled=
            False,

        limit=
            limit,
    )

    snapshots: list[
        AppointmentSnapshot
    ] = []

    for item in (
        _appointment_items_from_result(
            result
        )
    ):

        snapshot = (
            _to_snapshot(
                item
            )
        )

        if snapshot is None:
            continue

        status = (
            snapshot.status
            or ""
        ).strip().lower()

        if status == "cancelled":
            continue

        # Only confirmed bookings
        # should be rescheduled.
        if (
            action == "reschedule"
            and status
            and status != "confirmed"
        ):
            continue

        snapshots.append(
            snapshot
        )

        if len(
            snapshots
        ) >= limit:
            break

    return snapshots


# ============================================================
# VOICE DESCRIPTION
# ============================================================

def describe_appointment(
    appointment: AppointmentSnapshot,
    *,
    language: str,
) -> str:

    time_text = (
        appointment.start_time
        or ""
    )[:5]

    if language == "en":

        parts = []

        if appointment.doctor_name:
            parts.append(
                f"with {appointment.doctor_name}"
            )

        if appointment.service_name:
            parts.append(
                f"for {appointment.service_name}"
            )

        if appointment.scheduled_date:
            parts.append(
                f"on {appointment.scheduled_date}"
            )

        if time_text:
            parts.append(
                f"at {time_text}"
            )

        return " ".join(
            parts
        )

    parts = []

    if appointment.doctor_name:
        parts.append(
            f"مع {appointment.doctor_name}"
        )

    if appointment.service_name:
        parts.append(
            f"خدمة {appointment.service_name}"
        )

    if appointment.scheduled_date:
        parts.append(
            f"يوم {appointment.scheduled_date}"
        )

    if time_text:
        parts.append(
            f"الساعة {time_text}"
        )

    return "، ".join(
        parts
    )


def build_selection_prompt(
    appointments: list[AppointmentSnapshot],
    *,
    language: str,
    action: str,
) -> str:

    candidates = (
        appointments[:5]
    )

    if not candidates:
        return ""

    # ========================================================
    # One booking
    # ========================================================

    if len(
        candidates
    ) == 1:

        description = (
            describe_appointment(
                candidates[0],
                language=language,
            )
        )

        if language == "en":

            action_text = (
                "reschedule"
                if action
                == "reschedule"
                else "cancel"
            )

            return (
                "I found one appointment "
                f"{description}. "
                "Is this the appointment "
                f"you want to {action_text}?"
            )

        action_text = (
            "تغيّر ميعاده"
            if action
            == "reschedule"
            else "تلغيه"
        )

        return (
            "لقيت حجز واحد "
            f"{description}. "
            "هو ده الحجز اللي عايز "
            f"{action_text}؟"
        )

        # ========================================================
    # Multiple bookings
    #
    # Voice-friendly grouped summary:
    # - doctor is spoken once
    # - different dates are summarized by weekday
    # - times are spoken only when multiple bookings share
    #   the same date
    # ========================================================

    def join_labels(
        values: list[str],
    ) -> str:

        if not values:
            return ""

        if len(values) == 1:
            return values[0]

        if language == "en":

            if len(values) == 2:
                return (
                    f"{values[0]} and "
                    f"{values[1]}"
                )

            return (
                ", ".join(values[:-1])
                + f", and {values[-1]}"
            )

        if len(values) == 2:
            return (
                f"{values[0]}، و"
                f"{values[1]}"
            )

        return (
            "، ".join(values[:-1])
            + f"، و{values[-1]}"
        )

    # doctor -> date -> appointments
    grouped: dict[
        str,
        dict[
            str,
            list[AppointmentSnapshot],
        ],
    ] = {}

    for appointment in candidates:

        scheduled_date = (
            appointment.scheduled_date
            or ""
        ).strip()[:10]

        # A booking without a date cannot be summarized
        # safely by weekday. Fall back to the existing
        # detailed representation.
        if not scheduled_date:

            lines = [
                describe_appointment(
                    item,
                    language=language,
                )
                for item in candidates
            ]

            if language == "en":
                return (
                    "I found more than one appointment. "
                    + ". ".join(lines)
                    + ". Which appointment do you mean?"
                )

            return (
                "لقيت أكتر من حجز. "
                + ". ".join(lines)
                + ". أنهي حجز تقصد؟"
            )

        doctor_name = (
            appointment.doctor_name
            or ""
        ).strip()

        doctor_dates = grouped.setdefault(
            doctor_name,
            {},
        )

        doctor_dates.setdefault(
            scheduled_date,
            [],
        ).append(
            appointment
        )

    doctor_segments: list[str] = []

    for (
        doctor_name,
        date_groups,
    ) in grouped.items():

        date_labels: list[str] = []

        for (
            scheduled_date,
            date_appointments,
        ) in date_groups.items():

            day_label = appointment_day_label(
                scheduled_date,
                language=language,
            )

            # More than one booking on the same day:
            # times are necessary to distinguish them.
            if len(date_appointments) > 1:

                times: list[str] = []

                for appointment in date_appointments:

                    time_text = (
                        appointment.start_time
                        or ""
                    )[:5]

                    if (
                        time_text
                        and time_text not in times
                    ):
                        times.append(
                            time_text
                        )

                if times:

                    if language == "en":
                        day_label = (
                            f"{day_label} at "
                            f"{join_labels(times)}"
                        )
                    else:
                        day_label = (
                            f"{day_label} الساعة "
                            f"{join_labels(times)}"
                        )

            date_labels.append(
                day_label
            )

        dates_text = join_labels(
            date_labels
        )

        if doctor_name:

            if language == "en":
                doctor_segments.append(
                    f"with {doctor_name}: "
                    f"{dates_text}"
                )
            else:
                doctor_segments.append(
                    f"مع {doctor_name}: "
                    f"{dates_text}"
                )

        else:

            doctor_segments.append(
                dates_text
            )

    summary = join_labels(
        doctor_segments
    )

    if language == "en":

        question = (
            "Which appointment would you like "
            "to reschedule?"
            if action == "reschedule"
            else
            "Which appointment would you like "
            "to cancel?"
        )

        return (
            f"You have appointments {summary}. "
            f"{question}"
        )

    question = (
        "تحب تغيّر ميعاد أنهي حجز؟"
        if action == "reschedule"
        else
        "تحب تلغي أنهي حجز؟"
    )

    return (
        f"عندك حجوزات {summary}. "
        f"{question}"
    )

def resolve_appointment_selection(
    text: str | None,
    appointments: list[AppointmentSnapshot],
) -> int | None:

    if not appointments:
        return None

    normalized = (
        normalize_selection_text(
            text
        )
    )

    if not normalized:
        return None

    # One booking + yes
    if (
        len(
            appointments
        ) == 1
        and is_affirmative(
            normalized
        )
    ):
        return 0

    # first / second / الأول / التاني
    tokens = (
        normalized.split()
    )

    for token in tokens:

        index = (
            _SELECTION_WORDS.get(
                token
            )
        )

        if (
            index is not None
            and index
            < len(
                appointments
            )
        ):
            return index

    # ========================================================
    # Natural phrase:
    # "حجز الجلدية"
    # "بتاع دكتور ماهر"
    # ========================================================

    matches = []

    for index, appointment in enumerate(
        appointments
    ):

        searchable_values = [
            appointment.doctor_name,
            appointment.service_name,
            appointment.specialty_name,
            appointment.branch_name,
        ]

        matched = False

        for value in searchable_values:

            candidate = (
                normalize_selection_text(
                    value
                )
            )

            if not candidate:
                continue

            candidate_tokens = [
                token
                for token in (
                    candidate.split()
                )
                if len(token) >= 3
            ]

            if (
                candidate in normalized
                or normalized in candidate
                or any(
                    token
                    in normalized.split()
                    for token
                    in candidate_tokens
                )
            ):

                matched = True
                break

        if matched:

            matches.append(
                index
            )

    if len(
        matches
    ) == 1:

        return matches[0]

    return None