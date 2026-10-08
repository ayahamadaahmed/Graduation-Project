from __future__ import annotations

import json
from pathlib import Path


DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "understanding"
    / "cases.jsonl"
)


VALID_STATUSES = {
    "selected",
    "ambiguous",
}

VALID_CONFIRMATIONS = {
    "yes",
    "no",
    "unknown",
}

VALID_AMBIGUITY_KINDS = {
    "needs_clarification",
    "candidate_miss",
    None,
}


def load_cases():

    cases = []

    with DATASET_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            stripped = line.strip()

            if not stripped:
                continue

            try:
                case = json.loads(
                    stripped
                )

            except json.JSONDecodeError as exc:

                raise AssertionError(
                    f"Invalid JSON on line "
                    f"{line_number}"
                ) from exc

            cases.append(
                case
            )

    return cases


def test_understanding_eval_dataset_exists():

    assert DATASET_PATH.exists()


def test_understanding_eval_dataset_has_enough_cases():

    cases = load_cases()

    assert len(cases) >= 30


def test_understanding_eval_case_ids_are_unique():

    cases = load_cases()

    ids = [
        case["id"]
        for case in cases
    ]

    assert len(ids) == len(
        set(ids)
    )


def test_understanding_eval_cases_have_required_fields():

    for case in load_cases():

        assert case.get("id")
        assert isinstance(
            case.get("message"),
            str,
        )

        assert isinstance(
            case.get("context"),
            dict,
        )

        assert isinstance(
            case.get("expected"),
            dict,
        )

        assert isinstance(
            case.get("tags"),
            list,
        )


def test_expected_status_contract():

    for case in load_cases():

        expected = case["expected"]

        assert (
            expected["status"]
            in VALID_STATUSES
        )

        if (
            expected["status"]
            == "selected"
        ):

            assert expected.get(
                "capability"
            )

        else:

            assert (
                expected.get(
                    "capability"
                )
                is None
            )


def test_expected_confirmation_contract():

    for case in load_cases():

        confirmation = (
            case["expected"].get(
                "confirmation",
                "unknown",
            )
        )

        assert (
            confirmation
            in VALID_CONFIRMATIONS
        )


def test_expected_ambiguity_contract():

    for case in load_cases():

        ambiguity_kind = (
            case["expected"].get(
                "ambiguity_kind"
            )
        )

        assert (
            ambiguity_kind
            in VALID_AMBIGUITY_KINDS
        )