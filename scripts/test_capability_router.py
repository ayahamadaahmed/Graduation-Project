from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)


TEST_MESSAGES = [
    "عايز أحجز كشف جلدية",
    "ممكن أحجز مع دكتور ماهر",
    "عايز ألغي ميعادي",
    "محتاج أغير ميعاد الحجز",
    "حجزي امتى",
    "عندكم دكاترة جلدية مين",
    "دكتور ماهر فاضي امتى",
    "كشف الجلدية بكام",
    "سياسة إلغاء الحجز عندكم ايه",
    "عايز أكلم خدمة العملاء",
]


router = SemanticCapabilityRouter()


for message in TEST_MESSAGES:

    print()
    print("=" * 70)
    print(
        "USER:",
        message,
    )
    print("-" * 70)

    matches = router.route(
        message,
        top_k=3,
    )

    for index, match in enumerate(
        matches,
        start=1,
    ):
        print(
            f"{index}. "
            f"{match.name:<28} "
            f"score={match.score:.4f}"
        )

        print(
            "   matched:",
            match.matched_text,
        )