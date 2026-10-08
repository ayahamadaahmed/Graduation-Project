from __future__ import annotations

import asyncio
import os
import time

from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.candidate_selector import (
    select_capability_candidates,
)

from medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from medmind.understanding.planner_policy import (
    choose_planner_provider,
)

from medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)


TOP_K = 8


# ============================================================
# COUNTING WRAPPER
#
# Lets us prove whether Qwen/GPT was actually called.
# ============================================================

class CountingPlanner:

    def __init__(
        self,
        planner,
    ) -> None:
        self.planner = planner
        self.calls = 0

    async def plan(
        self,
        **kwargs,
    ):
        self.calls += 1

        return await self.planner.plan(
            **kwargs
        )

    def reset(
        self,
    ) -> None:
        self.calls = 0


# ============================================================
# CASE
# ============================================================

@dataclass
class Case:
    name: str
    message: str
    expected_provider: str
    expected_capability: str

    context: dict[str, Any] = field(
        default_factory=dict
    )


CASES = [

    # --------------------------------------------------------
    # SIMPLE -> QWEN
    # --------------------------------------------------------

    Case(
        name="simple_booking",
        message="عايز أحجز جلدية بكرة",
        expected_provider="qwen",
        expected_capability="appointment.create",
    ),

    Case(
        name="simple_slots",
        message="في مواعيد بكرة؟",
        expected_provider="qwen",
        expected_capability="provider.get_slots",
    ),

    Case(
        name="contextual_correction",
        message="لا خليه الاتنين",
        expected_provider="qwen",
        expected_capability="appointment.reschedule",
        context={
            "active_capability": (
                "appointment.reschedule"
            ),
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
            "collected_arguments": {
                "date_text": "الأحد",
                "time_text": "الساعة ستة",
            },
        },
    ),

    # --------------------------------------------------------
    # COMPLEX -> GPT DIRECT
    # --------------------------------------------------------

    Case(
        name="operation_switch",
        message="لا متلغهوش، غيره للسبت",
        expected_provider="gpt",
        expected_capability="appointment.reschedule",
        context={
            "active_capability": (
                "appointment.cancel"
            ),
            "stage": "awaiting_confirmation",
            "pending_confirmation": True,
        },
    ),

    Case(
        name="multiple_conditions",
        message=(
            "لو مفيش بكرة شوفلي بعده "
            "بس يكون بعد الساعة خمسة"
        ),
        expected_provider="gpt",
        expected_capability="appointment.create",
        context={
            "active_capability": (
                "appointment.create"
            ),
            "stage": "awaiting_date",
        },
    ),

    Case(
        name="search_then_reschedule",
        message=(
            "شوف حجزي الأول ولو موجود "
            "غيره للاتنين"
        ),
        expected_provider="gpt",
        expected_capability="appointment.reschedule",
    ),
]


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    load_dotenv(
        override=False
    )

    groq_api_key = os.getenv(
        "GROQ_API_KEY",
        "",
    )

    qwen_model_name = os.getenv(
        "QWEN_PLANNER_MODEL",
        "qwen/qwen3.6-27b",
    )

    qwen_timeout = float(
        os.getenv(
            "QWEN_PLANNER_TIMEOUT",
            "3",
        )
    )

    qwen_max_tokens = int(
        os.getenv(
            "QWEN_PLANNER_MAX_TOKENS",
            "160",
        )
    )

    gpt_model_name = (
        os.getenv(
            "PLANNER_FALLBACK_MODEL"
        )
        or os.getenv(
            "PLANNER_MODEL"
        )
        or "gpt-4.1"
    )

    print(
        "Qwen model:",
        qwen_model_name,
    )

    print(
        "GPT model:",
        gpt_model_name,
    )

    print(
        "Cases:",
        len(CASES),
    )

    print(
        "Retriever Top-K:",
        TOP_K,
    )

    router = (
        SemanticCapabilityRouter()
    )

    qwen_raw = QwenToolPlanner(
        api_key=groq_api_key,
        model=qwen_model_name,
        timeout=qwen_timeout,
        max_tokens=qwen_max_tokens,
    )

    gpt_model = ChatOpenAI(
        model=gpt_model_name,
        temperature=0,
        timeout=30,
    )

    gpt_raw = ToolPlanner(
        model=gpt_model,
    )

    qwen = CountingPlanner(
        qwen_raw
    )

    gpt = CountingPlanner(
        gpt_raw
    )

    planner = FallbackToolPlanner(
        primary=qwen,
        fallback=gpt,
    )

    total_passes = 0

    simple_latencies: list[float] = []
    complex_latencies: list[float] = []

    for index, case in enumerate(
        CASES,
        start=1,
    ):

        qwen.reset()
        gpt.reset()

        candidates = (
            select_capability_candidates(
                router=router,
                message=case.message,
                context=case.context,
                top_k=TOP_K,
            )
        )

        policy = (
            choose_planner_provider(
                message=case.message,
                context=case.context,
                candidates=candidates,
            )
        )

        started = (
            time.perf_counter()
        )

        try:

            result = await planner.plan(
                message=case.message,
                candidates=candidates,
                context=case.context,
            )

        except Exception as exc:

            print()
            print(
                "=" * 72
            )

            print(
                f"{index:02d}. {case.name}"
            )

            print(
                "ERROR:",
                type(exc).__name__,
                str(exc),
            )

            continue

        latency_ms = (
            time.perf_counter()
            - started
        ) * 1000

        if (
            case.expected_provider
            == "qwen"
        ):
            simple_latencies.append(
                latency_ms
            )

        else:
            complex_latencies.append(
                latency_ms
            )

        provider_correct = (
            policy.provider
            == case.expected_provider
        )

        capability_correct = (
            result.capability
            == case.expected_capability
        )

        # Complex requests MUST skip Qwen.
        if (
            case.expected_provider
            == "gpt"
        ):
            call_path_correct = (
                qwen.calls == 0
                and gpt.calls == 1
            )

        else:
            # Simple path must at least start with Qwen.
            #
            # GPT may still be used if the Qwen result is
            # rejected or the provider fails.
            call_path_correct = (
                qwen.calls == 1
            )

        passed = (
            provider_correct
            and capability_correct
            and call_path_correct
        )

        if passed:
            total_passes += 1

        print()
        print(
            "=" * 72
        )

        print(
            f"{index:02d}. {case.name}"
        )

        print(
            "=" * 72
        )

        print(
            "EXPECTED PROVIDER:",
            case.expected_provider,
        )

        print(
            "POLICY PROVIDER:",
            policy.provider,
        )

        print(
            "POLICY LEVEL:",
            policy.complexity_level,
        )

        print(
            "POLICY SCORE:",
            policy.complexity_score,
        )

        print(
            "POLICY SIGNALS:",
            policy.signals,
        )

        print(
            "QWEN CALLS:",
            qwen.calls,
        )

        print(
            "GPT CALLS:",
            gpt.calls,
        )

        print(
            "EXPECTED CAPABILITY:",
            case.expected_capability,
        )

        print(
            "RESULT CAPABILITY:",
            result.capability,
        )

        print(
            "ARGUMENTS:",
            result.arguments,
        )

        print(
            "LATENCY:",
            f"{latency_ms:.2f} ms",
        )

        print(
            "RESULT:",
            (
                "PASS"
                if passed
                else "FAIL"
            ),
        )

    print()
    print(
        "=" * 72
    )

    print(
        "PRODUCTION ROUTING SUMMARY"
    )

    print(
        "=" * 72
    )

    print(
        f"Passed:"
        f" {total_passes}/{len(CASES)}"
    )

    if simple_latencies:

        print(
            "Simple average:",
            f"{sum(simple_latencies) / len(simple_latencies):.2f} ms",
        )

    if complex_latencies:

        print(
            "Complex average:",
            f"{sum(complex_latencies) / len(complex_latencies):.2f} ms",
        )

    print()
    print(
        "For complex cases we require:"
    )

    print(
        "Qwen calls = 0"
    )

    print(
        "GPT calls  = 1"
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )