from medmind.diagnostic_safety_guard import (
    DiagnosticSafetyGuardAgent,
    SafetyUrgency,
)


def make_agent():
    return DiagnosticSafetyGuardAgent()


def test_routine_diagnostic_request_is_not_blocked():

    agent = make_agent()

    result = agent.check_text(
        message="حلل أشعة الصدر دي",
        language="ar",
    )

    assert result.urgency == SafetyUrgency.ROUTINE
    assert result.blocked is False
    assert result.triggered_rules == []


def test_arabic_chest_pain_red_flag_is_critical():

    agent = make_agent()

    result = agent.check_text(
        message=(
            "عندي ألم صدر وعرق بارد "
            "والألم بيمتد للدراع"
        ),
        language="ar",
    )

    assert result.urgency == SafetyUrgency.CRITICAL
    assert result.blocked is True
    assert result.triggered_rules
    assert "طوارئ" in result.message_to_patient


def test_english_chest_pain_red_flag_is_critical():

    agent = make_agent()

    result = agent.check_text(
        message=(
            "I have chest pain with cold sweat "
            "and pain going to my arm"
        ),
        language="en",
    )

    assert result.urgency == SafetyUrgency.CRITICAL
    assert result.blocked is True
    assert result.triggered_rules
    assert "emergency" in result.message_to_patient.lower()


def test_soft_breathlessness_asks_confirmation():

    agent = make_agent()

    result = agent.check_text(
        message="عندي ضيق نفس",
        language="ar",
    )

    assert (
        result.urgency
        == SafetyUrgency.NEEDS_CONFIRMATION
    )

    assert result.blocked is True

    assert (
        result.confirmation_field
        == "breathlessness_persists_at_rest"
    )

    assert "ضيق النفس" in result.message_to_patient


def test_clear_diagnostic_upload_with_no_symptoms_is_routine():

    agent = make_agent()

    result = agent.check_text(
        message="Analyze this brain MRI",
        language="en",
    )

    assert result.urgency == SafetyUrgency.ROUTINE
    assert result.blocked is False