from __future__ import annotations

import asyncio
import json

from pathlib import Path

from rag.service import (
    create_rag_service,
)


EVALUATION_FILE = Path(
    "tests/data/rag_evaluation_cases.jsonl"
)


def load_cases() -> list[dict]:

    cases = []

    with EVALUATION_FILE.open(
        "r",
        encoding="utf-8-sig",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            normalized = (
                line.strip()
            )

            if not normalized:
                continue

            try:

                cases.append(
                    json.loads(
                        normalized
                    )
                )

            except json.JSONDecodeError as exc:

                raise RuntimeError(
                    f"Invalid JSON on line "
                    f"{line_number}."
                ) from exc

    return cases


async def main() -> None:

    cases = (
        load_cases()
    )

    rag_service = (
        create_rag_service()
    )

    passed = 0
    failed = 0

    print(
        f"RAG evaluation cases: "
        f"{len(cases)}"
    )

    print(
        "=" * 70
    )

    for case in cases:

        result = await (
            rag_service.answer(
                tenant_id=
                    case["tenant_id"],

                query=
                    case["query"],

                language=
                    case["language"],
            )
        )

        expected_supported = bool(
            case[
                "expected_supported"
            ]
        )

        support_ok = (
            result.supported
            ==
            expected_supported
        )

        returned_tenants = {
            chunk.get(
                "tenant_id"
            )
            for chunk
            in result.retrieved_chunks
        }

        tenant_ok = (
            not returned_tenants
            or
            returned_tenants
            == {
                case["tenant_id"]
            }
        )

        case_passed = (
            support_ok
            and
            tenant_ok
        )

        if case_passed:

            passed += 1
            status = "PASS"

        else:

            failed += 1
            status = "FAIL"

        print()
        print(
            f"[{status}] "
            f"{case['id']}"
        )

        print(
            "Tenant:",
            case["tenant_id"],
        )

        print(
            "Query:",
            case["query"],
        )

        print(
            "Expected supported:",
            expected_supported,
        )

        print(
            "Actual supported:",
            result.supported,
        )

        print(
            "Returned tenants:",
            returned_tenants,
        )

        print(
            "Sources:",
            len(
                result.sources
            ),
        )

        print(
            "Supporting chunks:",
            len(
                result.retrieved_chunks
            ),
        )

        print(
            "Answer:",
            result.answer,
        )

    total = (
        passed
        +
        failed
    )

    accuracy = (
        passed
        /
        total
        *
        100
        if total
        else 0.0
    )

    print()
    print(
        "=" * 70
    )

    print(
        "PASSED:",
        passed,
    )

    print(
        "FAILED:",
        failed,
    )

    print(
        "TOTAL:",
        total,
    )

    print(
        "PASS RATE:",
        f"{accuracy:.2f}%",
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )