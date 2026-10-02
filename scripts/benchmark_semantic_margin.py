from __future__ import annotations

import time

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.planner_policy import (
    choose_planner_provider,
)


CASES = [
    {
        "label": "simple",
        "message": "عايزة احجز",
        "context": {},
    },
    {
        "label": "simple",
        "message": "ممكن أحجز بكرة؟",
        "context": {},
    },
    {
        "label": "contextual",
        "message": "جلدية",
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_specialty",
        },
    },
    {
        "label": "contextual",
        "message": "بكرة",
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_date",
        },
    },
    {
        "label": "contextual",
        "message": "الساعة خمسة",
        "context": {
            "active_capability": "appointment.create",
            "stage": "awaiting_time",
        },
    },
    {
        "label": "complex",
        "message": "لا متلغهوش، غيره للسبت",
        "context": {
            "active_capability": "appointment.cancel",
            "stage": "awaiting_confirmation",
        },
    },
    {
        "label": "complex",
        "message": (
            "لو مفيش مع دكتورة منى السبت "
            "شوفلي دكتور تاني الأحد بعد الساعة ستة"
        ),
        "context": {},
    },
    {
        "label": "ambiguous",
        "message": "عايزة أغير الحجز",
        "context": {},
    },
]


def main() -> None:

    print("Loading semantic router...")

    router = SemanticCapabilityRouter()

    print("\nRunning benchmark...\n")

    for index, case in enumerate(
        CASES,
        start=1,
    ):

        started = time.perf_counter()

        candidates = router.route(
            case["message"],
            top_k=8,
        )

        router_ms = (
            time.perf_counter()
            - started
        ) * 1000

        decision = choose_planner_provider(
            message=case["message"],
            context=case["context"],
            candidates=candidates,
        )

        top1 = (
            candidates[0]
            if candidates
            else None
        )

        top2 = (
            candidates[1]
            if len(candidates) >= 2
            else None
        )

        print(
            f"{index:02d} | "
            f"{case['label']:10} | "
            f"router={router_ms:7.2f} ms | "
            f"provider={decision.provider:4} | "
            f"level={decision.complexity_level:10} | "
            f"score={decision.complexity_score:3} | "
            f"margin={decision.semantic_margin}"
        )

        if top1 is not None:

            print(
                f"     TOP1: "
                f"{top1.name} "
                f"{top1.score:.4f}"
            )

        if top2 is not None:

            print(
                f"     TOP2: "
                f"{top2.name} "
                f"{top2.score:.4f}"
            )

        print(
            f"     signals="
            f"{decision.signals}"
        )

        print()


if __name__ == "__main__":
    main()