from types import SimpleNamespace

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


def test_qwen_prompt_uses_compressed_context():

    # We do not need a real Groq client here.
    # _build_prompt() only builds local text.
    planner = object.__new__(
        QwenToolPlanner
    )

    candidates = [
        SimpleNamespace(
            name="appointment.create",
            score=0.95,
            matched_text="appointment booking",
        )
    ]

    context = {
        "language": "ar",
        "stage": "awaiting_time",
        "active_capability": "appointment.create",
        "pending_confirmation": False,

        # Internal values that must NOT reach Qwen.
        "doctor_id": "doc-123",
        "service_id": "service-456",
        "slot_id": "slot-789",

        "recent_slots": [
            {
                "id": "slot-789",
                "doctor_id": "doc-123",
                "branch_id": "branch-1",
                "start_time": "17:00:00",
            }
        ],

        # Compact useful values.
        "collected_arguments": {
            "specialty_name": "جلدية",
            "doctor_name": "دكتورة منى",
            "date_text": "2026-09-10",
        },

        "offered_slots": [
            "17:00",
            "17:30",
        ],

        # Irrelevant for awaiting_time.
        "offered_doctors": [
            "دكتورة منى",
        ],
    }

    prompt = planner._build_prompt(
        message="التانية",
        candidates=candidates,
        context=context,
    )

    # --------------------------------------------------------
    # Important compact context remains.
    # --------------------------------------------------------

    assert '"stage": "awaiting_time"' in prompt

    assert (
        '"active_capability": '
        '"appointment.create"'
        in prompt
    )

    assert '"offered_slots"' in prompt
    assert "17:00" in prompt
    assert "17:30" in prompt

    assert '"collected_arguments"' in prompt
    assert "جلدية" in prompt
    assert "دكتورة منى" in prompt

    # --------------------------------------------------------
    # Internal / duplicate state must not reach Qwen.
    # --------------------------------------------------------

    assert '"doctor_id"' not in prompt
    assert '"service_id"' not in prompt
    assert '"slot_id"' not in prompt

    assert '"recent_slots"' not in prompt

    assert "doc-123" not in prompt
    assert "service-456" not in prompt
    assert "slot-789" not in prompt
    assert "branch-1" not in prompt

    # awaiting_time should not carry doctor choices.
    assert '"offered_doctors"' not in prompt