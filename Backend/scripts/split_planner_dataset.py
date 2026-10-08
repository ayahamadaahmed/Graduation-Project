from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

SOURCE_PATH = Path(
    "data/planner/medmind_planner_canonical.jsonl"
)

TRAIN_PATH = Path(
    "data/planner/medmind_planner_train_gold.jsonl"
)

VALIDATION_PATH = Path(
    "data/planner/medmind_planner_validation_gold.jsonl"
)

TEST_PATH = Path(
    "data/planner/medmind_planner_test_gold.jsonl"
)

MANIFEST_PATH = Path(
    "data/planner/medmind_planner_split_manifest.json"
)


# ============================================================
# HELPERS
# ============================================================

def read_jsonl(
    path: Path,
) -> list[dict]:

    rows: list[dict] = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            line = line.strip()

            if not line:
                continue

            try:
                rows.append(
                    json.loads(
                        line
                    )
                )

            except json.JSONDecodeError as exc:

                raise ValueError(
                    f"Invalid JSON at "
                    f"{path}:{line_number}"
                ) from exc

    return rows


def write_jsonl(
    path: Path,
    rows: list[dict],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:

        for row in rows:

            file.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )


def get_plan(
    row: dict,
) -> dict:

    messages = row.get(
        "messages",
        []
    )

    if len(messages) != 2:
        raise ValueError(
            "Expected exactly 2 messages "
            f"for {row.get('scenario_id')}"
        )

    assistant_message = messages[1]

    if (
        assistant_message.get("role")
        != "assistant"
    ):
        raise ValueError(
            "Second message must be assistant "
            f"for {row.get('scenario_id')}"
        )

    return json.loads(
        assistant_message["content"]
    )


def sort_rows(
    rows: list[dict],
) -> list[dict]:

    return sorted(
        rows,
        key=lambda row: row["scenario_id"],
    )


# ============================================================
# SPLIT STATE
# ============================================================

def main() -> None:

    rows = read_jsonl(
        SOURCE_PATH
    )

    if not rows:
        raise ValueError(
            "Canonical dataset is empty."
        )

    # --------------------------------------------------------
    # Validate unique IDs
    # --------------------------------------------------------

    scenario_ids = [
        row["scenario_id"]
        for row in rows
    ]

    if (
        len(scenario_ids)
        != len(set(scenario_ids))
    ):
        raise ValueError(
            "Duplicate scenario_id found."
        )

    # --------------------------------------------------------
    # Split containers
    # --------------------------------------------------------

    splits: dict[
        str,
        list[dict],
    ] = {
        "train": [],
        "validation": [],
        "test": [],
    }

    assigned_ids: set[str] = set()

    # ========================================================
    # ASSIGN FUNCTION
    # ========================================================

    def assign(
        row: dict,
        split_name: str,
    ) -> None:

        scenario_id = row[
            "scenario_id"
        ]

        if scenario_id in assigned_ids:
            return

        splits[
            split_name
        ].append(
            row
        )

        assigned_ids.add(
            scenario_id
        )

    # ========================================================
    # 1. CORRECTION TARGETS
    #
    # We currently have 3 canonical examples for each
    # correction target.
    #
    # Put one in:
    # train
    # validation
    # test
    # ========================================================

    correction_groups: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    for row in rows:

        plan = get_plan(
            row
        )

        correction_target = plan.get(
            "correction_target"
        )

        if correction_target is not None:

            correction_groups[
                correction_target
            ].append(
                row
            )

    for target, group in sorted(
        correction_groups.items()
    ):

        group = sort_rows(
            group
        )

        destinations = [
            "train",
            "validation",
            "test",
        ]

        for index, row in enumerate(
            group
        ):

            destination = (
                destinations[
                    index % len(destinations)
                ]
            )

            assign(
                row,
                destination,
            )

    # ========================================================
    # 2. CONFIRMATION YES / NO
    #
    # Same idea:
    # one canonical example in each split.
    # ========================================================

    confirmation_groups: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    for row in rows:

        if (
            row["scenario_id"]
            in assigned_ids
        ):
            continue

        plan = get_plan(
            row
        )

        confirmation = plan.get(
            "confirmation"
        )

        if confirmation in {
            "yes",
            "no",
        }:

            confirmation_groups[
                confirmation
            ].append(
                row
            )

    for confirmation, group in sorted(
        confirmation_groups.items()
    ):

        group = sort_rows(
            group
        )

        destinations = [
            "train",
            "validation",
            "test",
        ]

        for index, row in enumerate(
            group
        ):

            destination = (
                destinations[
                    index % len(destinations)
                ]
            )

            assign(
                row,
                destination,
            )

    # ========================================================
    # 3. AMBIGUITY
    #
    # needs_clarification:
    # distribute across all splits.
    #
    # candidate_miss currently has fewer examples,
    # so make sure train and test see it.
    # ========================================================

    ambiguity_groups: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    for row in rows:

        if (
            row["scenario_id"]
            in assigned_ids
        ):
            continue

        plan = get_plan(
            row
        )

        if (
            plan.get("status")
            == "ambiguous"
        ):

            ambiguity_kind = plan.get(
                "ambiguity_kind"
            )

            ambiguity_groups[
                ambiguity_kind
            ].append(
                row
            )

    for ambiguity_kind, group in sorted(
        ambiguity_groups.items()
    ):

        group = sort_rows(
            group
        )

        if (
            ambiguity_kind
            == "candidate_miss"
        ):
            destinations = [
                "train",
                "test",
                "validation",
            ]

        else:
            destinations = [
                "train",
                "validation",
                "test",
            ]

        for index, row in enumerate(
            group
        ):

            destination = (
                destinations[
                    index % len(destinations)
                ]
            )

            assign(
                row,
                destination,
            )

    # ========================================================
    # 4. NORMAL SELECTED CASES
    #
    # Group by capability.
    #
    # We want:
    # - every capability represented in train
    # - evaluation representation whenever enough examples
    # - remaining examples stay mainly in train
    # ========================================================

    capability_groups: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    for row in rows:

        if (
            row["scenario_id"]
            in assigned_ids
        ):
            continue

        plan = get_plan(
            row
        )

        capability = plan.get(
            "capability"
        )

        if capability is None:
            continue

        capability_groups[
            capability
        ].append(
            row
        )

    for capability, group in sorted(
        capability_groups.items()
    ):

        group = sort_rows(
            group
        )

        # ----------------------------------------------------
        # First unassigned example -> train
        # ----------------------------------------------------

        if len(group) >= 1:
            assign(
                group[0],
                "train",
            )

        # ----------------------------------------------------
        # Second -> test
        #
        # Test is more important than validation for very
        # small capability groups.
        # ----------------------------------------------------

        if len(group) >= 2:
            assign(
                group[1],
                "test",
            )

        # ----------------------------------------------------
        # Third -> validation
        # ----------------------------------------------------

        if len(group) >= 3:
            assign(
                group[2],
                "validation",
            )

        # ----------------------------------------------------
        # Remaining -> mostly train
        #
        # Add occasional validation/test examples so larger
        # capabilities are not evaluated on one row only.
        # ----------------------------------------------------

        remaining = group[
            3:
        ]

        for index, row in enumerate(
            remaining
        ):

            cycle = index % 6

            if cycle == 4:
                destination = "validation"

            elif cycle == 5:
                destination = "test"

            else:
                destination = "train"

            assign(
                row,
                destination,
            )

    # ========================================================
    # 5. SAFETY CHECK
    # ========================================================

    if len(assigned_ids) != len(rows):

        missing = sorted(
            set(scenario_ids)
            - assigned_ids
        )

        raise RuntimeError(
            "Some scenarios were not assigned: "
            f"{missing}"
        )

    train_rows = sort_rows(
        splits["train"]
    )

    validation_rows = sort_rows(
        splits["validation"]
    )

    test_rows = sort_rows(
        splits["test"]
    )

    # --------------------------------------------------------
    # No overlap
    # --------------------------------------------------------

    train_ids = {
        row["scenario_id"]
        for row in train_rows
    }

    validation_ids = {
        row["scenario_id"]
        for row in validation_rows
    }

    test_ids = {
        row["scenario_id"]
        for row in test_rows
    }

    if (
        train_ids & validation_ids
        or train_ids & test_ids
        or validation_ids & test_ids
    ):
        raise RuntimeError(
            "Split leakage detected."
        )

    all_split_ids = (
        train_ids
        | validation_ids
        | test_ids
    )

    if all_split_ids != set(
        scenario_ids
    ):
        raise RuntimeError(
            "Split does not cover all scenarios."
        )

    # ========================================================
    # WRITE FILES
    # ========================================================

    write_jsonl(
        TRAIN_PATH,
        train_rows,
    )

    write_jsonl(
        VALIDATION_PATH,
        validation_rows,
    )

    write_jsonl(
        TEST_PATH,
        test_rows,
    )

    # ========================================================
    # MANIFEST
    # ========================================================

    manifest = {
        "source": str(
            SOURCE_PATH
        ),
        "total_scenarios": len(
            rows
        ),
        "splits": {
            "train": [
                row["scenario_id"]
                for row in train_rows
            ],
            "validation": [
                row["scenario_id"]
                for row in validation_rows
            ],
            "test": [
                row["scenario_id"]
                for row in test_rows
            ],
        },
    }

    with MANIFEST_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            manifest,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # ========================================================
    # REPORT
    # ========================================================

    print(
        f"TOTAL={len(rows)}"
    )

    print(
        f"TRAIN={len(train_rows)}"
    )

    print(
        f"VALIDATION={len(validation_rows)}"
    )

    print(
        f"TEST={len(test_rows)}"
    )

    print(
        "OVERLAP=0"
    )

    print(
        f"MANIFEST={MANIFEST_PATH}"
    )

    # --------------------------------------------------------
    # Behavior reports
    # --------------------------------------------------------

    for split_name, split_rows in [
        (
            "TRAIN",
            train_rows,
        ),
        (
            "VALIDATION",
            validation_rows,
        ),
        (
            "TEST",
            test_rows,
        ),
    ]:

        plans = [
            get_plan(row)
            for row in split_rows
        ]

        status_counts = Counter(
            plan["status"]
            for plan in plans
        )

        confirmation_counts = Counter(
            plan["confirmation"]
            for plan in plans
        )

        correction_counts = Counter(
            plan["correction_target"]
            for plan in plans
        )

        capability_counts = Counter(
            plan["capability"]
            for plan in plans
            if (
                plan["status"]
                == "selected"
            )
        )

        print()
        print(
            f"=== {split_name} ==="
        )

        print(
            "status=",
            dict(status_counts),
        )

        print(
            "confirmation=",
            dict(
                confirmation_counts
            ),
        )

        print(
            "corrections=",
            dict(
                correction_counts
            ),
        )

        print(
            "capabilities=",
            dict(
                sorted(
                    capability_counts.items()
                )
            ),
        )


if __name__ == "__main__":
    main()