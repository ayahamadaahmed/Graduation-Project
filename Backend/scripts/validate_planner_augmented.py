from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

TRAIN_GOLD_PATH = Path(
    "data/planner/medmind_planner_train_gold.jsonl"
)

VALIDATION_GOLD_PATH = Path(
    "data/planner/medmind_planner_validation_gold.jsonl"
)

TEST_GOLD_PATH = Path(
    "data/planner/medmind_planner_test_gold.jsonl"
)

AUGMENTED_PATH = Path(
    "data/planner/"
    "medmind_planner_train_augmented_candidates.jsonl"
)

REPORT_PATH = Path(
    "data/planner/"
    "medmind_planner_augmented_quality_report.json"
)


# ============================================================
# CONFIG
# ============================================================

EXPECTED_VARIATIONS_PER_SCENARIO = 10

CURRENT_MESSAGE_MARKER = (
    "CURRENT USER MESSAGE"
)

STRUCTURAL_PLAN_FIELDS = (
    "status",
    "capability",
    "confirmation",
    "ambiguity_kind",
    "correction_target",
    "reason",
)


# ============================================================
# FILE HELPERS
# ============================================================

def read_jsonl(
    path: Path,
) -> list[dict]:

    if not path.exists():
        raise FileNotFoundError(
            f"Missing dataset: {path}"
        )

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

                row = json.loads(
                    line
                )

            except json.JSONDecodeError as exc:

                raise ValueError(
                    f"Invalid JSON at "
                    f"{path}:{line_number}"
                ) from exc

            if not isinstance(
                row,
                dict,
            ):
                raise ValueError(
                    f"Row at {path}:{line_number} "
                    "must be a JSON object."
                )

            rows.append(
                row
            )

    return rows


# ============================================================
# MESSAGE / PLAN HELPERS
# ============================================================

def get_user_prompt(
    row: dict,
) -> str:

    messages = row.get(
        "messages"
    )

    if not isinstance(
        messages,
        list,
    ):
        raise ValueError(
            "messages must be a list."
        )

    if len(messages) != 2:
        raise ValueError(
            "Expected exactly 2 messages."
        )

    user_message = messages[0]

    if (
        not isinstance(
            user_message,
            dict,
        )
        or user_message.get("role")
        != "user"
    ):
        raise ValueError(
            "First message must be user."
        )

    content = user_message.get(
        "content"
    )

    if (
        not isinstance(content, str)
        or not content.strip()
    ):
        raise ValueError(
            "User prompt is empty."
        )

    return content


def get_plan(
    row: dict,
) -> dict:

    messages = row.get(
        "messages"
    )

    if (
        not isinstance(messages, list)
        or len(messages) != 2
    ):
        raise ValueError(
            "Expected exactly 2 messages."
        )

    assistant_message = messages[1]

    if (
        not isinstance(
            assistant_message,
            dict,
        )
        or assistant_message.get("role")
        != "assistant"
    ):
        raise ValueError(
            "Second message must be assistant."
        )

    content = assistant_message.get(
        "content"
    )

    if not isinstance(
        content,
        str,
    ):
        raise ValueError(
            "Assistant content must be text."
        )

    try:

        plan = json.loads(
            content
        )

    except json.JSONDecodeError as exc:

        raise ValueError(
            "Assistant ToolPlan is invalid JSON."
        ) from exc

    if not isinstance(
        plan,
        dict,
    ):
        raise ValueError(
            "ToolPlan must be a JSON object."
        )

    return plan


def split_current_message(
    planner_prompt: str,
) -> tuple[str, str]:

    if (
        CURRENT_MESSAGE_MARKER
        not in planner_prompt
    ):
        raise ValueError(
            "CURRENT USER MESSAGE marker "
            "was not found."
        )

    before, after = planner_prompt.split(
        CURRENT_MESSAGE_MARKER,
        1,
    )

    message = after.strip()

    if not message:
        raise ValueError(
            "Current user message is empty."
        )

    return (
        before,
        message,
    )


def normalize_message(
    text: str,
) -> str:

    return (
        " ".join(
            text
            .casefold()
            .strip()
            .split()
        )
    )


# ============================================================
# GOLD MAP
# ============================================================

def build_gold_map(
    rows: list[dict],
) -> dict[str, dict]:

    result: dict[
        str,
        dict,
    ] = {}

    for row in rows:

        scenario_id = row.get(
            "scenario_id"
        )

        if (
            not isinstance(
                scenario_id,
                str,
            )
            or not scenario_id
        ):
            raise ValueError(
                "Gold row has invalid scenario_id."
            )

        if scenario_id in result:
            raise ValueError(
                "Duplicate Gold scenario_id: "
                f"{scenario_id}"
            )

        result[
            scenario_id
        ] = row

    return result


# ============================================================
# PLAN VALIDATION
# ============================================================

def validate_plan_against_gold(
    *,
    scenario_id: str,
    generated_plan: dict,
    gold_plan: dict,
) -> None:

    # --------------------------------------------------------
    # Behavioral labels MUST remain exactly Gold.
    # --------------------------------------------------------

    for field in STRUCTURAL_PLAN_FIELDS:

        generated_value = (
            generated_plan.get(
                field
            )
        )

        gold_value = (
            gold_plan.get(
                field
            )
        )

        if (
            generated_value
            != gold_value
        ):

            raise ValueError(
                f"{scenario_id}: "
                f"field {field!r} changed. "
                f"gold={gold_value!r} "
                f"generated="
                f"{generated_value!r}"
            )

    # --------------------------------------------------------
    # Argument key set MUST remain the same.
    #
    # Values may differ because teacher can change surface
    # date/time/name/etc.
    # --------------------------------------------------------

    gold_arguments = gold_plan.get(
        "arguments",
        {},
    )

    generated_arguments = (
        generated_plan.get(
            "arguments",
            {},
        )
    )

    if not isinstance(
        gold_arguments,
        dict,
    ):
        raise ValueError(
            f"{scenario_id}: "
            "Gold arguments are invalid."
        )

    if not isinstance(
        generated_arguments,
        dict,
    ):
        raise ValueError(
            f"{scenario_id}: "
            "Generated arguments are invalid."
        )

    gold_keys = set(
        gold_arguments.keys()
    )

    generated_keys = set(
        generated_arguments.keys()
    )

    if gold_keys != generated_keys:

        raise ValueError(
            f"{scenario_id}: "
            "argument keys changed. "
            f"gold={sorted(gold_keys)} "
            f"generated="
            f"{sorted(generated_keys)}"
        )

    # --------------------------------------------------------
    # Argument values must be usable strings.
    # --------------------------------------------------------

    for key, value in (
        generated_arguments.items()
    ):

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):

            raise ValueError(
                f"{scenario_id}: "
                f"invalid value for "
                f"argument {key!r}"
            )

    # --------------------------------------------------------
    # Ambiguous plans cannot contain arguments.
    # --------------------------------------------------------

    if (
        gold_plan.get("status")
        == "ambiguous"
        and generated_arguments
    ):

        raise ValueError(
            f"{scenario_id}: "
            "ambiguous variation contains "
            "arguments."
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    # ========================================================
    # LOAD DATASETS
    # ========================================================

    train_gold_rows = read_jsonl(
        TRAIN_GOLD_PATH
    )

    validation_gold_rows = read_jsonl(
        VALIDATION_GOLD_PATH
    )

    test_gold_rows = read_jsonl(
        TEST_GOLD_PATH
    )

    augmented_rows = read_jsonl(
        AUGMENTED_PATH
    )

    train_gold = build_gold_map(
        train_gold_rows
    )

    validation_gold = build_gold_map(
        validation_gold_rows
    )

    test_gold = build_gold_map(
        test_gold_rows
    )

    train_ids = set(
        train_gold.keys()
    )

    validation_ids = set(
        validation_gold.keys()
    )

    test_ids = set(
        test_gold.keys()
    )

    # ========================================================
    # GOLD SPLIT LEAKAGE CHECK
    # ========================================================

    if (
        train_ids
        & validation_ids
    ):

        raise RuntimeError(
            "Train/Validation Gold leakage."
        )

    if train_ids & test_ids:

        raise RuntimeError(
            "Train/Test Gold leakage."
        )

    if (
        validation_ids
        & test_ids
    ):

        raise RuntimeError(
            "Validation/Test Gold leakage."
        )

    # ========================================================
    # AUGMENTED COLLECTION STATE
    # ========================================================

    rows_by_scenario: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    variation_ids: set[
        str
    ] = set()

    duplicate_variation_ids: list[
        str
    ] = []

    gold_message_reuse: list[
        str
    ] = []

    query_mismatches: list[
        dict
    ] = []

    total_argument_rows = 0

    # --------------------------------------------------------
    # Detect identical FULL prompts with conflicting plans.
    # --------------------------------------------------------

    prompt_to_plan: dict[
        str,
        str,
    ] = {}

    # ========================================================
    # VALIDATE EVERY AUGMENTED ROW
    # ========================================================

    for row_number, row in enumerate(
        augmented_rows,
        start=1,
    ):

        scenario_id = row.get(
            "scenario_id"
        )

        variation_id = row.get(
            "variation_id"
        )

        source = row.get(
            "source"
        )

        # ----------------------------------------------------
        # IDs
        # ----------------------------------------------------

        if (
            not isinstance(
                scenario_id,
                str,
            )
            or not scenario_id
        ):

            raise ValueError(
                f"Row {row_number}: "
                "invalid scenario_id."
            )

        if scenario_id not in train_ids:

            if (
                scenario_id
                in validation_ids
                or scenario_id
                in test_ids
            ):

                raise RuntimeError(
                    f"DATA LEAKAGE: "
                    f"{scenario_id} belongs to "
                    "validation/test but appears "
                    "in augmented training data."
                )

            raise ValueError(
                f"Unknown augmented scenario: "
                f"{scenario_id}"
            )

        if (
            not isinstance(
                variation_id,
                str,
            )
            or not variation_id
        ):

            raise ValueError(
                f"{scenario_id}: "
                "invalid variation_id."
            )

        if (
            variation_id
            in variation_ids
        ):

            duplicate_variation_ids.append(
                variation_id
            )

        variation_ids.add(
            variation_id
        )

        if source != "teacher_generated":

            raise ValueError(
                f"{variation_id}: "
                "unexpected source."
            )

        # ----------------------------------------------------
        # Get generated content.
        # ----------------------------------------------------

        generated_prompt = (
            get_user_prompt(
                row
            )
        )

        generated_plan = get_plan(
            row
        )

        # ----------------------------------------------------
        # Gold reference.
        # ----------------------------------------------------

        gold_row = train_gold[
            scenario_id
        ]

        gold_prompt = get_user_prompt(
            gold_row
        )

        gold_plan = get_plan(
            gold_row
        )

        (
            generated_prefix,
            generated_message,
        ) = split_current_message(
            generated_prompt
        )

        (
            gold_prefix,
            gold_message,
        ) = split_current_message(
            gold_prompt
        )

        # ====================================================
        # PRODUCTION CONTEXT MUST NOT CHANGE
        #
        # Only CURRENT USER MESSAGE is allowed to change.
        # ====================================================

        if (
            generated_prefix
            != gold_prefix
        ):

            raise ValueError(
                f"{variation_id}: "
                "planner context/candidates/"
                "instructions changed."
            )

        # ====================================================
        # GENERATED MESSAGE
        # ====================================================

        if not generated_message.strip():

            raise ValueError(
                f"{variation_id}: "
                "empty generated message."
            )

        if (
            normalize_message(
                generated_message
            )
            ==
            normalize_message(
                gold_message
            )
        ):

            gold_message_reuse.append(
                variation_id
            )

        # ====================================================
        # PLAN PRESERVATION
        # ====================================================

        validate_plan_against_gold(
            scenario_id=scenario_id,
            generated_plan=(
                generated_plan
            ),
            gold_plan=(
                gold_plan
            ),
        )

        generated_arguments = (
            generated_plan.get(
                "arguments",
                {},
            )
        )

        if generated_arguments:

            total_argument_rows += 1

        # ====================================================
        # QUERY ARGUMENT CHECK
        #
        # For policy/knowledge queries the training target
        # should normally preserve the complete CURRENT
        # user message as query.
        # ====================================================

        if (
            "query"
            in generated_arguments
        ):

            query_value = (
                generated_arguments[
                    "query"
                ].strip()
            )

            if (
                query_value
                != generated_message.strip()
            ):

                query_mismatches.append(
                    {
                        "variation_id":
                            variation_id,
                        "message":
                            generated_message,
                        "query":
                            query_value,
                    }
                )

        # ====================================================
        # CONFLICTING IDENTICAL FULL PROMPT CHECK
        # ====================================================

        serialized_plan = json.dumps(
            generated_plan,
            ensure_ascii=False,
            sort_keys=True,
        )

        if (
            generated_prompt
            in prompt_to_plan
        ):

            previous_plan = (
                prompt_to_plan[
                    generated_prompt
                ]
            )

            if (
                previous_plan
                != serialized_plan
            ):

                raise RuntimeError(
                    "Identical planner prompt "
                    "has conflicting ToolPlans: "
                    f"{variation_id}"
                )

        else:

            prompt_to_plan[
                generated_prompt
            ] = serialized_plan

        rows_by_scenario[
            scenario_id
        ].append(
            row
        )

    # ========================================================
    # DUPLICATE VARIATION IDS
    # ========================================================

    if duplicate_variation_ids:

        raise RuntimeError(
            "Duplicate variation_ids found: "
            f"{sorted(set(duplicate_variation_ids))}"
        )

    # ========================================================
    # EVERY TRAIN GOLD SCENARIO MUST HAVE EXACTLY 10
    # ========================================================

    missing_scenarios: list[
        str
    ] = []

    wrong_counts: dict[
        str,
        int,
    ] = {}

    for scenario_id in sorted(
        train_ids
    ):

        count = len(
            rows_by_scenario.get(
                scenario_id,
                [],
            )
        )

        if count == 0:

            missing_scenarios.append(
                scenario_id
            )

        if (
            count
            != EXPECTED_VARIATIONS_PER_SCENARIO
        ):

            wrong_counts[
                scenario_id
            ] = count

    if missing_scenarios:

        raise RuntimeError(
            "Train scenarios missing "
            "augmentation: "
            f"{missing_scenarios}"
        )

    if wrong_counts:

        raise RuntimeError(
            "Invalid variation counts: "
            f"{wrong_counts}"
        )

    # ========================================================
    # DUPLICATES WITHIN EACH SCENARIO
    # ========================================================

    duplicate_messages: dict[
        str,
        list[str],
    ] = {}

    for (
        scenario_id,
        scenario_rows,
    ) in rows_by_scenario.items():

        seen: set[
            str
        ] = set()

        duplicates: list[
            str
        ] = []

        for row in scenario_rows:

            prompt = get_user_prompt(
                row
            )

            _, message = (
                split_current_message(
                    prompt
                )
            )

            normalized = (
                normalize_message(
                    message
                )
            )

            if normalized in seen:

                duplicates.append(
                    message
                )

            seen.add(
                normalized
            )

        if duplicates:

            duplicate_messages[
                scenario_id
            ] = duplicates

    if duplicate_messages:

        raise RuntimeError(
            "Duplicate generated messages "
            "inside scenarios: "
            f"{duplicate_messages}"
        )

    # ========================================================
    # VARIATION ID SHAPE
    # ========================================================

    invalid_variation_id_sets: dict[
        str,
        dict,
    ] = {}

    for (
        scenario_id,
        scenario_rows,
    ) in rows_by_scenario.items():

        actual = {
            row["variation_id"]
            for row in scenario_rows
        }

        expected = {
            (
                f"{scenario_id}-aug-"
                f"{index:02d}"
            )
            for index in range(
                1,
                EXPECTED_VARIATIONS_PER_SCENARIO
                + 1,
            )
        }

        if actual != expected:

            invalid_variation_id_sets[
                scenario_id
            ] = {
                "missing": sorted(
                    expected - actual
                ),
                "unexpected": sorted(
                    actual - expected
                ),
            }

    if invalid_variation_id_sets:

        raise RuntimeError(
            "Variation ID sequence error: "
            f"{invalid_variation_id_sets}"
        )

    # ========================================================
    # QUERY LABEL QUALITY
    # ========================================================

    if query_mismatches:

        print()
        print(
            "QUERY_MISMATCHES="
            f"{len(query_mismatches)}"
        )

        for mismatch in (
            query_mismatches[:10]
        ):

            print(
                mismatch
            )

        raise RuntimeError(
            "Query argument does not match "
            "generated CURRENT USER MESSAGE."
        )

    # ========================================================
    # REPORT COUNTS
    # ========================================================

    plans = [
        get_plan(row)
        for row in augmented_rows
    ]

    status_counts = Counter(
        plan.get("status")
        for plan in plans
    )

    capability_counts = Counter(
        plan.get("capability")
        for plan in plans
        if (
            plan.get("status")
            == "selected"
        )
    )

    confirmation_counts = Counter(
        plan.get("confirmation")
        for plan in plans
    )

    ambiguity_counts = Counter(
        plan.get("ambiguity_kind")
        for plan in plans
    )

    correction_counts = Counter(
        plan.get("correction_target")
        for plan in plans
    )

    report = {
        "quality_gate": "PASS",
        "train_gold_scenarios":
            len(train_gold_rows),
        "augmented_rows":
            len(augmented_rows),
        "augmented_scenarios":
            len(rows_by_scenario),
        "variations_per_scenario":
            EXPECTED_VARIATIONS_PER_SCENARIO,
        "validation_gold_scenarios":
            len(validation_gold_rows),
        "test_gold_scenarios":
            len(test_gold_rows),
        "split_leakage": 0,
        "duplicate_variation_ids": 0,
        "duplicate_messages_within_scenario": 0,
        "query_mismatches": 0,
        "gold_message_reuse_count":
            len(gold_message_reuse),
        "rows_with_arguments":
            total_argument_rows,
        "status": dict(
            status_counts
        ),
        "capabilities": dict(
            sorted(
                capability_counts.items()
            )
        ),
        "confirmation": {
            str(key): value
            for key, value
            in confirmation_counts.items()
        },
        "ambiguity": {
            str(key): value
            for key, value
            in ambiguity_counts.items()
        },
        "corrections": {
            str(key): value
            for key, value
            in correction_counts.items()
        },
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print()
    print(
        "QUALITY_GATE=PASS"
    )

    print(
        f"TRAIN_GOLD_SCENARIOS="
        f"{len(train_gold_rows)}"
    )

    print(
        f"AUGMENTED_ROWS="
        f"{len(augmented_rows)}"
    )

    print(
        f"AUGMENTED_SCENARIOS="
        f"{len(rows_by_scenario)}"
    )

    print(
        "SPLIT_LEAKAGE=0"
    )

    print(
        "DUPLICATE_VARIATION_IDS=0"
    )

    print(
        "DUPLICATE_MESSAGES_WITHIN_SCENARIO=0"
    )

    print(
        "QUERY_MISMATCHES=0"
    )

    print(
        f"GOLD_MESSAGE_REUSE="
        f"{len(gold_message_reuse)}"
    )

    print(
        f"REPORT={REPORT_PATH}"
    )


if __name__ == "__main__":
    main()