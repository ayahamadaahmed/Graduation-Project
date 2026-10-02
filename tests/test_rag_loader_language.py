from rag.loader import _detect_language


def test_arabic_dominant_text_with_english_terms_is_arabic():
    text = """
    معامل ألفا من أكبر معامل التحاليل في مصر.
    تقدم المعامل خدمات الفحوصات والتحاليل الطبية.
    المعمل حاصل على اعتماد GAHAR و EGAC.
    """

    assert _detect_language(text) == "ar"


def test_english_text_is_english():
    text = """
    The clinic provides dermatology services
    for adults and children.
    """

    assert _detect_language(text) == "en"


def test_balanced_bilingual_text_is_mixed():
    text = """
    العيادة تقدم خدمات الجلدية
    The clinic provides dermatology services
    """

    assert _detect_language(text) == "mixed"