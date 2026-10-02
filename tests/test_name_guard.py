from voice_gateway.safety.name_guard import (
    arbitrate_name_transcripts,
    names_equivalent,
    normalize_name_for_comparison,
    resolve_name_stage_transcript,
)
def test_arabic_name_normalization() -> None:
    assert (
        normalize_name_for_comparison(
            "  آيَة   محمد "
        )
        == "اية محمد"
    )

def test_single_name_part_is_incomplete() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="آية",
        deepgram_transcript="آية محمد",
    )

    assert decision.action == "accept"
    assert decision.provider == "deepgram"
    assert decision.transcript == "آية محمد"
    assert decision.reason == "deepgram_only_valid"    

def test_equivalent_arabic_spellings_agree() -> None:
    assert names_equivalent(
        "أحمد محمد",
        "احمد محمد",
    )


def test_matching_candidates_accept_hamsa() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="آية محمد",
        deepgram_transcript="آية محمد",
    )

    assert decision.action == "accept"
    assert decision.provider == "hamsa"
    assert decision.transcript == "آية محمد"
    assert decision.reason == "providers_agree"


def test_hamsa_only_valid_candidate() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="آية محمد",
        deepgram_transcript=None,
    )

    assert decision.action == "accept"
    assert decision.provider == "hamsa"


def test_deepgram_only_valid_candidate() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="1234",
        deepgram_transcript="آية محمد",
    )

    assert decision.action == "accept"
    assert decision.provider == "deepgram"
    assert decision.transcript == "آية محمد"

def test_truncated_hamsa_uses_valid_deepgram_name() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="آية",
        deepgram_transcript="آية محمد",
    )

    assert decision.action == "accept"
    assert decision.provider == "deepgram"
    assert decision.transcript == "آية محمد"
    assert decision.reason == "deepgram_only_valid"


def test_different_names_retry() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="آية محمد",
        deepgram_transcript="آية محمود",
    )

    assert decision.action == "retry"
    assert decision.reason == "provider_disagreement"


def test_both_invalid_retry() -> None:
    decision = arbitrate_name_transcripts(
        hamsa_transcript="123",
        deepgram_transcript="...",
    )

    assert decision.action == "retry"
    assert decision.reason == "no_valid_candidate"

def test_name_stage_runtime_uses_deepgram_when_hamsa_is_truncated() -> None:
    decision = resolve_name_stage_transcript(
        stage="awaiting_patient_name_correction",
        hamsa_transcript="آية",
        deepgram_transcript="آية محمد",
    )

    assert decision is not None
    assert decision.action == "accept"
    assert decision.provider == "deepgram"
    assert decision.transcript == "آية محمد"


def test_name_stage_runtime_blocks_real_provider_disagreement() -> None:
    decision = resolve_name_stage_transcript(
        stage="awaiting_patient_name_correction",
        hamsa_transcript="آية محمد",
        deepgram_transcript="آية محمود",
    )

    assert decision is not None
    assert decision.action == "retry"
    assert decision.transcript is None


def test_name_arbitration_does_not_touch_other_stages() -> None:
    decision = resolve_name_stage_transcript(
        stage="awaiting_time",
        hamsa_transcript="الساعة خمسة",
        deepgram_transcript="الساعة خمسة",
    )

    assert decision is None    