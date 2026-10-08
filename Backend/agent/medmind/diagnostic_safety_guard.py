from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


class SafetyUrgency(str, Enum):
    ROUTINE = "routine"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class DiagnosticSafetyResult:
    urgency: SafetyUrgency
    blocked: bool = False
    message_to_patient: str = ""
    triggered_rules: list[str] = field(
        default_factory=list
    )
    confirmation_field: str | None = None


class DiagnosticSafetyGuardAgent:
    """
    Deterministic safety guard for diagnostic conversations.

    This agent is not a diagnosis engine.
    It only detects obvious emergency red flags from the
    user's text before continuing normal diagnostic analysis.
    """

    _CRITICAL_PATTERNS: tuple[
        tuple[str, tuple[str, ...]],
        ...,
    ] = (
        (
            "chest_pain_with_cold_sweat_or_radiation",
            (
                r"الم صدر.*عرق بارد",
                r"وجع صدر.*عرق بارد",
                r"الم في الصدر.*عرق بارد",
                r"الم صدر.*للذراع",
                r"الم صدر.*للدراع",
                r"الم صدر.*للفك",
                r"وجع صدر.*للذراع",
                r"chest pain.*cold sweat",
                r"chest pain.*sweating",
                r"chest pain.*arm",
                r"chest pain.*jaw",
            ),
        ),
        (
            "chest_pain_with_fainting",
            (
                r"الم صدر.*اغماء",
                r"وجع صدر.*اغماء",
                r"الم في الصدر.*فقدان وعي",
                r"chest pain.*faint",
                r"chest pain.*loss of consciousness",
            ),
        ),
        (
            "severe_breathlessness",
            (
                r"مش قادر.*اتنفس",
                r"مش قادرة.*اتنفس",
                r"مش عارف.*اتنفس",
                r"مش عارفة.*اتنفس",
                r"ضيق نفس شديد",
                r"صعوبة تنفس شديدة",
                r"severe shortness of breath",
                r"can.?t breathe",
            ),
        ),
        (
            "uncontrolled_bleeding",
            (
                r"نزيف.*مش بيقف",
                r"نزيف.*مستمر",
                r"نزيف شديد.*مش بيقف",
                r"bleeding.*won.?t stop",
                r"uncontrolled bleeding",
            ),
        ),
        (
            "sudden_stroke_like_symptoms",
            (
                r"ضعف مفاجئ.*وش",
                r"ضعف مفاجئ.*ذراع",
                r"ضعف مفاجئ.*دراع",
                r"صعوبة كلام.*فجأة",
                r"كلامي تقيل.*فجأة",
                r"مش قادر.*احرك.*ذراع",
                r"مش قادرة.*احرك.*ذراع",
                r"sudden weakness.*speech",
                r"sudden weakness.*arm",
                r"face drooping.*speech",
            ),
        ),
        (
            "thunderclap_headache",
            (
                r"اسوا صداع.*فجأة",
                r"اسوأ صداع.*فجأة",
                r"اسوا صداع.*في حيات",
                r"صداع.*زي ضربة.*فجأة",
                r"thunderclap headache",
                r"worst headache.*sudden",
            ),
        ),
        (
            "headache_with_fever_and_neck_stiffness",
            (
                r"صداع.*حرارة.*تيبس",
                r"صداع.*سخونية.*رقبة",
                r"headache.*fever.*stiff neck",
            ),
        ),
    )

    _SOFT_CONFIRMATION_PATTERNS: tuple[
        tuple[str, tuple[str, ...], str, str],
        ...,
    ] = (
        (
            "severe_shortness_of_breath",
            (
                "ضيق نفس",
                "نهجان شديد",
                "مش قادر اتنفس",
                "مش قادرة اتنفس",
                "shortness of breath",
                "breathless",
            ),
            "breathlessness_persists_at_rest",
            (
                "ضيق النفس ده مستمر دلوقتي وإنت مرتاح، "
                "ولا بيظهر مع المجهود أو التوتر وبيخف؟"
            ),
        ),
        (
            "uncontrolled_bleeding",
            (
                "نزيف",
                "bleeding",
            ),
            "bleeding_still_active_now",
            (
                "النزيف لسه مستمر دلوقتي ومش بيقف "
                "رغم الضغط عليه؟"
            ),
        ),
        (
            "sudden_weakness_face_arm_speech",
            (
                "ضعف مفاجئ",
                "صعوبة كلام",
                "كلامي تقيل",
                "sudden weakness",
            ),
            "weakness_started_suddenly_and_ongoing",
            (
                "الضعف أو صعوبة الكلام بدأت فجأة "
                "ولسه موجودة دلوقتي؟"
            ),
        ),
    )

    def check_text(
        self,
        *,
        message: str,
        language: str,
    ) -> DiagnosticSafetyResult:

        normalized = self._normalize(
            message
        )

        triggered_rules: list[str] = []

        for rule_name, patterns in self._CRITICAL_PATTERNS:
            if any(
                re.search(
                    self._normalize(pattern),
                    normalized,
                    flags=re.IGNORECASE,
                )
                for pattern in patterns
            ):
                triggered_rules.append(
                    rule_name
                )

        if triggered_rules:
            return DiagnosticSafetyResult(
                urgency=SafetyUrgency.CRITICAL,
                blocked=True,
                triggered_rules=triggered_rules,
                message_to_patient=(
                    self._critical_message(
                        language=language,
                    )
                ),
            )

        for (
            rule_name,
            phrases,
            confirmation_field,
            prompt_ar,
        ) in self._SOFT_CONFIRMATION_PATTERNS:

            if any(
                self._normalize(phrase)
                in normalized
                for phrase in phrases
            ):
                return DiagnosticSafetyResult(
                    urgency=(
                        SafetyUrgency
                        .NEEDS_CONFIRMATION
                    ),
                    blocked=True,
                    triggered_rules=[
                        rule_name,
                    ],
                    confirmation_field=(
                        confirmation_field
                    ),
                    message_to_patient=(
                        prompt_ar
                        if language == "ar"
                        else self._english_confirmation_prompt(
                            rule_name
                        )
                    ),
                )

        return DiagnosticSafetyResult(
            urgency=SafetyUrgency.ROUTINE,
            blocked=False,
        )

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        normalized = (
            str(text or "")
            .lower()
            .strip()
        )

        normalized = (
            normalized
            .replace("إ", "ا")
            .replace("أ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
        )

        normalized = re.sub(
            r"\s+",
            " ",
            normalized,
        )

        return normalized

    @staticmethod
    def _critical_message(
        *,
        language: str,
    ) -> str:

        if language == "ar":
            return (
                "الأعراض اللي قلتها ممكن تكون علامة على حالة طارئة. "
                "الأفضل تتواصل مع الإسعاف أو تروح لأقرب طوارئ فورًا. "
                "المساعد ده مش بديل عن التقييم الطبي العاجل."
            )

        return (
            "The symptoms you described may indicate an emergency. "
            "Please contact emergency services or go to the nearest "
            "emergency department now. This assistant is not a substitute "
            "for urgent medical assessment."
        )

    @staticmethod
    def _english_confirmation_prompt(
        rule_name: str,
    ) -> str:

        prompts = {
            "severe_shortness_of_breath": (
                "Is the shortness of breath happening now while resting, "
                "or does it mainly happen with stress or effort and improve quickly?"
            ),
            "uncontrolled_bleeding": (
                "Is the bleeding still active now and not stopping "
                "despite direct pressure?"
            ),
            "sudden_weakness_face_arm_speech": (
                "Did the weakness or speech difficulty start suddenly "
                "and is it still present now?"
            ),
        }

        return prompts.get(
            rule_name,
            "Can you clarify whether this symptom is happening right now?",
        )