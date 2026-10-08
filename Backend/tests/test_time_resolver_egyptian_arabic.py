from __future__ import annotations

import pytest

from medmind.resolvers.time import (
    resolve_time_candidates,
)
import medmind.resolvers.time as time_resolver

@pytest.mark.parametrize(
    (
        "value",
        "expected",
    ),
    [
        (
            "الساعة خمسة",
            ["05:00", "17:00"],
        ),
        (
            "خمسة",
            ["05:00", "17:00"],
        ),
        (
            "خمسة العصر",
            ["17:00"],
        ),
        (
            "الساعة خمسة العصر",
            ["17:00"],
        ),
        (
            "خمسة ونص",
            ["05:30", "17:30"],
        ),
        (
            "الساعة خمسة ونص",
            ["05:30", "17:30"],
        ),
        (
            "ستة بالليل",
            ["18:00"],
        ),
        (
            "سبعة الصبح",
            ["07:00"],
        ),
        (
            "اتناشر",
            ["12:00", "00:00"],
        ),
        (
            "اتناشر ونص",
            ["12:30", "00:30"],
        ),
    ],
)
def test_egyptian_spoken_times(
    value: str,
    expected: list[str],
) -> None:

    assert (
        resolve_time_candidates(
            value
        )
        == expected
    )


@pytest.mark.parametrize(
    (
        "value",
        "expected",
    ),
    [
        (
            "5",
            ["05:00", "17:00"],
        ),
        (
            "5 العصر",
            ["17:00"],
        ),
        (
            "17:00",
            ["17:00"],
        ),
        (
            "1 ونص",
            ["01:30", "13:30"],
        ),
        (
            "2 العصر",
            ["14:00"],
        ),
    ],
)
def test_existing_numeric_time_support(
    value: str,
    expected: list[str],
) -> None:

    assert (
        resolve_time_candidates(
            value
        )
        == expected
    )

@pytest.mark.parametrize(
    (
        "value",
        "expected",
    ),
    [
        (
            "\u0627\u0644\u0633\u0627\u0639\u0629 \u062e\u0645\u0633\u0629",
            ["05:00", "17:00"],
        ),
        (
            "\u062e\u0645\u0633\u0629 \u0645\u0633\u0627\u0621",
            ["17:00"],
        ),
        (
            "17:00",
            ["17:00"],
        ),
    ],
)
def test_time_reply_candidates_accept_time_only_replies(
    value: str,
    expected: list[str],
) -> None:

    assert (
        time_resolver
        .resolve_time_reply_candidates(
            value
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [
        (
            "\u0647\u0644 \u0627\u0644\u062f\u0643\u062a\u0648\u0631 "
            "\u0645\u0648\u062c\u0648\u062f "
            "\u0627\u0644\u0633\u0627\u0639\u0629 "
            "\u062e\u0645\u0633\u0629\u061f"
        ),
        (
            "\u0647\u0644 \u0641\u064a\u0647 "
            "\u0645\u0648\u0639\u062f "
            "\u0627\u0644\u0633\u0627\u0639\u0629 "
            "\u062e\u0645\u0633\u0629\u061f"
        ),
    ],
)
def test_time_reply_candidates_reject_conversational_sentences(
    value: str,
) -> None:

    assert (
        time_resolver
        .resolve_time_reply_candidates(
            value
        )
        == []
    )    