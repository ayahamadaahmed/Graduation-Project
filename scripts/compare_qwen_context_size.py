from __future__ import annotations

import json

import agent.medmind.understanding.qwen_tool_planner as qwen_module

from agent.medmind.state.models import (
    SessionState,
)

from agent.medmind.service import (
    MedMindService,
)

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)


def main() -> None:

    message = "جلدية"

    state = SessionState(
        channel="web",
        session_id="context-size-test",
        tenant_id="clinic-001",
        language="ar",
        operation_type="book_appointment",
        stage="awaiting_specialty",
    )

    context = (
        MedMindService
        ._build_understanding_context(
            state
        )
    )

    router = SemanticCapabilityRouter()

    candidates = select_capability_candidates(
        router=router,
        message=message,
        context=context,
        top_k=8,
    )

    planner = object.__new__(
        QwenToolPlanner
    )

    # ========================================================
    # CURRENT COMPRESSED PROMPT
    # ========================================================

    compressed_prompt = (
        planner._build_prompt(
            message=message,
            candidates=candidates,
            context=context,
        )
    )

    # ========================================================
    # LEGACY / FULL CONTEXT PROMPT
    #
    # Temporarily disable compression only while building text.
    # No API request is made.
    # ========================================================

    original_compressor = (
        qwen_module
        .compress_understanding_context
    )

    try:

        qwen_module.compress_understanding_context = (
            lambda value: value or {}
        )

        full_prompt = (
            planner._build_prompt(
                message=message,
                candidates=candidates,
                context=context,
            )
        )

    finally:

        qwen_module.compress_understanding_context = (
            original_compressor
        )

    print()
    print("=" * 60)
    print("QWEN CONTEXT SIZE A/B")
    print("=" * 60)

    print(
        "Full context JSON chars:",
        len(
            json.dumps(
                context,
                ensure_ascii=False,
                default=str,
            )
        ),
    )

    compressed_context = (
        original_compressor(
            context
        )
    )

    print(
        "Compressed context JSON chars:",
        len(
            json.dumps(
                compressed_context,
                ensure_ascii=False,
                default=str,
            )
        ),
    )

    print()

    print(
        "Full prompt chars:",
        len(full_prompt),
    )

    print(
        "Compressed prompt chars:",
        len(compressed_prompt),
    )

    reduction = (
        1
        - (
            len(compressed_prompt)
            / len(full_prompt)
        )
    ) * 100

    print(
        "Prompt character reduction:",
        f"{reduction:.2f}%",
    )

    print()

    print(
        "Compressed context:",
        json.dumps(
            compressed_context,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
    )

    candidate_text = (
        planner._build_candidate_text(
            candidates
        )
    )

    instructions_text = (
        qwen_module
        .QWEN_PLANNER_INSTRUCTIONS
    )

    compressed_context_json = (
        json.dumps(
            compressed_context,
            ensure_ascii=False,
            default=str,
        )
    )

    print()
    print("=" * 60)
    print("PROMPT SECTION SIZES")
    print("=" * 60)

    print(
        "Instructions chars:",
        len(instructions_text),
    )

    print(
        "Candidates chars:",
        len(candidate_text),
    )

    print(
        "Compressed context chars:",
        len(compressed_context_json),
    )

    print(
        "User message chars:",
        len(message),
    )


if __name__ == "__main__":
    main()