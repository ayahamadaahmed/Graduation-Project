import time

import torch

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)


MESSAGE = "عايز أحجز كشف جلدية"


def sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def measure(
    router: SemanticCapabilityRouter,
    label: str,
) -> None:

    sync_cuda()

    started = time.perf_counter()

    matches = router.route(
        MESSAGE,
        top_k=8,
    )

    sync_cuda()

    elapsed_ms = (
        time.perf_counter()
        - started
    ) * 1000

    print(
        f"{label}: "
        f"{elapsed_ms:.2f} ms "
        f"top={matches[0].name}"
    )


def main() -> None:

    router = SemanticCapabilityRouter()

    print()
    print("Router ready")
    print("Device:", router.device)
    print()

    # Warm GPU
    measure(router, "Warm-up")

    gaps = [
        0.1,
        1,
        3,
        5,
        10,
    ]

    for gap in gaps:

        print(
            f"\nSleeping {gap}s..."
        )

        time.sleep(gap)

        measure(
            router,
            f"After {gap}s idle",
        )


if __name__ == "__main__":
    main()