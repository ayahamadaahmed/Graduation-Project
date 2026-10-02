from __future__ import annotations

import asyncio
import json
import os

from dotenv import (
    load_dotenv,
)

from langchain_openai import (
    ChatOpenAI,
)

from medmind.language import (
    detect_language,
)

from medmind.memory.models import (
    ChatMessage,
)

from medmind.state.models import (
    SessionState,
)

from medmind.understanding.llm import (
    LLMNLU,
)


# ============================================================
# PRINT
# ============================================================

def print_result(
    title: str,
    result,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        title
    )

    print(
        "=" * 70
    )

    print(
        json.dumps(
            result.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
    )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    load_dotenv(
        override=True
    )

    model_name = os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1",
    )

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=60,
    )

    nlu = LLMNLU(
        model=model
    )

    # ========================================================
    # TEST 1
    # New booking
    # ========================================================

    state = SessionState(
        session_id="nlu-test-001",
        tenant_id="clinic-001",
    )

    message = (
        "عايزة احجز جلدية"
    )

    language = detect_language(
        message
    )

    result = await nlu.understand(
        message=message,
        language=language,
        state=state,
        history=[],
    )

    print_result(
        "TEST 1 - NEW BOOKING",
        result,
    )

    # ========================================================
    # TEST 2
    # Doctor contextual reply
    # ========================================================

    state.operation_type = (
        "book_appointment"
    )

    state.stage = (
        "awaiting_doctor"
    )

    history = [
        ChatMessage(
            role="user",
            content=(
                "عايزة احجز جلدية"
            ),
        ),

        ChatMessage(
            role="assistant",
            content=(
                "متاح د. منى صلاح "
                "ود. عمر خالد، "
                "تحبي تحجزي مع مين؟"
            ),
        ),
    ]

    message = "منى"

    result = await nlu.understand(
        message=message,
        language="ar",
        state=state,
        history=history,
    )

    print_result(
        "TEST 2 - DOCTOR",
        result,
    )

    # ========================================================
    # TEST 3
    # Date contextual reply
    # ========================================================

    state.stage = (
        "awaiting_date"
    )

    history.append(
        ChatMessage(
            role="user",
            content="منى",
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=(
                "تمام، تحبي تحجزي يوم إيه؟"
            ),
        )
    )

    message = "بكرة"

    result = await nlu.understand(
        message=message,
        language="ar",
        state=state,
        history=history,
    )

    print_result(
        "TEST 3 - DATE",
        result,
    )

    # ========================================================
    # TEST 4
    # Time contextual reply
    # ========================================================

    state.stage = (
        "awaiting_time"
    )

    history.append(
        ChatMessage(
            role="user",
            content="بكرة",
        )
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=(
                "تحبي الساعة كام؟"
            ),
        )
    )

    message = "12 ونص"

    result = await nlu.understand(
        message=message,
        language="ar",
        state=state,
        history=history,
    )

    print_result(
        "TEST 4 - TIME",
        result,
    )

    # ========================================================
    # TEST 5
    # Confirmation
    # ========================================================

    state.stage = (
        "awaiting_confirmation"
    )

    state.awaiting_confirmation = (
        True
    )

    history.append(
        ChatMessage(
            role="assistant",
            content=(
                "أأكد الحجز؟"
            ),
        )
    )

    message = "أيوه"

    result = await nlu.understand(
        message=message,
        language="ar",
        state=state,
        history=history,
    )

    print_result(
        "TEST 5 - CONFIRMATION",
        result,
    )

    # ========================================================
    # TEST 6
    # English
    # ========================================================

    english_state = SessionState(
        session_id="nlu-test-en-001",
        tenant_id="clinic-001",
        language="en",
    )

    message = (
        "I want to book a dermatology appointment tomorrow."
    )

    result = await nlu.understand(
        message=message,
        language="en",
        state=english_state,
        history=[],
    )

    print_result(
        "TEST 6 - ENGLISH",
        result,
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )