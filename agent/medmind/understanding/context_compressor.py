from __future__ import annotations

from typing import Any


# ============================================================
# STAGE-SPECIFIC CONTEXT
# ============================================================

SPECIALTY_STAGES = {
    "awaiting_specialty",
}

DOCTOR_STAGES = {
    "awaiting_doctor",
}

SERVICE_STAGES = {
    "awaiting_service",
}

SLOT_STAGES = {
    "awaiting_time",
    "awaiting_reschedule_time",
}


# ============================================================
# CONTEXT COMPRESSION
# ============================================================

def compress_understanding_context(
    context: dict[str, Any] | None,
) -> dict[str, Any]:

    if not context:
        return {}

    compressed: dict[str, Any] = {}

    # --------------------------------------------------------
    # Always useful for understanding the current turn.
    # --------------------------------------------------------

    for key in (
        "language",
        "stage",
        "active_capability",
        "pending_confirmation",
    ):

        value = context.get(key)

        if value is not None:
            compressed[key] = value

    # --------------------------------------------------------
    # Previously collected human-readable values.
    #
    # Keep only the compact representation already built
    # by MedMindService.
    # --------------------------------------------------------

    collected_arguments = context.get(
        "collected_arguments"
    )

    if collected_arguments:
        compressed[
            "collected_arguments"
        ] = collected_arguments

    # --------------------------------------------------------
    # Stage-aware offered options.
    #
    # Only send lists that can help interpret replies such as:
    # "الأول"
    # "التانية"
    # "آخر ميعاد"
    # --------------------------------------------------------

    stage = context.get(
        "stage"
    )

    if stage in SPECIALTY_STAGES:

        offered_specialties = context.get(
            "offered_specialties"
        )

        if offered_specialties:
            compressed[
                "offered_specialties"
            ] = offered_specialties

    if stage in DOCTOR_STAGES:

        offered_doctors = context.get(
            "offered_doctors"
        )

        if offered_doctors:
            compressed[
                "offered_doctors"
            ] = offered_doctors

    if stage in SERVICE_STAGES:

        offered_services = context.get(
            "offered_services"
        )

        if offered_services:
            compressed[
                "offered_services"
            ] = offered_services

    if stage in SLOT_STAGES:

        offered_slots = context.get(
            "offered_slots"
        )

        if offered_slots:
            compressed[
                "offered_slots"
            ] = offered_slots

    return compressed