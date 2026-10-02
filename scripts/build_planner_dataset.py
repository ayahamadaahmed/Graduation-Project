from __future__ import annotations

import json
from pathlib import Path

from agent.medmind.understanding.capabilities import (
    CAPABILITY_BY_NAME,
)

from agent.medmind.understanding.tool_planner import (
    PLANNER_INSTRUCTIONS,
)


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_PATH = Path(
    "data/planner/medmind_planner_canonical.jsonl"
)


# ============================================================
# VALID VALUES
# ============================================================

VALID_CONFIRMATIONS = {
    "yes",
    "no",
    "unknown",
}

VALID_AMBIGUITY_KINDS = {
    "needs_clarification",
    "candidate_miss",
}

VALID_CORRECTION_TARGETS = {
    "patient_name",
    "phone",
    "doctor",
    "schedule",
    "time",
    "national_id",
}


# ============================================================
# PLAN BUILDERS
# ============================================================

def selected_plan(
    capability: str,
    arguments: dict[str, str] | None = None,
    *,
    confirmation: str = "unknown",
    correction_target: str | None = None,
) -> dict:

    return {
        "status": "selected",
        "capability": capability,
        "arguments": arguments or {},
        "confirmation": confirmation,
        "ambiguity_kind": None,
        "correction_target": correction_target,
        "reason": "",
    }


def ambiguous_plan(
    ambiguity_kind: str,
    *,
    reason: str,
) -> dict:

    return {
        "status": "ambiguous",
        "capability": None,
        "arguments": {},
        "confirmation": "unknown",
        "ambiguity_kind": ambiguity_kind,
        "correction_target": None,
        "reason": reason,
    }


# ============================================================
# CANONICAL CASES
# ============================================================

CASES = [

    # ========================================================
    # APPOINTMENT.CREATE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "appointment.cancel",
            "provider.search_doctors",
        ],
        "message": "احجزلي",
        "plan": selected_plan(
            "appointment.create",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "provider.search_doctors",
            "provider.get_services",
        ],
        "message": "عايزة احجز كشف جلدية",
        "plan": selected_plan(
            "appointment.create",
            {
                "specialty_name": "جلدية",
                "service_name": "كشف جلدية",
            },
        ),
    },

    {
        "stage": "awaiting_doctor",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.search_doctors",
            "provider.get_slots",
        ],
        "message": "ماهر محمود",
        "plan": selected_plan(
            "appointment.create",
            {
                "doctor_name": "ماهر محمود",
            },
        ),
    },

    {
        "stage": "awaiting_time",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "الساعة ستة",
        "plan": selected_plan(
            "appointment.create",
            {
                "time_text": "الساعة ستة",
            },
        ),
    },

    {
        "stage": "awaiting_patient_name",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
        ],
        "message": "آية أحمد",
        "plan": selected_plan(
            "appointment.create",
            {
                "patient_name": "آية أحمد",
            },
        ),
    },

    # ========================================================
    # PROVIDER.SEARCH_DOCTORS
    # ========================================================

    {
        "stage": "awaiting_specialty",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.search_doctors",
            "provider.get_services",
        ],
        "message": "جلدية",
        "plan": selected_plan(
            "provider.search_doctors",
            {
                "specialty_name": "جلدية",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.search_doctors",
            "provider.get_services",
            "provider.get_slots",
        ],
        "message": "عندكم دكاترة عيون مين",
        "plan": selected_plan(
            "provider.search_doctors",
            {
                "specialty_name": "عيون",
            },
        ),
    },

    # ========================================================
    # PROVIDER.GET_SLOTS
    # ========================================================

    {
        "stage": "awaiting_date",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
            "appointment.search",
        ],
        "message": "بكرة",
        "plan": selected_plan(
            "provider.get_slots",
            {
                "date_text": "بكرة",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_slots",
            "provider.search_doctors",
            "appointment.create",
        ],
        "message": "دكتور ماهر فاضي امتى",
        "plan": selected_plan(
            "provider.get_slots",
            {
                "doctor_name": "ماهر",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_slots",
            "provider.get_working_hours",
        ],
        "message": "في مواعيد جلدية بكرة بالليل",
        "plan": selected_plan(
            "provider.get_slots",
            {
                "specialty_name": "جلدية",
                "date_text": "بكرة",
                "time_text": "بالليل",
            },
        ),
    },

    # ========================================================
    # PROVIDER.GET_SERVICES
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_services",
            "provider.search_doctors",
            "knowledge.search",
        ],
        "message": "كشف الجلدية بكام",
        "plan": selected_plan(
            "provider.get_services",
            {
                "specialty_name": "جلدية",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_services",
            "knowledge.search",
        ],
        "message": "ايه الخدمات اللي عند دكتور ماهر",
        "plan": selected_plan(
            "provider.get_services",
            {
                "doctor_name": "ماهر",
            },
        ),
    },

    # ========================================================
    # APPOINTMENT.CANCEL
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.cancel",
            "appointment.reschedule",
            "appointment.search",
        ],
        "message": "عايز ألغي الحجز",
        "plan": selected_plan(
            "appointment.cancel",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.cancel",
            "appointment.search",
        ],
        "message": "الغي الحجز APT-260831-1234",
        "plan": selected_plan(
            "appointment.cancel",
            {
                "appointment_reference":
                    "APT-260831-1234",
            },
        ),
    },

    # ========================================================
    # APPOINTMENT.RESCHEDULE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.reschedule",
            "appointment.cancel",
            "appointment.search",
        ],
        "message": "عايزة أغير ميعاد الحجز لبكرة",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "date_text": "بكرة",
            },
        ),
    },

    {
        "stage": "awaiting_reschedule_date",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "provider.get_slots",
        ],
        "message": "خليه السبت الساعة خمسة",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "date_text": "السبت",
                "time_text": "الساعة خمسة",
            },
        ),
    },

    # ========================================================
    # APPOINTMENT.SEARCH
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.search",
            "appointment.create",
            "appointment.cancel",
        ],
        "message": "عندي حجز امتى",
        "plan": selected_plan(
            "appointment.search",
        ),
    },

    # ========================================================
    # PROVIDER.GET_POLICY
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_policy",
            "appointment.cancel",
            "knowledge.search",
        ],
        "message": "إيه سياسة إلغاء المواعيد؟",
        "plan": selected_plan(
            "provider.get_policy",
            {
                "query":
                    "إيه سياسة إلغاء المواعيد؟",
            },
        ),
    },

    # ========================================================
    # PROVIDER.GET_WORKING_HOURS
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_working_hours",
            "provider.get_slots",
        ],
        "message": "العيادة بتفتح امتى",
        "plan": selected_plan(
            "provider.get_working_hours",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_working_hours",
            "provider.get_slots",
        ],
        "message": "فرع الدقي فاتح السبت؟",
        "plan": selected_plan(
            "provider.get_working_hours",
            {
                "branch_name": "الدقي",
                "date_text": "السبت",
            },
        ),
    },

    # ========================================================
    # KNOWLEDGE.SEARCH
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "knowledge.search",
            "provider.search_doctors",
        ],
        "message": "دكتور ماهر بيعالج حب الشباب؟",
        "plan": selected_plan(
            "knowledge.search",
            {
                "query":
                    "دكتور ماهر بيعالج حب الشباب؟",
            },
        ),
    },

    # ========================================================
    # HUMAN_SUPPORT.TRANSFER
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "human_support.transfer",
            "knowledge.search",
        ],
        "message": "عايز أكلم حد",
        "plan": selected_plan(
            "human_support.transfer",
        ),
    },

    # ========================================================
    # EGYPTIAN CORRECTIONS
    # ========================================================

    # Replacement value موجود في نفس الرسالة.
    # لذلك correction_target يجب أن يظل None.

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "لا الدكتور منى",
        "plan": selected_plan(
            "appointment.create",
            {
                "doctor_name": "منى",
            },
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message":
            "مش الجمعة خليها السبت الساعة خمسة",
        "plan": selected_plan(
            "appointment.create",
            {
                "date_text": "السبت",
                "time_text": "الساعة خمسة",
            },
        ),
    },

    # ========================================================
    # ARABIZI
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "appointment.cancel",
        ],
        "message": "3ayza a7gz",
        "plan": selected_plan(
            "appointment.create",
        ),
    },

    {
        "stage": "awaiting_date",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "bokra",
        "plan": selected_plan(
            "provider.get_slots",
            {
                "date_text": "bokra",
            },
        ),
    },

    {
        "stage": "awaiting_time",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "el sa3a 6",
        "plan": selected_plan(
            "appointment.create",
            {
                "time_text": "el sa3a 6",
            },
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "la2 el doctor Mona",
        "plan": selected_plan(
            "appointment.create",
            {
                "doctor_name": "Mona",
            },
        ),
    },


    # ========================================================
    # CONFIRMATION
    # ========================================================

    # Pending confirmation + clear yes
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "أيوه كده صح",
        "plan": selected_plan(
            "appointment.create",
            confirmation="yes",
        ),
    },

    # Pending confirmation + clear no
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.cancel",
        "candidates": [
            "appointment.cancel",
            "appointment.reschedule",
        ],
        "message": "لا",
        "plan": selected_plan(
            "appointment.cancel",
            confirmation="no",
        ),
    },

    # ========================================================
    # CORRECTION REQUEST WITHOUT NEW VALUE
    # ========================================================

    # Patient name is wrong, but replacement not supplied.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الاسم غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="patient_name",
        ),
    },

    # Phone is wrong, but replacement not supplied.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "رقم الموبايل غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="phone",
        ),
    },

    # Doctor is wrong, but replacement not supplied.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الدكتور غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="doctor",
        ),
    },

    # Whole schedule/date is wrong.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الميعاد غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="schedule",
        ),
    },

    # Only the time is wrong.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الوقت غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="time",
        ),
    },

    # National ID is wrong.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
        ],
        "message": "الرقم القومي غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="national_id",
        ),
    },

    # ========================================================
    # NEEDS CLARIFICATION
    # ========================================================

    # No context to resolve "the second one".
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "appointment.reschedule",
        ],
        "message": "التاني",
        "plan": ambiguous_plan(
            "needs_clarification",
            reason=(
                "The referenced second option "
                "cannot be resolved from context."
            ),
        ),
    },

    # "Change it" does not identify the operation/object.
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
            "appointment.cancel",
        ],
        "message": "عايز أغيره",
        "plan": ambiguous_plan(
            "needs_clarification",
            reason=(
                "The requested change cannot be "
                "resolved without useful context."
            ),
        ),
    },

    # Mentions booking but does not state a safe operation.
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "human_support.transfer",
        ],
        "message": "ممكن تساعدني في الحجز؟",
        "plan": ambiguous_plan(
            "needs_clarification",
            reason=(
                "The message discusses booking "
                "without specifying the requested operation."
            ),
        ),
    },

    # ========================================================
    # CANDIDATE MISS
    # ========================================================

    # Cancellation intent is clear,
    # but appointment.cancel was not retrieved.
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "provider.get_policy",
        ],
        "message": "عايز ألغي الحجز",
        "plan": ambiguous_plan(
            "candidate_miss",
            reason=(
                "Cancellation is clear but "
                "appointment.cancel is not a candidate."
            ),
        ),
    },

    # Human support intent is clear,
    # but human_support.transfer is absent.
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "knowledge.search",
            "provider.get_policy",
            "appointment.search",
        ],
        "message": "عايز أكلم موظف",
        "plan": ambiguous_plan(
            "candidate_miss",
            reason=(
                "Human support is clearly requested "
                "but its capability is not a candidate."
            ),
        ),
    },

    # ========================================================
    # OPERATION SWITCHING
    # ========================================================

    # Cancel was active, but user explicitly switches
    # to rescheduling the existing appointment.
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.cancel",
        "candidates": [
            "appointment.cancel",
            "appointment.reschedule",
        ],
        "message": "لا متلغهوش، غيره للسبت",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "date_text": "السبت",
            },
        ),
    },

    # A booking operation is in progress,
    # but the user explicitly switches to appointment search.
    {
        "stage": "awaiting_doctor",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.search",
            "provider.search_doctors",
        ],
        "message": "سيب الحجز ده، عايز أعرف حجوزاتي",
        "plan": selected_plan(
            "appointment.search",
        ),
    },



        # ========================================================
    # MORE APPOINTMENT.CANCEL COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.cancel",
            "appointment.reschedule",
            "appointment.search",
        ],
        "message": "مش عايز الحجز ده خلاص الغيه",
        "plan": selected_plan(
            "appointment.cancel",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.cancel",
            "appointment.search",
        ],
        "message": "عايز ألغي APT-260901-5678",
        "plan": selected_plan(
            "appointment.cancel",
            {
                "appointment_reference":
                    "APT-260901-5678",
            },
        ),
    },

    # Synthetic national ID only.
    # Never put real patient data in the training dataset.
    {
        "stage": "awaiting_cancel_identity",
        "active": "appointment.cancel",
        "candidates": [
            "appointment.cancel",
            "appointment.search",
        ],
        "message": "29801011234567",
        "plan": selected_plan(
            "appointment.cancel",
            {
                "national_id":
                    "29801011234567",
            },
        ),
    },

    # Explicit switch:
    # reschedule -> cancel
    {
        "stage": "awaiting_confirmation",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "appointment.cancel",
        ],
        "message": "لا خلاص متغيروش، الغيه",
        "plan": selected_plan(
            "appointment.cancel",
        ),
    },

    # ========================================================
    # MORE APPOINTMENT.RESCHEDULE COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.reschedule",
            "appointment.cancel",
            "appointment.search",
        ],
        "message":
            "غير الحجز لبكرة الساعة ستة",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "date_text": "بكرة",
                "time_text": "الساعة ستة",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.reschedule",
            "appointment.search",
        ],
        "message":
            "غير ميعاد APT-260901-8765 للسبت",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "appointment_reference":
                    "APT-260901-8765",
                "date_text":
                    "السبت",
            },
        ),
    },

    # Synthetic national ID only.
    {
        "stage": "awaiting_reschedule_identity",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "appointment.search",
        ],
        "message": "29902021234567",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "national_id":
                    "29902021234567",
            },
        ),
    },

    {
        "stage": "awaiting_reschedule_date",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "provider.search_doctors",
            "provider.get_slots",
        ],
        "message":
            "وخليه مع دكتورة منى",
        "plan": selected_plan(
            "appointment.reschedule",
            {
                "doctor_name":
                    "دكتورة منى",
            },
        ),
    },

    # ========================================================
    # MORE APPOINTMENT.SEARCH COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.search",
            "appointment.create",
            "appointment.cancel",
        ],
        "message": "عايز أعرف حجوزاتي",
        "plan": selected_plan(
            "appointment.search",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.search",
            "provider.get_slots",
            "appointment.create",
        ],
        "message": "الحجز بتاعي امتى",
        "plan": selected_plan(
            "appointment.search",
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.search",
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "وريني مواعيدي",
        "plan": selected_plan(
            "appointment.search",
        ),
    },

    # ========================================================
    # MORE PROVIDER.GET_POLICY COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_policy",
            "appointment.reschedule",
            "knowledge.search",
        ],
        "message":
            "إيه شروط تغيير ميعاد الحجز؟",
        "plan": selected_plan(
            "provider.get_policy",
            {
                "query":
                    "إيه شروط تغيير ميعاد الحجز؟",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_policy",
            "knowledge.search",
            "provider.get_working_hours",
        ],
        "message":
            "لو اتأخرت على الكشف بيحصل إيه؟",
        "plan": selected_plan(
            "provider.get_policy",
            {
                "query":
                    "لو اتأخرت على الكشف بيحصل إيه؟",
            },
        ),
    },

    # ========================================================
    # MORE KNOWLEDGE.SEARCH COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "knowledge.search",
            "provider.search_doctors",
            "provider.get_services",
        ],
        "message":
            "دكتورة منى متخصصة في إيه؟",
        "plan": selected_plan(
            "knowledge.search",
            {
                "query":
                    "دكتورة منى متخصصة في إيه؟",
            },
        ),
    },

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "knowledge.search",
            "provider.get_services",
        ],
        "message":
            "عندكم معلومات عن علاج التصبغات؟",
        "plan": selected_plan(
            "knowledge.search",
            {
                "query":
                    "عندكم معلومات عن علاج التصبغات؟",
            },
        ),
    },

    # ========================================================
    # MORE HUMAN SUPPORT COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "human_support.transfer",
            "knowledge.search",
            "provider.get_policy",
        ],
        "message":
            "محتاج أكلم خدمة العملاء",
        "plan": selected_plan(
            "human_support.transfer",
        ),
    },

    # ========================================================
    # MORE PROVIDER.SEARCH_DOCTORS COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.search_doctors",
            "provider.get_slots",
            "provider.get_services",
        ],
        "message":
            "مين دكاترة القلب عندكم",
        "plan": selected_plan(
            "provider.search_doctors",
            {
                "specialty_name":
                    "القلب",
            },
        ),
    },

    # ========================================================
    # MORE PROVIDER.GET_SERVICES COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_services",
            "knowledge.search",
            "provider.get_slots",
        ],
        "message":
            "خدمات دكتورة منى ايه",
        "plan": selected_plan(
            "provider.get_services",
            {
                "doctor_name":
                    "دكتورة منى",
            },
        ),
    },

    # ========================================================
    # MORE PROVIDER.GET_WORKING_HOURS COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_working_hours",
            "provider.get_slots",
        ],
        "message":
            "فرع مدينة نصر شغال بكرة؟",
        "plan": selected_plan(
            "provider.get_working_hours",
            {
                "branch_name":
                    "مدينة نصر",
                "date_text":
                    "بكرة",
            },
        ),
    },

    # ========================================================
    # MORE PROVIDER.GET_SLOTS COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "provider.get_slots",
            "provider.get_working_hours",
            "appointment.create",
        ],
        "message":
            "في ميعاد مع دكتورة منى الجمعة بعد الضهر؟",
        "plan": selected_plan(
            "provider.get_slots",
            {
                "doctor_name":
                    "دكتورة منى",
                "date_text":
                    "الجمعة",
                "time_text":
                    "بعد الضهر",
            },
        ),
    },


        # ========================================================
    # EXTRA CONFIRMATION COVERAGE
    # ========================================================

    # --------------------------------------------------------
    # Confirmation YES - reschedule
    # --------------------------------------------------------

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "appointment.cancel",
        ],
        "message": "أيوه تمام غيره",
        "plan": selected_plan(
            "appointment.reschedule",
            confirmation="yes",
        ),
    },

    # --------------------------------------------------------
    # Confirmation YES - cancel
    # --------------------------------------------------------

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.cancel",
        "candidates": [
            "appointment.cancel",
            "appointment.reschedule",
        ],
        "message": "أيوه الغيه",
        "plan": selected_plan(
            "appointment.cancel",
            confirmation="yes",
        ),
    },

    # --------------------------------------------------------
    # Confirmation NO - create
    # --------------------------------------------------------

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "لا مش صح",
        "plan": selected_plan(
            "appointment.create",
            confirmation="no",
        ),
    },

    # --------------------------------------------------------
    # Confirmation NO - reschedule
    # --------------------------------------------------------

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.reschedule",
        "candidates": [
            "appointment.reschedule",
            "appointment.cancel",
        ],
        "message": "لأ مش موافق",
        "plan": selected_plan(
            "appointment.reschedule",
            confirmation="no",
        ),
    },

    # ========================================================
    # EXTRA PATIENT NAME CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "اسم المريض مش مظبوط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="patient_name",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الاسم اللي اتقال في التأكيد غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="patient_name",
        ),
    },

    # ========================================================
    # EXTRA PHONE CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "رقم التليفون محتاج يتعدل",
        "plan": selected_plan(
            "appointment.create",
            correction_target="phone",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "الموبايل اللي سجلته مش صح",
        "plan": selected_plan(
            "appointment.create",
            correction_target="phone",
        ),
    },

    # ========================================================
    # EXTRA DOCTOR CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "مش الدكتور ده",
        "plan": selected_plan(
            "appointment.create",
            correction_target="doctor",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.search_doctors",
        ],
        "message": "الدكتور اللي في الحجز محتاج يتغير",
        "plan": selected_plan(
            "appointment.create",
            correction_target="doctor",
        ),
    },

    # ========================================================
    # EXTRA SCHEDULE CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "اليوم اللي اتأكد غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="schedule",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "appointment.reschedule",
        ],
        "message": "عايزة أعدل الميعاد",
        "plan": selected_plan(
            "appointment.create",
            correction_target="schedule",
        ),
    },

    # ========================================================
    # EXTRA TIME CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "الساعة مش صح",
        "plan": selected_plan(
            "appointment.create",
            correction_target="time",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
            "provider.get_slots",
        ],
        "message": "الوقت اللي قولته غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="time",
        ),
    },

    # ========================================================
    # EXTRA NATIONAL ID CORRECTION COVERAGE
    # ========================================================

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
        ],
        "message": "الرقم القومي اللي سجلته غلط",
        "plan": selected_plan(
            "appointment.create",
            correction_target="national_id",
        ),
    },

    {
        "stage": "awaiting_confirmation",
        "active": "appointment.create",
        "candidates": [
            "appointment.create",
        ],
        "message": "محتاج أصحح الرقم القومي",
        "plan": selected_plan(
            "appointment.create",
            correction_target="national_id",
        ),
    },

        # ========================================================
    # EXTRA HUMAN SUPPORT COVERAGE
    # ========================================================

    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "human_support.transfer",
            "knowledge.search",
            "provider.get_policy",
        ],
        "message": "ممكن تحولني لموظف؟",
        "plan": selected_plan(
            "human_support.transfer",
        ),
    },

    # ========================================================
    # EXTRA CANDIDATE MISS COVERAGE
    # ========================================================

    # Reschedule intent is clear,
    # but appointment.reschedule was not retrieved.
    {
        "stage": "new",
        "active": "none",
        "candidates": [
            "appointment.cancel",
            "appointment.search",
            "provider.get_slots",
        ],
        "message": "عايز أغير ميعاد الحجز للاتنين",
        "plan": ambiguous_plan(
            "candidate_miss",
            reason=(
                "Rescheduling is clearly requested "
                "but appointment.reschedule "
                "is not a candidate."
            ),
        ),
    },
]


# ============================================================
# VALIDATION
# ============================================================

def validate_case(
    case: dict,
) -> None:

    # --------------------------------------------------------
    # BASIC CASE STRUCTURE
    # --------------------------------------------------------

    required_case_fields = {
        "stage",
        "active",
        "candidates",
        "message",
        "plan",
    }

    missing_case_fields = (
        required_case_fields
        - set(case.keys())
    )

    if missing_case_fields:
        raise ValueError(
            "Missing case fields: "
            f"{sorted(missing_case_fields)}"
        )

    # --------------------------------------------------------
    # VALIDATE CANDIDATES
    # --------------------------------------------------------

    if not case["candidates"]:
        raise ValueError(
            "Candidate list cannot be empty."
        )

    for candidate_name in case["candidates"]:

        if candidate_name not in CAPABILITY_BY_NAME:
            raise ValueError(
                "Unknown candidate capability: "
                f"{candidate_name}"
            )

    output = case["plan"]

    # --------------------------------------------------------
    # VALIDATE SHARED OUTPUT FIELDS
    # --------------------------------------------------------

    status = output.get(
        "status"
    )

    confirmation = output.get(
        "confirmation"
    )

    correction_target = output.get(
        "correction_target"
    )

    if confirmation not in VALID_CONFIRMATIONS:
        raise ValueError(
            "Invalid confirmation value: "
            f"{confirmation}"
        )

    if (
        correction_target is not None
        and correction_target
        not in VALID_CORRECTION_TARGETS
    ):
        raise ValueError(
            "Invalid correction_target: "
            f"{correction_target}"
        )

    # ========================================================
    # AMBIGUOUS
    # ========================================================

    if status == "ambiguous":

        if output.get(
            "capability"
        ) is not None:
            raise ValueError(
                "Ambiguous plan must have "
                "capability=None."
            )

        if output.get(
            "arguments"
        ):
            raise ValueError(
                "Ambiguous plan must have "
                "empty arguments."
            )

        ambiguity_kind = output.get(
            "ambiguity_kind"
        )

        if (
            ambiguity_kind
            not in VALID_AMBIGUITY_KINDS
        ):
            raise ValueError(
                "Invalid ambiguity_kind: "
                f"{ambiguity_kind}"
            )

        if correction_target is not None:
            raise ValueError(
                "Ambiguous plan cannot have "
                "correction_target."
            )

        return

    # ========================================================
    # SELECTED
    # ========================================================

    if status != "selected":
        raise ValueError(
            "Unknown plan status: "
            f"{status}"
        )

    capability_name = output.get(
        "capability"
    )

    if capability_name is None:
        raise ValueError(
            "Selected plan must have "
            "a capability."
        )

    capability = CAPABILITY_BY_NAME.get(
        capability_name
    )

    if capability is None:
        raise ValueError(
            "Unknown capability: "
            f"{capability_name}"
        )

    # --------------------------------------------------------
    # SELECTED CAPABILITY MUST BE A CANDIDATE
    # --------------------------------------------------------

    candidate_names = set(
        case["candidates"]
    )

    if capability_name not in candidate_names:
        raise ValueError(
            f"{capability_name} not present "
            f"in candidate set for message: "
            f"{case['message']}"
        )

    # --------------------------------------------------------
    # SELECTED RESULT CANNOT HAVE AMBIGUITY KIND
    # --------------------------------------------------------

    if output.get(
        "ambiguity_kind"
    ) is not None:
        raise ValueError(
            "Selected plan must have "
            "ambiguity_kind=None."
        )

    # --------------------------------------------------------
    # ARGUMENT SCHEMA
    # --------------------------------------------------------

    allowed_arguments = set(
        capability.arguments.keys()
    )

    arguments = output.get(
        "arguments",
        {},
    )

    if not isinstance(
        arguments,
        dict,
    ):
        raise ValueError(
            "Plan arguments must be a dict."
        )

    supplied_arguments = set(
        arguments.keys()
    )

    invalid_arguments = (
        supplied_arguments
        - allowed_arguments
    )

    if invalid_arguments:
        raise ValueError(
            f"Invalid arguments for "
            f"{capability_name}: "
            f"{sorted(invalid_arguments)}"
        )

    # --------------------------------------------------------
    # ARGUMENT VALUES MUST BE NON-EMPTY STRINGS
    # --------------------------------------------------------

    for key, value in arguments.items():

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise ValueError(
                "Argument values must be "
                "non-empty strings. "
                f"Invalid: {key}"
            )


# ============================================================
# PRODUCTION-SHAPED CANDIDATE TEXT
# ============================================================

def build_candidate_text(
    candidate_names: list[str],
) -> str:

    blocks: list[str] = []

    for name in candidate_names:

        capability = CAPABILITY_BY_NAME[
            name
        ]

        arguments = (
            ", ".join(
                capability.arguments.keys()
            )
            if capability.arguments
            else "none"
        )

        # ----------------------------------------------------
        # Keep score constant in canonical examples.
        #
        # We do NOT want the model to learn:
        #
        # highest retrieval_score == correct answer.
        #
        # Later augmentation can intentionally vary scores.
        # ----------------------------------------------------

        score = 0.80

        blocks.append(
            "\n".join(
                [
                    (
                        f"name: "
                        f"{capability.name}"
                    ),
                    (
                        f"domain: "
                        f"{capability.domain}"
                    ),
                    (
                        "description_ar: "
                        f"{capability.description_ar}"
                    ),
                    (
                        "description_en: "
                        f"{capability.description_en}"
                    ),
                    (
                        "allowed_arguments: "
                        f"{arguments}"
                    ),
                    (
                        "retrieval_score: "
                        f"{score:.4f}"
                    ),
                ]
            )
        )

    return "\n\n---\n\n".join(
        blocks
    )


# ============================================================
# BUILD PRODUCTION-SHAPED TRAINING ROW
# ============================================================

def make_row(
    case: dict,
    *,
    scenario_id: str,
) -> dict:

    # --------------------------------------------------------
    # CURRENT CONTEXT
    # --------------------------------------------------------

    context = {
        "stage": case["stage"],
        "active_capability": (
            None
            if case["active"] == "none"
            else case["active"]
        ),
    }

    context_text = json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # --------------------------------------------------------
    # CANDIDATES
    # --------------------------------------------------------

    candidate_text = (
        build_candidate_text(
            case["candidates"]
        )
    )

    # --------------------------------------------------------
    # MATCH PRODUCTION TOOL PLANNER PROMPT SHAPE
    # --------------------------------------------------------

    planner_prompt = f"""
{PLANNER_INSTRUCTIONS}


CURRENT CONTEXT

{context_text}


CANDIDATE CAPABILITIES

{candidate_text}


CURRENT USER MESSAGE

{case["message"]}
""".strip()

    # --------------------------------------------------------
    # TRAINING ROW
    # --------------------------------------------------------

    return {
        "scenario_id": scenario_id,
        "messages": [
            {
                "role": "user",
                "content": planner_prompt,
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    case["plan"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }

# ============================================================
# MAIN
# ============================================================

def main() -> None:

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows: list[dict] = []

    # --------------------------------------------------------
    # VALIDATE + BUILD
    # --------------------------------------------------------

    for index, case in enumerate(
        CASES,
        start=1,
    ):

        try:
            validate_case(
                case
            )

        except Exception as exc:

            raise ValueError(
                f"Invalid case #{index}: "
                f"{case.get('message')!r}"
            ) from exc

        scenario_id = (
            f"medmind-planner-{index:03d}"
        )

        rows.append(
            make_row(
                case,
                scenario_id=scenario_id,
            )
        )

    # --------------------------------------------------------
    # WRITE JSONL
    # --------------------------------------------------------

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        for row in rows:

            file.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print(
        f"generated_rows={len(rows)}"
    )

    print(
        f"output={OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()