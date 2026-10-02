from __future__ import annotations

import time

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)


CASES = [
    # ========================================================
    # CREATE
    # ========================================================
    (
        "عايزة احجز",
        "appointment.create",
    ),
    (
        "ممكن أحجز بكرة؟",
        "appointment.create",
    ),
    (
        "عايز أعمل حجز",
        "appointment.create",
    ),
    (
        "عايزة ميعاد كشف",
        "appointment.create",
    ),

    # ========================================================
    # SEARCH
    # ========================================================
    (
        "عايزة أعرف حجزي",
        "appointment.search",
    ),
    (
        "عندي حجز امتى",
        "appointment.search",
    ),
    (
        "ممكن أعرف مواعيد حجوزاتي",
        "appointment.search",
    ),
    (
        "عايز أشوف الحجز بتاعي",
        "appointment.search",
    ),

    # ========================================================
    # CANCEL
    # ========================================================
    (
        "عايزة ألغي الحجز",
        "appointment.cancel",
    ),
    (
        "الغي ميعادي",
        "appointment.cancel",
    ),
    (
        "مش عايزة الحجز ده",
        "appointment.cancel",
    ),
    (
        "عايز أكنسل الحجز",
        "appointment.cancel",
    ),

    # ========================================================
    # RESCHEDULE
    # ========================================================
    (
        "عايزة أغير ميعاد الحجز",
        "appointment.reschedule",
    ),
    (
        "ممكن أنقل الحجز لبكرة",
        "appointment.reschedule",
    ),
    (
        "عايز أغير الحجز للسبت",
        "appointment.reschedule",
    ),
    (
        "ممكن أأجل الميعاد",
        "appointment.reschedule",
    ),
]


def main() -> None:
    print("Loading semantic router...")

    router = SemanticCapabilityRouter()

    print("\nAppointment Router Benchmark\n")

    top1_correct = 0
    top3_correct = 0
    top8_correct = 0

    latencies: list[float] = []

    for index, (message, expected) in enumerate(
        CASES,
        start=1,
    ):
        started = time.perf_counter()

        candidates = router.route(
            message,
            top_k=8,
        )

        elapsed_ms = (
            time.perf_counter()
            - started
        ) * 1000

        latencies.append(elapsed_ms)

        candidate_names = [
            candidate.name
            for candidate in candidates
        ]

        top1_pass = (
            len(candidate_names) >= 1
            and candidate_names[0] == expected
        )

        top3_pass = (
            expected
            in candidate_names[:3]
        )

        top8_pass = (
            expected
            in candidate_names[:8]
        )

        if top1_pass:
            top1_correct += 1

        if top3_pass:
            top3_correct += 1

        if top8_pass:
            top8_correct += 1

        if top1_pass:
            status = "TOP1"
        elif top3_pass:
            status = "TOP3"
        elif top8_pass:
            status = "TOP8"
        else:
            status = "MISS"

        print(
            f"{index:02d} | "
            f"{status:4} | "
            f"{elapsed_ms:7.2f} ms | "
            f"{message}"
        )

        print(
            f"     expected: {expected}"
        )

        for rank, candidate in enumerate(
            candidates,
            start=1,
        ):
            print(
                f"     {rank}. "
                f"{candidate.name:<30} "
                f"{candidate.score:.4f}"
            )

        print()

    total = len(CASES)

    top1_accuracy = (
        top1_correct
        / total
        * 100
    )

    top3_recall = (
        top3_correct
        / total
        * 100
    )

    top8_recall = (
        top8_correct
        / total
        * 100
    )

    average_latency = (
        sum(latencies)
        / len(latencies)
    )

    print("=" * 70)

    print(
        f"Top-1 Accuracy: "
        f"{top1_correct}/{total} "
        f"({top1_accuracy:.1f}%)"
    )

    print(
        f"Top-3 Recall:   "
        f"{top3_correct}/{total} "
        f"({top3_recall:.1f}%)"
    )

    print(
        f"Top-8 Recall:   "
        f"{top8_correct}/{total} "
        f"({top8_recall:.1f}%)"
    )

    print(
        f"Average router latency: "
        f"{average_latency:.2f} ms"
    )


if __name__ == "__main__":
    main()