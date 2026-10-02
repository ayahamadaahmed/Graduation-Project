from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)


# ============================================================
# CAPABILITY DEFINITION
# ============================================================

@dataclass(frozen=True)
class CapabilityDefinition:

    name: str

    description_ar: str

    description_en: str

    arguments: dict[
        str,
        str,
    ] = field(
        default_factory=dict
    )

    examples_ar: tuple[
        str,
        ...,
    ] = ()

    examples_en: tuple[
        str,
        ...,
    ] = ()

    requires_confirmation: bool = False

    domain: str = "general"


# ============================================================
# READ-ONLY SIDE-QUESTION CAPABILITIES
# ============================================================

READ_ONLY_SIDE_QUESTION_CAPABILITIES = frozenset(
    {
        "provider.get_slots",
        "provider.get_working_hours",
        "provider.search_doctors",
        "provider.get_services",
        "catalog.specialty.search",
        "provider.get_policy",
        "knowledge.search",
    }
)

# ============================================================
# CAPABILITY REGISTRY
# ============================================================

CAPABILITIES: tuple[
    CapabilityDefinition,
    ...,
] = (

    # ========================================================
    # Appointment
    # ========================================================

    CapabilityDefinition(
        name="appointment.create",
        domain="appointment",
        description_ar=(
        "إنشاء حجز جديد عندما يريد المستخدم "
        "الكشف أو الحجز أو تحديد موعد، "
        "حتى لو ذكر يومًا أو سأل إن كان ذلك ممكنًا."
        ),
        description_en=(
            "Create a new appointment when the user wants "
            "to book, get examined, or schedule a visit, "
            "even if they mention a date or ask if it is possible."
        ),
        
        arguments={
            "specialty_name":
                "Requested medical specialty.",

            "doctor_name":
                "Requested doctor.",

            "service_name":
                "Requested healthcare service.",

            "date_text":
                "Requested appointment date.",

            "time_text":
                "Requested appointment time.",

            "patient_name":
                (
                    "Patient name provided or corrected "
                    "during the booking workflow."
                ),

            "phone":
                (
                    "Patient phone number provided or corrected "
                    "during the booking workflow."
                ),

            "national_id":
                (
                    "Patient national ID provided during "
                    "the booking workflow."
                ),
        },
        examples_ar=(
            # Direct booking requests
            "عايز أحجز",
            "عايزة أحجز",
            "ممكن أحجز",
            "عايز أعمل حجز",
            "عايزة أعمل حجز",

            # Booking with date/time
            "ممكن أحجز بكرة",
            "عايز أحجز بكرة",
            "عايزة أحجز بكرة",
            "ممكن أحجز يوم السبت",
            "عايزة أحجز الساعة خمسة",

            # Booking with medical details
            "عايز أحجز كشف جلدية",
            "عايزة أحجز كشف جلدية",
            "ممكن أحجز مع دكتور ماهر بكرة",
            "عايز ميعاد كشف",
            "عايزة ميعاد كشف",
        ),
    ),

    CapabilityDefinition(
        name="appointment.cancel",
        domain="appointment",
        description_ar=(
            "إلغاء حجز أو موعد موجود."
        ),
        description_en=(
            "Cancel an existing appointment."
        ),
        arguments={
            "appointment_reference":
                "Existing appointment reference.",

            "national_id":
                (
                    "Patient national ID used to identify "
                    "the appointment owner."
                ),

            "doctor_name":
                (
                    "Doctor name used to identify the "
                    "existing appointment to cancel."
                ),

            "specialty_name":
                (
                    "Specialty used to identify the "
                    "existing appointment to cancel."
                ),

            "service_name":
                (
                    "Service used to identify the "
                    "existing appointment to cancel."
                ),

            "date_text":
                (
                    "Existing appointment date or weekday "
                    "used to identify which appointment "
                    "the user wants to cancel."
                ),

            "time_text":
                (
                    "Existing appointment time used to "
                    "identify which appointment the user "
                    "wants to cancel."
                ),
        },

        examples_ar=(
            "عايز ألغي الحجز",
            "الغي ميعادي",

            # Egyptian / code-switched cancellation
            "ممكن أكنسل الميعاد",
            "عايزة أكنسل ميعادي",
            "كنسل الموعد",
        ),
        requires_confirmation=True,
    ),

    CapabilityDefinition(
        name="appointment.reschedule",
        domain="appointment",
        description_ar=(
            "تغيير تاريخ أو وقت حجز موجود."
        ),
        description_en=(
            "Reschedule an existing appointment."
        ),
        arguments={
            "appointment_reference":
                "Existing appointment reference.",

            "national_id":
                (
                    "Patient national ID used to identify "
                    "the appointment owner."
                ),

            "date_text":
                "New date.",

            "time_text":
                "New time.",

            "doctor_name":
                "New doctor if requested.",
        },
        examples_ar=(
            "عايز أغير ميعاد الحجز",
            "ممكن أنقل الحجز لبكرة",
        ),
        requires_confirmation=True,
    ),

    CapabilityDefinition(
        name="appointment.search",
        domain="appointment",
        description_ar=(
            "البحث عن حجز معين أو عرض حجوزات المريض."
        ),
        description_en=(
            "Search for a specific appointment or retrieve "
            "patient appointments."
        ),
        arguments={
            "appointment_reference":
                (
                    "Existing appointment reference explicitly "
                    "provided by the user."
                ),
        },
        examples_ar=(
            "عندي حجز امتى",
            "عايز أعرف حجوزاتي",
            "عايز أعرف الحجز APT-260815-XXXX",
            "ممكن أشوف حجز APT-260815-XXXX",
        ),
        examples_en=(
            "When is my appointment?",
            "Show me my appointments.",
            "Show me appointment APT-260815-XXXX.",
        ),
    ),

    # ========================================================
    # Provider
    # ========================================================

    CapabilityDefinition(
        name="catalog.specialty.search",
        domain="provider",
        description_ar=(
            "عرض أو البحث في قائمة التخصصات الطبية "
            "المتاحة لدى مقدم الخدمة."
        ),
        description_en=(
            "List or search the medical specialties "
            "available from the provider."
        ),
        examples_ar=(
            "إيه التخصصات الموجودة؟",
            "إيه التخصصات اللي موجودة في المستشفى؟",
            "عندكم تخصصات إيه؟",
            "التخصصات المتاحة إيه؟",
        ),
        examples_en=(
            "What specialties are available?",
            "What medical specialties do you have?",
            "List the available specialties.",
        ),
    ),

    CapabilityDefinition(
        name="provider.search_doctors",
        domain="provider",
        description_ar=(
            "البحث عن الأطباء أو معرفة الأطباء "
            "المتاحين في تخصص معين."
        ),
        description_en=(
            "Search the provider doctor catalog."
        ),
        arguments={
            "specialty_name":
                "Optional medical specialty.",
        },
        examples_ar=(
            "عندكم دكاترة جلدية مين",
            "مين دكتور العيون",
        ),
    ),

    CapabilityDefinition(
        name="provider.get_services",
        domain="provider",
        description_ar=(
            "عرض الخدمات الطبية أو أسعار الخدمات الفعلية "
            "المتاحة لدى مقدم الخدمة، بما في ذلك عندما "
            "يصف المستخدم مشكلة أو هدفًا ويريد معرفة "
            "الخدمات المتاحة لها دون طلب نصيحة علاجية."
        ),
        description_en=(
            "Retrieve actual healthcare services or service "
            "prices offered by the current provider, including "
            "when the user describes a concern or goal and wants "
            "to know what provider services are available."
        ),
        arguments={
            "doctor_name":
                "Optional doctor.",

            "specialty_name":
                "Optional specialty.",

            "service_name":
                (
                    "Optional service, procedure, treatment, or named offering "
                    "explicitly mentioned by the user. For price/cost/fee questions, "
                    "preserve the user-stated phrase such as 'تساقط الشعر' or 'الليزر'. "
                    "This is not a database ID and must not be invented from a general "
                    "symptom or goal."
                ),
        },
        examples_ar=(
            "عندكم خدمات ايه",
            "كشف الجلدية بكام",
            "عندكم خدمات للتصبغات؟",
            "عايزة حاجة للتصبغات عندكم",
            "تساقط الشعر بكام؟",
            "سعر علاج تساقط الشعر كام؟",
            "سعر الليزر كام؟",
            "أسعار خدمات الجلدية؟",
        ),
        examples_en=(
            "What services do you offer?",
            "How much is the dermatology consultation?",
            "Do you have services for pigmentation?",
        ),
    ),

    CapabilityDefinition(
        name="provider.get_slots",
        domain="provider",
        description_ar=(
            "عرض المواعيد أو الأوقات المتاحة فقط عندما "
            "يسأل المستخدم عن التوافر أو الخيارات المتاحة، "
            "بدون طلب إنشاء حجز جديد."
        ),
        description_en=(
            "Retrieve available appointment times only when "
            "the user is asking about availability or options, "
            "without requesting a new booking."
        ),
        arguments={
            "doctor_name":
                "Optional doctor name.",

            "specialty_name":
                "Optional specialty name.",

            "date_text":
                (
                    "Optional requested day or date, "
                    "such as بكرة, السبت, or يوم الخميس."
                ),

            "time_text":
                (
                    "Optional requested time or time period, "
                    "such as الساعة خمسة, بعد الضهر, "
                    "الصبح, or بالليل."
                ),
        },
        examples_ar=(
            "دكتور ماهر فاضي امتى",
            "المواعيد المتاحة بكرة ايه",
            "في مواعيد متاحة بالليل",
        ),
        examples_en=(
            "When is the doctor available?",
            "What appointments are available tomorrow?",
            "Are there appointments available in the evening?",
        ),
    ),

    CapabilityDefinition(
        name="provider.get_policy",
        domain="provider",
        description_ar=(
            "الاستفسار عن سياسات وقواعد وتعليمات "
            "مقدم الخدمة أو العيادة دون طلب تنفيذ "
            "عملية على حجز معين."
        ),
        description_en=(
            "Ask about provider policies, rules, "
            "or instructions without requesting "
            "an appointment operation."
        ),
        arguments={
            "query":
                (
                    "The user's policy or instruction "
                    "question."
                ),
        },
        examples_ar=(
            "إيه سياسة إلغاء المواعيد؟",
            "إيه قواعد تغيير الحجز؟",
            "لو المريض اتأخر بيحصل إيه؟",
            "إيه تعليمات الحضور للموعد؟",
            "مسموح أتأخر عن الكشف؟",
        ),
        examples_en=(
            "What is the cancellation policy?",
            "What are the rescheduling rules?",
            "What happens if a patient is late?",
        ),
    ),

    CapabilityDefinition(
        name="provider.get_working_hours",
        domain="provider",

        description_ar=(
            "معرفة مواعيد أو ساعات عمل طبيب "
            "أو العيادة أو الفرع، أو مواعيد "
            "الفتح والإغلاق."
        ),

        description_en=(
            "Retrieve doctor, provider, branch, "
            "opening, or working hours."
        ),

        arguments={
            "doctor_name":
                (
                    "Optional doctor whose working "
                    "hours are requested."
                ),

            "specialty_name":
                (
                    "Optional specialty used to identify "
                    "the requested doctor."
                ),

            "branch_name":
                "Optional branch name.",

            "date_text":
                (
                    "Optional requested day or date."
                ),
        },

        examples_ar=(
            "العيادة بتفتح امتى",
            "مواعيد عمل الفرع ايه",
            "الفرع بيفتح الساعة كام",
            "مواعيد شغل دكتور ماهر",
            "دكتور ماهر بيشتغل امتى",
            "مواعيد شغل دكتور ماهر يوم الخميس",
        ),

        examples_en=(
            "What are the clinic working hours?",
            "When does the branch open?",
            "What are Dr Maher's working hours?",
        ),
    ),
    # ========================================================
    # Knowledge
    # ========================================================

    CapabilityDefinition(
        name="knowledge.search",
        domain="knowledge",
        description_ar=(
            "البحث في قاعدة معرفة مقدم الخدمة عن "
            "معلومات موثوقة خاصة بمقدم الخدمة، مثل "
            "خبرات الأطباء والحالات التي يعالجونها "
            "والمعلومات المعتمدة الخاصة بالخدمات. "
            "لا يستخدم للنصائح أو التوصيات العلاجية العامة."
        ),
        description_en=(
            "Search the current provider's approved knowledge "
            "base for provider-specific information such as "
            "doctor expertise, conditions treated by a doctor, "
            "or approved service information. Not for general "
            "diagnosis or treatment recommendations."
        ),
        arguments={
            "query":
                "The user's knowledge question.",
        },
        examples_ar=(
            "دكتور ماهر بيعالج حب الشباب؟",
            "دكتور ماهر متخصص في إيه؟",
            "خدمة الليزر عندكم بتستخدم في ايه؟",
        ),
        examples_en=(
            "Does Dr. Maher treat acne?",
            "What is Dr. Maher specialized in?",
            "What is your laser service used for?",
        ),
    ),

    # ========================================================
    # Support
    # ========================================================

    CapabilityDefinition(
        name="human_support.transfer",
        domain="support",
        description_ar=(
            "تحويل المستخدم لموظف أو دعم بشري."
        ),
        description_en=(
            "Transfer the conversation to human support."
        ),
        examples_ar=(
            "عايز أكلم حد",
            "حولني لخدمة العملاء",
        ),
    ),
)


# ============================================================
# LOOKUP
# ============================================================

CAPABILITY_BY_NAME = {
    capability.name:
        capability
    for capability in CAPABILITIES
}


def get_capability(
    name: str,
) -> CapabilityDefinition | None:

    return (
        CAPABILITY_BY_NAME.get(
            name
        )
    )


def get_capabilities_by_domain(
    domain: str,
) -> list[
    CapabilityDefinition
]:

    return [
        capability
        for capability in CAPABILITIES
        if capability.domain == domain
    ]