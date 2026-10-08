from __future__ import annotations

import time

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)


TEST_CASES = [

    # ========================================================
    # Appointment create
    # ========================================================

    (
        "محتاج أكشف جلدية",
        "appointment.create",
    ),
    (
        "عاوز ميعاد عند دكتور جلدية",
        "appointment.create",
    ),
    (
        "ينفع آخد ميعاد مع دكتور ماهر؟",
        "appointment.create",
    ),
    (
        "ممكن أعمل حجز لبكرة؟",
        "appointment.create",
    ),

    # ========================================================
    # Appointment cancel
    # ========================================================

    (
        "مش هقدر أجي وعاوز ألغي الموعد",
        "appointment.cancel",
    ),
    (
        "شيل الحجز اللي عندي",
        "appointment.cancel",
    ),
    (
        "مش عايز الميعاد ده خلاص",
        "appointment.cancel",
    ),

    # ========================================================
    # Appointment reschedule
    # ========================================================

    (
        "ينفع أخلي معادي يوم تاني؟",
        "appointment.reschedule",
    ),
    (
        "عايز أنقل الكشف للسبت",
        "appointment.reschedule",
    ),
    (
        "ممكن نغير الساعة بدل خمسة؟",
        "appointment.reschedule",
    ),

    # ========================================================
    # Appointment search
    # ========================================================

    (
        "فكرني أنا حاجز امتى",
        "appointment.search",
    ),
    (
        "عندي ميعاد قريب؟",
        "appointment.search",
    ),
    (
        "وريني المواعيد اللي حاجزها",
        "appointment.search",
    ),

    # ========================================================
    # Doctor search
    # ========================================================

    (
        "مين عندكم متخصص جلدية؟",
        "provider.search_doctors",
    ),
    (
        "عايز أعرف الدكاترة الموجودين",
        "provider.search_doctors",
    ),
    (
        "فيه دكتور عيون عندكم؟",
        "provider.search_doctors",
    ),

    # ========================================================
    # Slots
    # ========================================================

    (
        "ماهر عنده مواعيد فاضية بكرة؟",
        "provider.get_slots",
    ),
    (
        "إيه أقرب وقت متاح للدكتور؟",
        "provider.get_slots",
    ),
    (
        "فيه كشف متاح بعد الضهر؟",
        "provider.get_slots",
    ),

    # ========================================================
    # Services
    # ========================================================

    (
        "سعر الكشف كام؟",
        "provider.get_services",
    ),
    (
        "بتقدموا خدمات إيه؟",
        "provider.get_services",
    ),
    (
        "تكلفة كشف العيون إيه؟",
        "provider.get_services",
    ),

    # ========================================================
    # Knowledge
    # ========================================================

    (
        "لو اتأخرت عن الميعاد بيحصل إيه؟",
        "knowledge.search",
    ),
    (
        "إيه نظام تغيير المواعيد عندكم؟",
        "knowledge.search",
    ),
    (
        "الفرع بيقفل الساعة كام؟",
        "knowledge.search",
    ),
    (
        "ماهر بيعالج آثار الحبوب؟",
        "knowledge.search",
    ),
    (
        "بتقفلوا امتى النهارده؟",
        "provider.get_working_hours",
    ),
    (
        "مواعيد الشغل يوم الجمعة إيه؟",
        "provider.get_working_hours",
    ),
    (
        "العيادة شغالة لحد الساعة كام؟",
        "provider.get_working_hours",
    ),

    (
        "لو وصلت بعد ميعادي بربع ساعة أعمل إيه؟",
        "provider.get_policy",
    ),
    (
        "ممكن أعرف القواعد لو احتجت أبدل يوم الكشف؟",
        "provider.get_policy",
    ),
    (
        "هل في مشكلة لو مقدرتش أحضر في الوقت المحدد؟",
        "provider.get_policy",
    ),
    (
        "إيه الشروط لو عايز أبدل موعد موجود؟",
        "provider.get_policy",
    ),

    # ========================================================
    # Human support
    # ========================================================

    (
        "ممكن تخليني أكلم موظف؟",
        "human_support.transfer",
    ),
    (
        "أنا محتاج حد من الاستقبال",
        "human_support.transfer",
    ),
    (
        "عايز أتواصل مع شخص مش بوت",
        "human_support.transfer",
    ),
]


router = SemanticCapabilityRouter()


# ------------------------------------------------------------
# Warm-up
# ------------------------------------------------------------

router.route(
    "اختبار",
    top_k=3,
)


top1_correct = 0
top3_correct = 0
top5_correct = 0

latencies_ms: list[float] = []


for message, expected in TEST_CASES:

    started_at = time.perf_counter()

    matches = router.route(
        message,
        top_k=5,
    )

    elapsed_ms = (
        time.perf_counter()
        - started_at
    ) * 1000

    latencies_ms.append(
        elapsed_ms
    )

    names = [
        match.name
        for match in matches
    ]

    top1_ok = (
        bool(names)
        and names[0] == expected
    )

    top3_ok = (
        expected in names[:3]
    )

    top5_ok = (
        expected in names[:5]
    )

    if top1_ok:
        top1_correct += 1

    if top3_ok:
        top3_correct += 1

    if top5_ok:
        top5_correct += 1     

    print()
    print("=" * 80)

    print(
        "USER:",
        message,
    )

    print(
        "EXPECTED:",
        expected,
    )

    print(
        f"LATENCY: {elapsed_ms:.2f} ms"
    )

    print("-" * 80)

    for index, match in enumerate(
        matches,
        start=1,
    ):

        print(
            f"{index}. "
            f"{match.name:<28} "
            f"{match.score:.4f}"
        )

    print(
        "TOP1:",
        "PASS"
        if top1_ok
        else "FAIL",
    )

    print(
        "TOP3:",
        "PASS"
        if top3_ok
        else "FAIL",
    )

    print(
        "TOP5:",
        "PASS"
        if top5_ok
        else "FAIL",
    )

total = len(
    TEST_CASES
)

top1_accuracy = (
    top1_correct
    / total
)

top3_recall = (
    top3_correct
    / total
)

top5_recall = (
    top5_correct
    / total
)

average_latency = (
    sum(latencies_ms)
    / len(latencies_ms)
)


print()
print("=" * 80)
print("FINAL RESULTS")
print("=" * 80)

print(
    f"Cases: {total}"
)

print(
    f"Top-1 accuracy: "
    f"{top1_accuracy:.2%}"
)

print(
    f"Top-3 recall: "
    f"{top3_recall:.2%}"
)
print(
    f"Top-5 recall: "
    f"{top5_recall:.2%}"
)
print(
    f"Average inference latency: "
    f"{average_latency:.2f} ms"
)