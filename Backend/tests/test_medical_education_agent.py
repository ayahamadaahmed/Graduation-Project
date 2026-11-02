from medmind.medical_education_agent import (
    MedicalEducationAgent,
    MedicalEducationStatus,
)
from medmind.service import MedMindService


def test_arabic_migraine_cause_question_routes_to_medical_education():
    assert MedMindService._looks_like_medical_education_question(
        message="انا قاديلى يومين بيجيلى صداع نصفى تفتكر ايه هى الاسباب اللى ممكن تكون عملالى كدا",
    )


def test_booking_question_does_not_route_to_medical_education():
    assert not MedMindService._looks_like_medical_education_question(
        message="عايزة احجز موعد بكرة",
    )


def test_medical_education_agent_answers_cbc_question(
    tmp_path,
):

    kb_dir = (
        tmp_path
        / "knowledge_base"
    )

    kb_dir.mkdir()

    (
        kb_dir
        / "cbc_interpretation.md"
    ).write_text(
        """
# تحليل صورة الدم الكاملة CBC

## القيم الأساسية ومعناها

الهيموجلوبين بينقل الأكسجين في الدم.
انخفاضه ممكن يكون مرتبط بفقر الدم.
نتيجة CBC لوحدها لا تكفي للتشخيص النهائي.
        """,
        encoding="utf-8",
    )

    agent = MedicalEducationAgent(
        knowledge_base_dir=kb_dir,
    )

    result = agent.answer(
        query="يعني ايه CBC؟",
        language="ar",
    )

    assert (
        result.status
        == MedicalEducationStatus.ANSWERED
    )

    assert "معلومات تعليمية" in result.reply
    assert "CBC" in result.reply
    assert "مش تشخيص نهائي" in result.reply

    assert result.sources
    assert (
        result.sources[0].source_file
        == "cbc_interpretation"
    )


def test_medical_education_agent_answers_diabetes_question_in_english(
    tmp_path,
):

    kb_dir = (
        tmp_path
        / "knowledge_base"
    )

    kb_dir.mkdir()

    (
        kb_dir
        / "diabetes.md"
    ).write_text(
        """
# Diabetes

## Diagnostic criteria

HbA1c is also known as A1c.
A diabetes diagnosis requires laboratory testing and clinical review.
Symptoms alone are not enough for a final diagnosis.
        """,
        encoding="utf-8",
    )

    agent = MedicalEducationAgent(
        knowledge_base_dir=kb_dir,
    )

    result = agent.answer(
        query="What is HbA1c?",
        language="en",
    )

    assert (
        result.status
        == MedicalEducationStatus.ANSWERED
    )

    assert "educational information" in result.reply
    assert "HbA1c" in result.reply
    assert "not a diagnosis" in result.reply

    assert result.sources
    assert (
        result.sources[0].source_file
        == "diabetes"
    )


def test_medical_education_agent_returns_unsupported_when_kb_empty(
    tmp_path,
):

    kb_dir = (
        tmp_path
        / "knowledge_base"
    )

    kb_dir.mkdir()

    agent = MedicalEducationAgent(
        knowledge_base_dir=kb_dir,
    )

    result = agent.answer(
        query="What is something unrelated?",
        language="en",
    )

    assert (
        result.status
        == MedicalEducationStatus.UNSUPPORTED
    )

    assert result.sources == []
    assert (
        "do not have enough information"
        in result.reply
    )


def test_medical_education_agent_does_not_answer_unrelated_question(
    tmp_path,
):

    kb_dir = (
        tmp_path
        / "knowledge_base"
    )

    kb_dir.mkdir()

    (
        kb_dir
        / "cbc_interpretation.md"
    ).write_text(
        """
# CBC

## Blood count

CBC is a complete blood count test.
        """,
        encoding="utf-8",
    )

    agent = MedicalEducationAgent(
        knowledge_base_dir=kb_dir,
    )

    result = agent.answer(
        query="How do I fix my laptop charger?",
        language="en",
    )

    assert (
        result.status
        == MedicalEducationStatus.UNSUPPORTED
    )

    assert result.sources == []
