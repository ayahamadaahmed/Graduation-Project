from datetime import date

from medmind.resolvers.date import (
    resolve_date,
)


# Sunday
TODAY = date(
    2026,
    9,
    6,
)


def test_resolves_egyptian_monday():

    assert resolve_date(
        "الاتنين",
        today=TODAY,
    ) == date(
        2026,
        9,
        7,
    )


def test_resolves_standard_arabic_monday():

    assert resolve_date(
        "الاثنين",
        today=TODAY,
    ) == date(
        2026,
        9,
        7,
    )


def test_resolves_egyptian_tuesday():

    assert resolve_date(
        "التلات",
        today=TODAY,
    ) == date(
        2026,
        9,
        8,
    )


def test_resolves_arabic_friday():

    assert resolve_date(
        "الجمعة",
        today=TODAY,
    ) == date(
        2026,
        9,
        11,
    )


def test_resolves_arabic_saturday():

    assert resolve_date(
        "السبت",
        today=TODAY,
    ) == date(
        2026,
        9,
        12,
    )


def test_non_date_text_returns_none():

    assert resolve_date(
        "الساعة خمسة",
        today=TODAY,
    ) is None