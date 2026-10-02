from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


# ============================================================
# PATHS
# ============================================================

INPUT_PATH = Path(
    "data/planner/medmind_planner_train_gold.jsonl"
)

OUTPUT_PATH = Path(
    "data/planner/"
    "medmind_planner_train_augmented_candidates.jsonl"
)


# ============================================================
# CONFIG
# ============================================================

VARIATIONS_PER_SCENARIO = 10

MAX_SCENARIO_ATTEMPTS = 3

DEFAULT_TEACHER_MODEL = "gpt-4.1"


# ============================================================
# FILE HELPERS
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


def append_jsonl(
    path: Path,
    row: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:

        file.write(
            json.dumps(
                row,
                ensure_ascii=False,
            )
            + "\n"
        )


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


# ============================================================
# EXTRACT ORIGINAL MESSAGE
# ============================================================

def extract_current_message(
    planner_prompt: str,
) -> str:

    marker = (
        "CURRENT USER MESSAGE"
    )

    if marker not in planner_prompt:

        raise ValueError(
            "CURRENT USER MESSAGE marker "
            "was not found."
        )

    return (
        planner_prompt
        .split(
            marker,
            1,
        )[1]
        .strip()
    )


# ============================================================
# REPLACE MESSAGE IN PRODUCTION PROMPT
# ============================================================

def replace_current_message(
    planner_prompt: str,
    new_message: str,
) -> str:

    marker = (
        "CURRENT USER MESSAGE"
    )

    if marker not in planner_prompt:

        raise ValueError(
            "CURRENT USER MESSAGE marker "
            "was not found."
        )

    before, _ = planner_prompt.split(
        marker,
        1,
    )

    return (
        f"{before}"
        f"{marker}\n\n"
        f"{new_message}"
    ).strip()


# ============================================================
# TEACHER PROMPT
# ============================================================

def build_teacher_prompt(
    *,
    scenario_id: str,
    original_message: str,
    expected_plan: dict,
) -> str:

    return f"""
You are generating training utterance variations for
MedMind, an Egyptian Arabic healthcare appointment assistant.

SCENARIO ID
{scenario_id}

ORIGINAL USER MESSAGE
{original_message}

GOLD TOOL PLAN
{json.dumps(expected_plan, ensure_ascii=False)}

Generate exactly {VARIATIONS_PER_SCENARIO} realistic variations
of the CURRENT USER MESSAGE.

The meaning and requested operation MUST stay exactly the same
as the gold example.


LANGUAGE DISTRIBUTION

Generate a useful mixture of:

- Egyptian Arabic
- casual Egyptian Arabic
- short spoken/voice-style Egyptian Arabic
- natural wording variation
- light ASR-like/noisy wording
- Arabizi when safe
- Arabic + English code-switching when natural


CRITICAL LABEL RULES

1. Do NOT change the requested operation.

2. Do NOT turn an informational question into an action,
or an action into an informational question.

3. Preserve confirmation meaning exactly:
yes stays yes,
no stays no,
unknown stays unknown.

4. Preserve ambiguity meaning exactly.

5. Preserve correction_target meaning exactly.

6. Do not introduce new medical facts.

7. Do not use real personal information.

8. Appointment references and national IDs must remain
synthetic.

9. Every generated message MUST be different from every
other generated message.

10. Do not generate trivial duplicates that differ only by
punctuation.


ARGUMENT RULES

The GOLD TOOL PLAN contains the turn-delta arguments.

For each generated variation, provide the exact argument
values that should be extracted from THAT generated message.

Do not add argument keys that are not present in the gold
plan.

You MAY change the surface value only when necessary to make
the variation natural.


EXAMPLE 1

Original:
"بكرة"

Variation:
"طب نخليها يوم الجمعة"

Then:

date_text = "يوم الجمعة"


EXAMPLE 2

Original:
"الساعة ستة"

Variation:
"خليها الساعة سبعة"

Then:

time_text = "الساعة سبعة"


QUERY ARGUMENTS

For query arguments such as:

knowledge.search
provider.get_policy

the query value should normally equal the complete generated
user message.


EMPTY ARGUMENTS

For cases with empty arguments:
keep arguments empty.


CORRECTION TARGET

For correction_target examples where the user says a field
is wrong but does NOT supply the replacement value:

do NOT introduce a replacement value.

CORRECTION TARGET SEMANTIC RULES

When correction_target = "time":
- Every generated message must clearly refer to time only.
- Use wording such as:
  الوقت
  الساعة
  وقت الحجز
  الساعة اللي اتقالت
- Do NOT use generic "ميعاد" or "معاد" alone,
  because that can mean the whole appointment schedule.

When correction_target = "schedule":
- The message may refer to the appointment/date/schedule
  in general.
- Examples:
  الميعاد غلط
  اليوم مش صح
  تاريخ الحجز غلط
  عايز أعدل الميعاد
- Do NOT make it explicitly about clock time only.

When correction_target = "doctor":
the message must clearly refer to the doctor.

When correction_target = "phone":
the message must clearly refer to phone/mobile.

When correction_target = "patient_name":
the message must clearly refer to patient name.

When correction_target = "national_id":
the message must clearly refer to national ID.

AMBIGUITY

For ambiguous examples:

arguments MUST remain empty.


OUTPUT FORMAT

Return JSON only.

Use exactly this format:

{{
  "variations": [
    {{
      "message": "...",
      "arguments": {{}}
    }}
  ]
}}



There must be exactly {VARIATIONS_PER_SCENARIO} variations.

All {VARIATIONS_PER_SCENARIO} message strings must be unique.
""".strip()


# ============================================================
# PARSE TEACHER OUTPUT
# ============================================================

def parse_teacher_output(
    text: str,
) -> dict:

    value = text.strip()

    # --------------------------------------------------------
    # Remove optional markdown fence.
    # --------------------------------------------------------

    if value.startswith("```"):

        lines = value.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip()
            == "```"
        ):
            lines = lines[:-1]

        value = "\n".join(
            lines
        ).strip()

    try:

        parsed = json.loads(
            value
        )

    except json.JSONDecodeError as exc:

        raise ValueError(
            "Teacher did not return valid JSON."
        ) from exc

    if not isinstance(
        parsed,
        dict,
    ):

        raise ValueError(
            "Teacher output root must be "
            "a JSON object."
        )

    return parsed


# ============================================================
# NORMALIZE MESSAGE FOR DUPLICATE CHECK
# ============================================================

def normalize_message(
    message: str,
) -> str:

    # --------------------------------------------------------
    # Simple normalization only.
    #
    # We intentionally do NOT perform aggressive Arabic
    # normalization here because legitimate surface
    # variations should remain distinct.
    # --------------------------------------------------------

    return (
        " ".join(
            message
            .casefold()
            .strip()
            .split()
        )
    )


# ============================================================
# VALIDATE GENERATED VARIATION
# ============================================================

def validate_variation(
    *,
    variation: dict,
    gold_plan: dict,
) -> None:

    if not isinstance(
        variation,
        dict,
    ):

        raise ValueError(
            "Variation must be a JSON object."
        )

    message = variation.get(
        "message"
    )

    arguments = variation.get(
        "arguments"
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    if (
        not isinstance(
            message,
            str,
        )
        or not message.strip()
    ):

        raise ValueError(
            "Variation has invalid message."
        )

    # --------------------------------------------------------
    # ARGUMENTS
    # --------------------------------------------------------

    if not isinstance(
        arguments,
        dict,
    ):

        raise ValueError(
            "Variation arguments must be "
            "a dict."
        )

    gold_arguments = gold_plan.get(
        "arguments",
        {},
    )

    if not isinstance(
        gold_arguments,
        dict,
    ):

        raise ValueError(
            "Gold plan arguments must be "
            "a dict."
        )

    gold_argument_keys = set(
        gold_arguments.keys()
    )

    generated_argument_keys = set(
        arguments.keys()
    )

    # --------------------------------------------------------
    # Teacher may change argument VALUES,
    # but never argument KEYS.
    # --------------------------------------------------------

    if (
        generated_argument_keys
        != gold_argument_keys
    ):

        raise ValueError(
            "Generated argument keys changed. "
            f"gold="
            f"{sorted(gold_argument_keys)} "
            f"generated="
            f"{sorted(generated_argument_keys)}"
        )

    # --------------------------------------------------------
    # Values must be non-empty strings.
    # --------------------------------------------------------

    for key, value in arguments.items():

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):

            raise ValueError(
                f"Invalid value for argument: "
                f"{key}"
            )

    # --------------------------------------------------------
    # Ambiguous examples never contain arguments.
    # --------------------------------------------------------

    if (
        gold_plan.get("status")
        == "ambiguous"
        and arguments
    ):

        raise ValueError(
            "Ambiguous variation cannot "
            "contain arguments."
        )

    # --------------------------------------------------------
    # correction_target examples without replacement data
    # must stay argument-free when the gold case is empty.
    # --------------------------------------------------------

    correction_target = gold_plan.get(
        "correction_target"
    )

    if (
        correction_target is not None
        and not gold_arguments
        and arguments
    ):

        raise ValueError(
            "Correction-target variation "
            "introduced replacement data."
        )


# ============================================================
# BUILD AUGMENTED TRAIN ROW
# ============================================================

def build_augmented_row(
    *,
    gold_row: dict,
    variation_index: int,
    message: str,
    arguments: dict[str, str],
) -> dict:

    scenario_id = gold_row[
        "scenario_id"
    ]

    original_prompt = gold_row[
        "messages"
    ][0]["content"]

    gold_plan = json.loads(
        gold_row[
            "messages"
        ][1]["content"]
    )

    # --------------------------------------------------------
    # Keep all Gold behavioral labels.
    #
    # Only CURRENT-turn argument values may change.
    # --------------------------------------------------------

    generated_plan = dict(
        gold_plan
    )

    generated_plan[
        "arguments"
    ] = arguments

    generated_prompt = (
        replace_current_message(
            original_prompt,
            message,
        )
    )

    return {
        "scenario_id": scenario_id,
        "variation_id": (
            f"{scenario_id}-aug-"
            f"{variation_index:02d}"
        ),
        "source": "teacher_generated",
        "messages": [
            {
                "role": "user",
                "content": generated_prompt,
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    generated_plan,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    # ========================================================
    # CLI
    # ========================================================

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Only augment the first N "
            "Gold scenarios."
        ),
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete previous augmented output "
            "before generation."
        ),
    )

    args = parser.parse_args()

    if (
        args.limit is not None
        and args.limit <= 0
    ):

        raise ValueError(
            "--limit must be greater than 0."
        )

    # ========================================================
    # ENVIRONMENT
    # ========================================================

    load_dotenv(
        override=True
    )

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "OPENAI_API_KEY is missing."
        )

    # ========================================================
    # LOAD GOLD TRAIN ONLY
    # ========================================================

    if not INPUT_PATH.exists():

        raise FileNotFoundError(
            f"Gold train dataset not found: "
            f"{INPUT_PATH}"
        )

    gold_rows = read_jsonl(
        INPUT_PATH
    )

    if not gold_rows:

        raise RuntimeError(
            "Gold train dataset is empty."
        )

    if args.limit is not None:

        gold_rows = gold_rows[
            :args.limit
        ]

    # ========================================================
    # RESET
    # ========================================================

    if args.reset:

        OUTPUT_PATH.unlink(
            missing_ok=True
        )

    # ========================================================
    # RESUME EXISTING GENERATION
    # ========================================================

    existing_rows: list[dict] = []

    if OUTPUT_PATH.exists():

        existing_rows = read_jsonl(
            OUTPUT_PATH
        )

    # --------------------------------------------------------
    # Group current rows by scenario.
    # --------------------------------------------------------

    existing_by_scenario: dict[
        str,
        list[dict],
    ] = {}

    for row in existing_rows:

        scenario_id = row.get(
            "scenario_id"
        )

        if not isinstance(
            scenario_id,
            str,
        ):

            raise ValueError(
                "Existing augmented row has "
                "invalid scenario_id."
            )

        existing_by_scenario.setdefault(
            scenario_id,
            [],
        ).append(
            row
        )

    # --------------------------------------------------------
    # Exactly 10 rows means complete.
    #
    # Anything else:
    # 1..9  -> partial
    # >10   -> invalid/overfull
    #
    # Both are regenerated.
    # --------------------------------------------------------

    completed_scenarios = {
        scenario_id
        for scenario_id, scenario_rows
        in existing_by_scenario.items()
        if (
            len(scenario_rows)
            == VARIATIONS_PER_SCENARIO
        )
    }

    incomplete_scenarios = {
        scenario_id
        for scenario_id, scenario_rows
        in existing_by_scenario.items()
        if (
            len(scenario_rows)
            != VARIATIONS_PER_SCENARIO
        )
    }

    print(
        f"existing_rows="
        f"{len(existing_rows)}"
    )

    print(
        f"completed_scenarios="
        f"{len(completed_scenarios)}"
    )

    print(
        f"incomplete_scenarios="
        f"{sorted(incomplete_scenarios)}"
    )

    # ========================================================
    # REMOVE INCOMPLETE SCENARIOS
    # ========================================================

    if incomplete_scenarios:

        existing_rows = [
            row
            for row in existing_rows
            if (
                row["scenario_id"]
                not in incomplete_scenarios
            )
        ]

        write_jsonl(
            OUTPUT_PATH,
            existing_rows,
        )

        for scenario_id in incomplete_scenarios:

            existing_by_scenario.pop(
                scenario_id,
                None,
            )

        completed_scenarios = {
            scenario_id
            for scenario_id, scenario_rows
            in existing_by_scenario.items()
            if (
                len(scenario_rows)
                == VARIATIONS_PER_SCENARIO
            )
        }

        print(
            "removed_incomplete_scenarios="
            f"{len(incomplete_scenarios)}"
        )

    # ========================================================
    # TEACHER
    # ========================================================

    model_name = os.getenv(
        "PLANNER_TEACHER_MODEL",
        DEFAULT_TEACHER_MODEL,
    )

    print(
        f"teacher_model={model_name}"
    )

    teacher = ChatOpenAI(
        model=model_name,
        temperature=0.7,
        max_retries=2,
    )

    # --------------------------------------------------------
    # Counts newly generated rows in THIS RUN.
    # --------------------------------------------------------

    generated_count = 0

    skipped_count = 0

    # ========================================================
    # GENERATE PER SCENARIO
    # ========================================================

    for position, gold_row in enumerate(
        gold_rows,
        start=1,
    ):

        scenario_id = gold_row[
            "scenario_id"
        ]

        # ----------------------------------------------------
        # Resume:
        # do not pay for scenarios already complete.
        # ----------------------------------------------------

        if scenario_id in completed_scenarios:

            print(
                f"[{position}/{len(gold_rows)}] "
                f"skipping {scenario_id} "
                f"(already complete)"
            )

            skipped_count += 1

            continue

        # ----------------------------------------------------
        # Extract Gold input/output.
        # ----------------------------------------------------

        planner_prompt = gold_row[
            "messages"
        ][0]["content"]

        original_message = (
            extract_current_message(
                planner_prompt
            )
        )

        gold_plan = json.loads(
            gold_row[
                "messages"
            ][1]["content"]
        )

        teacher_prompt = (
            build_teacher_prompt(
                scenario_id=scenario_id,
                original_message=(
                    original_message
                ),
                expected_plan=(
                    gold_plan
                ),
            )
        )

        print(
            f"[{position}/{len(gold_rows)}] "
            f"generating {scenario_id}..."
        )

        # ====================================================
        # GENERATE WITH RETRY
        # ====================================================

        scenario_rows: list[
            dict
        ] = []

        last_error: Exception | None = (
            None
        )

        for attempt in range(
            1,
            MAX_SCENARIO_ATTEMPTS + 1,
        ):

            try:

                if attempt > 1:

                    print(
                        f"  retry "
                        f"{attempt}/"
                        f"{MAX_SCENARIO_ATTEMPTS} "
                        f"for {scenario_id}"
                    )

                # ============================================
                # TEACHER INVOCATION
                # ============================================

                response = teacher.invoke(
                    teacher_prompt
                )

                content = response.content

                if not isinstance(
                    content,
                    str,
                ):

                    raise RuntimeError(
                        "Teacher response "
                        "was not text."
                    )

                # ============================================
                # PARSE OUTPUT
                # ============================================

                parsed = (
                    parse_teacher_output(
                        content
                    )
                )

                variations = parsed.get(
                    "variations"
                )

                if not isinstance(
                    variations,
                    list,
                ):

                    raise ValueError(
                        f"{scenario_id}: "
                        "variations is not "
                        "a list."
                    )

                if (
                    len(variations)
                    != VARIATIONS_PER_SCENARIO
                ):

                    raise ValueError(
                        f"{scenario_id}: "
                        f"expected "
                        f"{VARIATIONS_PER_SCENARIO} "
                        f"variations, got "
                        f"{len(variations)}"
                    )

                # ============================================
                # BUILD ALL 10 IN MEMORY FIRST
                # ============================================

                candidate_rows: list[
                    dict
                ] = []

                seen_messages: set[
                    str
                ] = set()

                for (
                    variation_index,
                    variation,
                ) in enumerate(
                    variations,
                    start=1,
                ):

                    # ----------------------------------------
                    # Schema / argument validation.
                    # ----------------------------------------

                    validate_variation(
                        variation=variation,
                        gold_plan=gold_plan,
                    )

                    generated_message = (
                        variation[
                            "message"
                        ]
                        .strip()
                    )

                    normalized_message = (
                        normalize_message(
                            generated_message
                        )
                    )

                    # ----------------------------------------
                    # DUPLICATE CHECK
                    # ----------------------------------------

                    if (
                        normalized_message
                        in seen_messages
                    ):

                        raise ValueError(
                            f"{scenario_id}: "
                            "duplicate generated "
                            "message: "
                            f"{generated_message!r}"
                        )

                    seen_messages.add(
                        normalized_message
                    )

                    # ----------------------------------------
                    # BUILD TRAIN ROW
                    # ----------------------------------------

                    augmented_row = (
                        build_augmented_row(
                            gold_row=(
                                gold_row
                            ),
                            variation_index=(
                                variation_index
                            ),
                            message=(
                                generated_message
                            ),
                            arguments=(
                                variation[
                                    "arguments"
                                ]
                            ),
                        )
                    )

                    # ----------------------------------------
                    # IMPORTANT:
                    # this was missing previously.
                    # ----------------------------------------

                    candidate_rows.append(
                        augmented_row
                    )

                # ============================================
                # FINAL SCENARIO CHECK
                # ============================================

                if (
                    len(candidate_rows)
                    != VARIATIONS_PER_SCENARIO
                ):

                    raise RuntimeError(
                        f"{scenario_id}: "
                        "incomplete scenario "
                        "generation."
                    )

                # ============================================
                # SUCCESS
                # ============================================

                scenario_rows = (
                    candidate_rows
                )

                last_error = None

                break

            except Exception as exc:

                last_error = exc

                scenario_rows = []

                print(
                    f"  attempt {attempt} "
                    f"failed: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

        # ====================================================
        # FAIL ONLY AFTER ALL ATTEMPTS
        # ====================================================

        if (
            len(scenario_rows)
            != VARIATIONS_PER_SCENARIO
        ):

            raise RuntimeError(
                f"{scenario_id}: failed "
                f"after "
                f"{MAX_SCENARIO_ATTEMPTS} "
                "generation attempts."
            ) from last_error

        # ====================================================
        # WRITE ONLY AFTER ALL 10 PASSED
        # ====================================================

        for augmented_row in scenario_rows:

            append_jsonl(
                OUTPUT_PATH,
                augmented_row,
            )

        completed_scenarios.add(
            scenario_id
        )

        generated_count += len(
            scenario_rows
        )

        print(
            f"  saved="
            f"{len(scenario_rows)}"
        )

    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    final_rows = read_jsonl(
        OUTPUT_PATH
    )

    final_by_scenario: dict[
        str,
        list[dict],
    ] = {}

    for row in final_rows:

        final_by_scenario.setdefault(
            row["scenario_id"],
            [],
        ).append(
            row
        )

    invalid_final_scenarios = {
        scenario_id: len(
            scenario_rows
        )
        for scenario_id, scenario_rows
        in final_by_scenario.items()
        if (
            len(scenario_rows)
            != VARIATIONS_PER_SCENARIO
        )
    }

    if invalid_final_scenarios:

        raise RuntimeError(
            "Final augmented dataset contains "
            "incomplete scenarios: "
            f"{invalid_final_scenarios}"
        )

    # ========================================================
    # REPORT
    # ========================================================

    print()

    print(
        f"gold_scenarios_requested="
        f"{len(gold_rows)}"
    )

    print(
        f"skipped_completed="
        f"{skipped_count}"
    )

    print(
        f"generated_variations_this_run="
        f"{generated_count}"
    )

    print(
        f"final_rows="
        f"{len(final_rows)}"
    )

    print(
        f"final_complete_scenarios="
        f"{len(final_by_scenario)}"
    )

    print(
        f"output="
        f"{OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()