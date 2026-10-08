from medmind.diagnostic_explanation import (
    SafeDiagnosticExplanationService,
)


def make_service():
    return SafeDiagnosticExplanationService()


def test_radiology_english_preserves_model_output():
    service = make_service()

    reply = service.explain_radiology(
        result={
            "modality": "brain_mri",
            "classification": "pituitary",
            "confidence": 0.86718768,
            "limitations": [],
        },
        language="en",
    )

    assert "brain MRI" in reply
    assert "'pituitary'" in reply
    assert "0.86718768" in reply
    assert "not a confirmed diagnosis" in reply


def test_radiology_arabic_preserves_model_output():
    service = make_service()

    reply = service.explain_radiology(
        result={
            "modality": "kidney_ct",
            "classification": "normal",
            "confidence": 0.60344005,
            "limitations": [],
        },
        language="ar",
    )

    assert "الأشعة المقطعية للكلى" in reply
    assert "طبيعي (normal)" in reply
    assert "60.3%" in reply
    assert "مش تشخيص نهائي" in reply


def test_radiology_missing_classification_fails_safe():
    service = make_service()

    reply = service.explain_radiology(
        result={
            "modality": "chest_xray",
            "classification": None,
            "confidence": None,
            "limitations": [],
        },
        language="en",
    )

    assert "could not be reported safely" in reply
    assert "qualified clinician" in reply


def test_pathology_english_preserves_abnormal_values():
    service = make_service()

    reply = service.explain_pathology(
        result={
            "document_type": "cbc",
            "unreadable_fields": [],
            "results": [
                {
                    "raw_name": "RBC",
                    "canonical_name": "rbc",
                    "value": 3.3,
                    "unit": "10^6/uL",
                    "reference_text": "3.5-5.50",
                    "flag": "low",
                    "mapping_status": "mapped",
                },
                {
                    "raw_name": "PLT",
                    "canonical_name": "platelets",
                    "value": 256.0,
                    "unit": "10^3/uL",
                    "reference_text": "150-450",
                    "flag": "normal",
                    "mapping_status": "mapped",
                },
            ],
        },
        language="en",
    )

    assert "RBC" in reply
    assert "3.3" in reply
    assert "10^6/uL" in reply
    assert "3.5-5.50" in reply
    assert "low" in reply
    assert "PLT:" not in reply
    assert "do not establish a diagnosis" in reply


def test_pathology_arabic_preserves_abnormal_values():
    service = make_service()

    reply = service.explain_pathology(
        result={
            "document_type": "cbc",
            "unreadable_fields": [],
            "results": [
                {
                    "raw_name": "HCT",
                    "canonical_name": "hematocrit",
                    "value": 36.0,
                    "unit": "%",
                    "reference_text": "37.0-50.0",
                    "flag": "low",
                    "mapping_status": "mapped",
                },
            ],
        },
        language="ar",
    )

    assert "HCT" in reply
    assert "36.0" in reply
    assert "%" in reply
    assert "37.0-50.0" in reply
    assert "منخفض" in reply
    assert "مش تعتبر تشخيصًا طبيًا" in reply


def test_pathology_all_normal_does_not_invent_problem():
    service = make_service()

    reply = service.explain_pathology(
        result={
            "document_type": "glycemic",
            "unreadable_fields": [],
            "results": [
                {
                    "raw_name": "HbA1c",
                    "value": 4.9,
                    "unit": "%",
                    "reference_text": "4.0-5.6",
                    "flag": "normal",
                    "mapping_status": "mapped",
                },
            ],
        },
        language="en",
    )

    assert (
        "No mapped result was flagged as low or high."
        in reply
    )
    assert "HbA1c:" not in reply


def test_pathology_unknown_result_is_not_interpreted():
    service = make_service()

    reply = service.explain_pathology(
        result={
            "document_type": "cbc",
            "unreadable_fields": [],
            "results": [
                {
                    "raw_name": "Unknown Marker",
                    "value": 10.0,
                    "unit": None,
                    "reference_text": None,
                    "flag": "unknown",
                    "mapping_status": "unmapped",
                },
            ],
        },
        language="en",
    )

    assert "Some results could not be safely evaluated" in reply
    assert "Unknown Marker" in reply


def test_pathology_reports_unreadable_fields():
    service = make_service()

    reply = service.explain_pathology(
        result={
            "document_type": "cbc",
            "unreadable_fields": [
                "WBC reference range",
            ],
            "results": [],
        },
        language="en",
    )

    assert "Unreadable fields" in reply
    assert "WBC reference range" in reply
