from evals.understanding.scoring import (
    score_understanding_result,
)


def test_exact_result_passes():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "date_text": "بكرة",
            },
            "confirmation": "unknown",
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "date_text": "بكرة",
            },
            "confirmation": "unknown",
            "ambiguity_kind": None,
        },
    )

    assert score.passed is True


def test_wrong_capability_fails():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.cancel",
        },
    )

    assert (
        score.capability_correct
        is False
    )

    assert score.passed is False


def test_missing_expected_argument_fails():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "time_text":
                    "الساعة 6",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {},
        },
    )

    assert (
        score.arguments_correct
        is False
    )

    assert (
        score.missing_arguments
        == ("time_text",)
    )


def test_hallucinated_argument_fails():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "date_text":
                    "بكرة",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "date_text":
                    "بكرة",

                "doctor_name":
                    "دكتور ماهر",
            },
        },
    )

    assert (
        score.arguments_correct
        is False
    )

    assert (
        "doctor_name"
        in score.wrong_arguments
    )


def test_empty_extra_argument_is_not_hallucination():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {},
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "doctor_name": None,
            },
        },
    )

    assert score.passed is True


def test_arabic_definite_article_difference_is_allowed():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "specialty_name":
                    "جلدية",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "specialty_name":
                    "الجلدية",
            },
        },
    )

    assert score.passed is True


def test_real_argument_difference_still_fails():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "doctor_name":
                    "دكتور ماهر",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "doctor_name":
                    "دكتورة منى",
            },
        },
    )

    assert (
        score.arguments_correct
        is False
    )


def test_ambiguity_must_match():

    score = score_understanding_result(
        expected={
            "status": "ambiguous",
            "capability": None,
            "ambiguity_kind":
                "needs_clarification",
        },
        actual={
            "status": "ambiguous",
            "capability": None,
            "ambiguity_kind":
                "candidate_miss",
        },
    )

    assert (
        score.ambiguity_correct
        is False
    )

    assert score.passed is False

def test_correction_target_must_match():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "correction_target":
                "phone",
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {},
            "confirmation":
                "unknown",
            "correction_target":
                "doctor",
            "ambiguity_kind":
                None,
        },
    )

    assert (
        score.correction_target_correct
        is False
    )

    assert score.passed is False


def test_expected_correction_target_passes():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "correction_target":
                "phone",
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {},
            "confirmation":
                "unknown",
            "correction_target":
                "phone",
            "ambiguity_kind":
                None,
        },
    )

    assert (
        score.correction_target_correct
        is True
    )

    assert score.passed is True

def test_semantically_equal_time_expression_passes():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "time_text":
                    "الساعة 6",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "time_text":
                    "6",
            },
        },
    )

    assert (
        score.arguments_correct
        is True
    )

    assert score.passed is True


def test_time_match_preserves_period_specificity():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "time_text":
                    "6 بالليل",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "time_text":
                    "6",
            },
        },
    )

    assert (
        score.arguments_correct
        is False
    )

    assert score.passed is False


def test_time_semantic_rule_does_not_affect_other_fields():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "doctor_name":
                    "دكتور ماهر",
            },
        },
        actual={
            "status": "selected",
            "capability":
                "appointment.create",
            "arguments": {
                "doctor_name":
                    "6",
            },
        },
    )

    assert (
        score.arguments_correct
        is False
    )   

def test_query_trailing_punctuation_is_semantically_equal():

    score = score_understanding_result(
        expected={
            "status": "selected",
            "capability":
                "knowledge.search",
            "arguments": {
                "query":
                    "دكتور ماهر بيعالج حب الشباب؟",
            },
            "confirmation": "unknown",
        },
        actual={
            "status": "selected",
            "capability":
                "knowledge.search",
            "arguments": {
                "query":
                    "دكتور ماهر بيعالج حب الشباب",
            },
            "confirmation": "unknown",
        },
    )

    assert (
        score.arguments_correct
        is True
    )

    assert score.passed is True     