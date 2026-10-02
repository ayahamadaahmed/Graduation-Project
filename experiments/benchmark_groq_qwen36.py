import os
import json
import time
import math
import statistics
from pathlib import Path

from dotenv import load_dotenv

from groq import (
    Groq,
    RateLimitError,
    BadRequestError,
)


# ============================================================
# CONFIG
# ============================================================

MODEL = "qwen/qwen3.6-27b"

BACKEND_ROOT = Path(__file__).resolve().parents[1]

ENV_PATH = BACKEND_ROOT / ".env"

RESULTS_DIR = (
    BACKEND_ROOT
    / "experiments"
    / "results"
)

RESULTS_PATH = (
    RESULTS_DIR
    / "groq_qwen36_27b_22.json"
)


# ============================================================
# LOAD ENV
# ============================================================

load_dotenv(
    ENV_PATH,
    override=True,
)

api_key = os.getenv(
    "GROQ_API_KEY"
)

print(
    "ENV PATH =",
    ENV_PATH
)

print(
    "ENV EXISTS =",
    ENV_PATH.exists()
)

print(
    "GROQ_API_KEY loaded =",
    bool(api_key)
)

if not api_key:

    raise RuntimeError(
        "GROQ_API_KEY not found in .env"
    )


# ============================================================
# GROQ CLIENT
# ============================================================

client = Groq(
    api_key=api_key
)


# ============================================================
# FIND VALIDATION FILE
# ============================================================

validation_matches = list(
    BACKEND_ROOT.rglob(
        "medmind_planner_validation_gold.jsonl"
    )
)

if not validation_matches:

    raise FileNotFoundError(
        "Could not find "
        "medmind_planner_validation_gold.jsonl"
    )


VALIDATION_PATH = validation_matches[0]


print()
print(
    "VALIDATION FILE =",
    VALIDATION_PATH
)


# ============================================================
# LOAD 22 FROZEN CASES
# ============================================================

validation_rows = [
    json.loads(line)
    for line in VALIDATION_PATH.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
]


print(
    "VALIDATION ROWS =",
    len(validation_rows)
)


assert (
    len(validation_rows) == 22
), (
    "Expected exactly 22 frozen "
    "validation cases"
)


# ============================================================
# JSON PARSER
# ============================================================

def parse_json_object(
    text: str,
):

    if not text:

        return None

    text = text.strip()


    # --------------------------------------------------------
    # Direct JSON
    # --------------------------------------------------------

    try:

        value = json.loads(
            text
        )

        if isinstance(
            value,
            dict,
        ):

            return value

    except Exception:

        pass


    # --------------------------------------------------------
    # Markdown code fence
    # --------------------------------------------------------

    if text.startswith(
        "```"
    ):

        lines = text.splitlines()

        if lines:

            lines = lines[1:]

        if (
            lines
            and lines[-1].strip()
            == "```"
        ):

            lines = lines[:-1]

        candidate = "\n".join(
            lines
        ).strip()

        try:

            value = json.loads(
                candidate
            )

            if isinstance(
                value,
                dict,
            ):

                return value

        except Exception:

            pass


    # --------------------------------------------------------
    # Search first JSON object
    # --------------------------------------------------------

    decoder = json.JSONDecoder()

    for index, char in enumerate(
        text
    ):

        if char != "{":

            continue

        try:

            value, _ = (
                decoder.raw_decode(
                    text[index:]
                )
            )

            if isinstance(
                value,
                dict,
            ):

                return value

        except Exception:

            continue


    return None


# ============================================================
# SAFE NORMALIZATION
#
# Same normalization we used when evaluating local Qwen.
# ============================================================

def normalize_value(
    key,
    value,
):

    if not isinstance(
        value,
        str,
    ):

        return value


    value = value.strip()


    # Arabic / English question mark
    if key == "query":

        value = value.replace(
            "?",
            "؟",
        )


    # القلب / قلب
    if (
        key
        == "specialty_name"
        and value
        == "قلب"
    ):

        value = "القلب"


    # منى / دكتورة منى
    if (
        key
        == "doctor_name"
        and value
        == "منى"
    ):

        value = "دكتورة منى"


    return value


def normalize_args(
    args,
):

    if not isinstance(
        args,
        dict,
    ):

        return args


    return {
        key: normalize_value(
            key,
            value,
        )
        for key, value
        in args.items()
    }


# ============================================================
# SINGLE GROQ REQUEST
# ============================================================

def run_case(
    row,
):

    original_prompt = (
        row["messages"][0]["content"]
    )


    # --------------------------------------------------------
    # Groq JSON mode requires the word "JSON"
    # somewhere in messages.
    #
    # We DO NOT modify the original MedMind prompt.
    # We only add a provider-specific formatting instruction.
    # --------------------------------------------------------

    messages = [

        {
            "role": "system",
            "content": (
                "Return ONLY one valid JSON object. "
                "Do not use markdown. "
                "Do not add explanations. "
                "Do not add text before or after the JSON."
            ),
        },

        {
            "role": "user",
            "content": original_prompt,
        },

    ]


    retries = 0


    while True:

        try:

            started = (
                time.perf_counter()
            )


            response = (
                client
                .chat
                .completions
                .create(

                    model=MODEL,

                    messages=messages,

                    # ----------------------------------------
                    # IMPORTANT:
                    # disable reasoning for low latency
                    # ----------------------------------------

                    reasoning_effort="none",

                    temperature=0,

                    # ----------------------------------------
                    # Force JSON output
                    # ----------------------------------------

                    response_format={
                        "type": "json_object"
                    },

                    max_completion_tokens=160,
                )
            )


            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000


            break


        except RateLimitError:

            retries += 1


            if retries > 5:

                raise


            wait_seconds = (
                retries * 15
            )


            print(
                f"Rate limit hit. "
                f"Waiting {wait_seconds}s..."
            )


            time.sleep(
                wait_seconds
            )


        except BadRequestError as exc:

            print()
            print(
                "BAD REQUEST:"
            )

            print(
                exc
            )

            raise


    # ========================================================
    # RESPONSE
    # ========================================================

    raw = (
        response
        .choices[0]
        .message
        .content
    )


    prediction = (
        parse_json_object(
            raw
        )
    )


    usage = response.usage


    prompt_tokens = None
    completion_tokens = None


    if usage:

        prompt_tokens = (
            usage.prompt_tokens
        )

        completion_tokens = (
            usage.completion_tokens
        )


    return {

        "raw": raw,

        "prediction": (
            prediction
        ),

        "latency_ms": (
            latency_ms
        ),

        "prompt_tokens": (
            prompt_tokens
        ),

        "completion_tokens": (
            completion_tokens
        ),

        "retries": retries,
    }


# ============================================================
# WARMUP
# ============================================================

print()
print(
    "Running warmup..."
)


warmup = run_case(
    validation_rows[0]
)


print(
    "Warmup latency =",
    round(
        warmup["latency_ms"],
        1,
    ),
    "ms",
)


print(
    "Warmup output ="
)

print(
    warmup["raw"][:500]
)


# ============================================================
# RUN 22 CASES
# ============================================================

results = []


print()
print("=" * 75)
print(
    "GROQ QWEN3.6-27B — "
    "22 CASE BENCHMARK"
)
print("=" * 75)
print()


for index, row in enumerate(
    validation_rows,
    start=1,
):

    scenario_id = (
        row.get("id")
        or row.get("scenario_id")
        or f"case-{index:02d}"
    )


    gold = json.loads(
        row["messages"][1]["content"]
    )


    result = run_case(
        row
    )


    prediction = (
        result["prediction"]
    )


    results.append({

        "id": scenario_id,

        "gold": gold,

        "prediction": (
            prediction
        ),

        "raw_output": (
            result["raw"]
        ),

        "latency_ms": (
            result["latency_ms"]
        ),

        "prompt_tokens": (
            result["prompt_tokens"]
        ),

        "completion_tokens": (
            result["completion_tokens"]
        ),

        "retries": (
            result["retries"]
        ),

    })


    gold_capability = (
        gold.get(
            "capability"
        )
    )


    predicted_capability = (

        prediction.get(
            "capability"
        )

        if prediction

        else None
    )


    print(

        f"[{index:02d}/22] "

        f"{scenario_id} | "

        f"{result['latency_ms']:.1f} ms | "

        f"gold={gold_capability} | "

        f"pred={predicted_capability}"

    )


# ============================================================
# METRICS
# ============================================================

fields = [

    "status",

    "capability",

    "arguments",

    "confirmation",

    "ambiguity_kind",

    "correction_target",

]


counts = {
    field: 0
    for field in fields
}


json_valid = 0

normalized_arguments_exact = 0

full_toolplan_exact = 0


latencies = []


real_argument_errors = []


for result in results:

    gold = result[
        "gold"
    ]

    prediction = result[
        "prediction"
    ]


    latencies.append(
        result["latency_ms"]
    )


    if prediction is None:

        continue


    json_valid += 1


    # --------------------------------------------------------
    # Individual fields
    # --------------------------------------------------------

    for field in fields:

        if (
            prediction.get(
                field
            )
            ==
            gold.get(
                field
            )
        ):

            counts[
                field
            ] += 1


    # --------------------------------------------------------
    # Safe-normalized arguments
    # --------------------------------------------------------

    gold_args = (
        normalize_args(
            gold.get(
                "arguments",
                {},
            )
        )
    )


    predicted_args = (
        normalize_args(
            prediction.get(
                "arguments",
                {},
            )
        )
    )


    if (
        gold_args
        ==
        predicted_args
    ):

        normalized_arguments_exact += 1

    else:

        real_argument_errors.append({

            "id": result[
                "id"
            ],

            "gold_capability": (
                gold.get(
                    "capability"
                )
            ),

            "pred_capability": (
                prediction.get(
                    "capability"
                )
            ),

            "gold_arguments": (
                gold_args
            ),

            "pred_arguments": (
                predicted_args
            ),

        })


    # --------------------------------------------------------
    # Full exact
    # --------------------------------------------------------

    if (
        prediction
        ==
        gold
    ):

        full_toolplan_exact += 1


# ============================================================
# LATENCY METRICS
# ============================================================

sorted_latencies = sorted(
    latencies
)


p50 = statistics.median(
    sorted_latencies
)


p95_index = (
    math.ceil(
        0.95
        * len(
            sorted_latencies
        )
    )
    - 1
)


p95 = (
    sorted_latencies[
        p95_index
    ]
)


average_latency = (
    statistics.mean(
        latencies
    )
)


# ============================================================
# TOKEN METRICS
# ============================================================

prompt_tokens = [

    result[
        "prompt_tokens"
    ]

    for result in results

    if result[
        "prompt_tokens"
    ]
    is not None
]


completion_tokens = [

    result[
        "completion_tokens"
    ]

    for result in results

    if result[
        "completion_tokens"
    ]
    is not None
]


prompt_p50 = (

    statistics.median(
        prompt_tokens
    )

    if prompt_tokens

    else None
)


completion_p50 = (

    statistics.median(
        completion_tokens
    )

    if completion_tokens

    else None
)


# ============================================================
# PRINT METRICS
# ============================================================

def score(
    value,
):

    return (
        f"{value}/22 "
        f"({value / 22 * 100:.1f}%)"
    )


print()
print("=" * 75)
print(
    "GROQ QWEN3.6-27B "
    "— FINAL RESULTS"
)
print("=" * 75)


print(
    "JSON valid           =",
    score(
        json_valid
    )
)


print(
    "Status               =",
    score(
        counts[
            "status"
        ]
    )
)


print(
    "Capability           =",
    score(
        counts[
            "capability"
        ]
    )
)


print(
    "Arguments raw        =",
    score(
        counts[
            "arguments"
        ]
    )
)


print(
    "Arguments normalized =",
    score(
        normalized_arguments_exact
    )
)


print(
    "Confirmation         =",
    score(
        counts[
            "confirmation"
        ]
    )
)


print(
    "Ambiguity            =",
    score(
        counts[
            "ambiguity_kind"
        ]
    )
)


print(
    "Correction target    =",
    score(
        counts[
            "correction_target"
        ]
    )
)


print(
    "Full ToolPlan exact  =",
    score(
        full_toolplan_exact
    )
)


# ============================================================
# LATENCY
# ============================================================

print()
print(
    "--- LATENCY ---"
)


print(
    f"P50 = "
    f"{p50:.1f} ms"
)


print(
    f"P95 = "
    f"{p95:.1f} ms"
)


print(
    f"AVG = "
    f"{average_latency:.1f} ms"
)


# ============================================================
# TOKENS
# ============================================================

print()
print(
    "--- TOKENS ---"
)


print(
    "Prompt P50 =",
    prompt_p50
)


print(
    "Completion P50 =",
    completion_p50
)


# ============================================================
# REAL ARGUMENT ERRORS
# ============================================================

print()
print(
    "--- REAL ARGUMENT ERRORS ---"
)


print(
    "COUNT =",
    len(
        real_argument_errors
    )
)


for error in (
    real_argument_errors
):

    print(
        json.dumps(
            error,
            ensure_ascii=False,
        )
    )


# ============================================================
# CURRENT BASELINES
# ============================================================

print()
print("=" * 75)
print(
    "CURRENT MEDMIND BASELINES"
)
print("=" * 75)


print(
    "GPT-4.1 planner"
    "      ≈ 1250 ms"
)


print(
    "GPT-4.1-mini"
    "         ≈ 980 ms + spikes"
)


print(
    "Qwen2.5 local P50"
    "    ≈ 1964 ms"
)


print(
    "Qwen2.5 local P95"
    "    ≈ 2362 ms"
)


print(
    "Qwen2.5 Capability"
    "   = 20/22 (90.9%)"
)


print(
    "Qwen2.5 Norm Args"
    "    = 14/22 (63.6%)"
)


# ============================================================
# SAVE FULL RESULT
# ============================================================

RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


summary = {

    "model": MODEL,

    "validation_cases": 22,

    "metrics": {

        "json_valid": (
            json_valid
        ),

        "status": (
            counts[
                "status"
            ]
        ),

        "capability": (
            counts[
                "capability"
            ]
        ),

        "arguments_raw": (
            counts[
                "arguments"
            ]
        ),

        "arguments_normalized": (
            normalized_arguments_exact
        ),

        "confirmation": (
            counts[
                "confirmation"
            ]
        ),

        "ambiguity": (
            counts[
                "ambiguity_kind"
            ]
        ),

        "correction_target": (
            counts[
                "correction_target"
            ]
        ),

        "full_toolplan_exact": (
            full_toolplan_exact
        ),

    },

    "latency": {

        "p50_ms": p50,

        "p95_ms": p95,

        "average_ms": (
            average_latency
        ),

    },

    "tokens": {

        "prompt_p50": (
            prompt_p50
        ),

        "completion_p50": (
            completion_p50
        ),

    },

    "real_argument_errors": (
        real_argument_errors
    ),

    "results": results,

}


RESULTS_PATH.write_text(

    json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
    ),

    encoding="utf-8",
)


print()
print(
    "SAVED =",
    RESULTS_PATH
)