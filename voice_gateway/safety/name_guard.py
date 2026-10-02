from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

NameDecisionAction = Literal[
    "accept",
    "retry",
]

NameProvider = Literal[
    "hamsa",
    "deepgram",
]

NAME_DUAL_STT_STAGES = {
    "awaiting_patient_name",
    "awaiting_patient_name_correction",
}

@dataclass(frozen=True)
class NameArbitrationDecision:
    action: NameDecisionAction
    transcript: str | None
    provider: NameProvider | None
    reason: str


def _strip_diacritics(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize(
            "NFKD",
            text,
        )
        if not unicodedata.combining(character)
    )


def normalize_name_for_comparison(
    transcript: str | None,
) -> str:
    """
    Conservative normalization used ONLY for comparing
    two STT name candidates.

    This does not change the transcript that will be sent
    to MedMind.
    """

    if not transcript:
        return ""

    text = _strip_diacritics(
        transcript.strip()
    )

    text = text.replace("ـ", "")

    # Safe Arabic orthographic normalization.
    text = (
        text
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
    )

    text = text.lower()

    # Keep Arabic/English letters and whitespace only.
    text = re.sub(
        r"[^a-z\u0600-\u06ff\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def is_plausible_name_candidate(
    transcript: str | None,
) -> bool:
    """
    Basic structural validation only.

    We intentionally do NOT require two words because a
    caller may initially provide only one name.

    We also do not attempt to guess whether a real person
    has this name.
    """

    normalized = normalize_name_for_comparison(
        transcript
    )

    if not normalized:
        return False

    if len(normalized) > 120:
        return False

    tokens = normalized.split()

    if len(tokens) < 2:
        return False

    if len(tokens) > 6:
        return False

    return all(
        bool(
            re.fullmatch(
                r"[a-z\u0600-\u06ff]+",
                token,
            )
        )
        for token in tokens
    )


def names_equivalent(
    first: str,
    second: str,
) -> bool:
    """
    Only accept genuine normalized agreement.

    We deliberately do NOT use fuzzy matching here.
    A patient name is identity-sensitive, so uncertain
    similarity must not silently become a different name.
    """

    first_normalized = (
        normalize_name_for_comparison(first)
    )

    second_normalized = (
        normalize_name_for_comparison(second)
    )

    return (
        bool(first_normalized)
        and first_normalized
        == second_normalized
    )


def arbitrate_name_transcripts(
    *,
    hamsa_transcript: str | None,
    deepgram_transcript: str | None,
) -> NameArbitrationDecision:
    """
    Conservative dual-STT arbitration for patient names.

    Rules:
    - Both providers agree -> accept Hamsa's original text.
    - Only Hamsa is valid -> accept Hamsa.
    - Only Deepgram is valid -> accept Deepgram.
    - Both valid but disagree -> retry.
    - Neither valid -> retry.

    Never choose a candidate merely because it is longer.
    """

    hamsa_valid = is_plausible_name_candidate(
        hamsa_transcript
    )

    deepgram_valid = is_plausible_name_candidate(
        deepgram_transcript
    )

    if (
        hamsa_valid
        and deepgram_valid
        and names_equivalent(
            hamsa_transcript or "",
            deepgram_transcript or "",
        )
    ):
        return NameArbitrationDecision(
            action="accept",
            transcript=(
                hamsa_transcript.strip()
                if hamsa_transcript
                else None
            ),
            provider="hamsa",
            reason="providers_agree",
        )

    if hamsa_valid and not deepgram_valid:
        return NameArbitrationDecision(
            action="accept",
            transcript=(
                hamsa_transcript.strip()
                if hamsa_transcript
                else None
            ),
            provider="hamsa",
            reason="hamsa_only_valid",
        )

    if deepgram_valid and not hamsa_valid:
        return NameArbitrationDecision(
            action="retry",
            transcript=None,
            provider=None,
            reason="deepgram_only_valid_requires_retry",
        )
    
    if hamsa_valid and deepgram_valid:
        return NameArbitrationDecision(
            action="retry",
            transcript=None,
            provider=None,
            reason="provider_disagreement",
        )

    return NameArbitrationDecision(
        action="retry",
        transcript=None,
        provider=None,
        reason="no_valid_candidate",
    )

def resolve_name_stage_transcript(
    *,
    stage: str | None,
    hamsa_transcript: str | None,
    deepgram_transcript: str | None,
) -> NameArbitrationDecision | None:
    """
    Apply patient-name arbitration only to name collection stages.

    Returns None for all unrelated conversation stages so the
    normal STT flow remains unchanged.
    """

    normalized_stage = (
        stage or ""
    ).strip().lower()

    if normalized_stage not in NAME_DUAL_STT_STAGES:
        return None

    return arbitrate_name_transcripts(
        hamsa_transcript=hamsa_transcript,
        deepgram_transcript=deepgram_transcript,
    )    