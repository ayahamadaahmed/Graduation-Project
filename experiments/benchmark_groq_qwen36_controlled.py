import os
import json
import time
import math
import statistics
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq, RateLimitError, BadRequestError


# ============================================================
# CONFIG
# ============================================================

MODEL = "qwen/qwen3.6-27b"

# Delay between requests so Free-tier TPM
# does not distort latency measurements.
REQUEST_DELAY_SECONDS = 13

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / ".env"

RESULTS_DIR = (
    BACKEND_ROOT
    / "experiments"
    / "results"
)

RESULTS_PATH = (
    RESULTS_DIR
    / "groq_qwen36_27b_controlled_22.json"
)


# ============================================================
# LOAD ENV
# ============================================================

load_dotenv(
    ENV_PATH,
    override=True,
)

api_key = os.getenv("GROQ_API_KEY")

print("ENV PATH =", ENV_PATH)
print("ENV EXISTS =", ENV_PATH.exists())
print("GROQ_API_KEY loaded =", bool(api_key))

if not api_key:
    raise RuntimeError(
        "GROQ_API_KEY not found in .env"
    )


# ============================================================
# GROQ CLIENT
#
# IMPORTANT:
# Disable automatic SDK retries.
#
# If we hit 429, we want to SEE it.
# We do not want hidden 10-12 second waits.
# ============================================================

client = Groq(
    api_key=api_key,
    max_retries=0,
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
    VALIDATION_PATH,
)


# ============================================================
# LOAD FROZEN 22 CASES
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
    len(validation_rows),
)

assert len(validation_rows) == 22, (
    "Expected exactly 22 frozen validation cases"
)


# ============================================================
# JSON PARSER
# ============================================================

def parse_json_object(text):

    if not text:
        return None

    text = text.strip()

    # Direct JSON
    try:
        value = json.loads(text)

        if isinstance(value, dict):
            return value

    except Exception:
        pass

    # Markdown fence fallback
    if text.startswith("```"):

        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        candidate = "\n".join(
            lines
        ).strip()

        try:
            value = json.loads(candidate)

            if isinstance(value, dict):
                return value

        except Exception:
            pass

    # Find first JSON object
    decoder = json.JSONDecoder()

    for index, char in enumerate(text):

        if char != "{":
            continue

        try:
            value, _ = decoder.raw_decode(
                text[index:]
            )

            if isinstance(value, dict):
                return value

        except Exception:
            continue

    return None


# ============================================================
# SAFE NORMALIZATION
# ============================================================

def normalize_value(
    key,
    value,
):

    if not isinstance(value, str):
        return value

    value = value.strip()

    # Arabic / English question mark
    if key == "query":
        value = value.replace(
            "?",
            "؟",
        )

    # قلب / القلب
    if (
        key == "specialty_name"
        and value == "قلب"
    ):
        value = "القلب"

    # منى / دكتورة منى
    if (
        key == "doctor_name"
        and value == "منى"
    ):
        value = "دكتورة منى"

    return value


def normalize_args(args):

    if not isinstance(args, dict):
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
# OPERATIONAL TOOLPLAN COMPARISON
#
# Ignore cosmetic/optional fields such as "reason".
# ============================================================

def operational_toolplan(
    obj,
    normalize_arguments=False,
):

    if not isinstance(obj, dict):
        return None

    arguments = obj.get(
        "arguments",
        {},
    )

    if normalize_arguments:
        arguments = normalize_args(
            arguments
        )

    return {
        "status": obj.get("status"),
        "capability": obj.get("capability"),
        "arguments": arguments,
        "confirmation": obj.get("confirmation"),
        "ambiguity_kind": obj.get("ambiguity_kind"),
        "correction_target": obj.get(
            "correction_target"
        ),
    }


# ============================================================
# SINGLE REQUEST
# ============================================================

def run_case(row):

    original_prompt = (
        row["messages"][0]["content"]
    )

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

    started = time.perf_counter()

    try:

        response = (
            client
            .chat
            .completions
            .create(
                model=MODEL,
                messages=messages,

                # Fast planner:
                # disable Qwen reasoning.
                reasoning_effort="none",

                temperature=0,

                response_format={
                    "type": "json_object"
                },

                max_completion_tokens=160,
            )
        )

    except RateLimitError as exc:

        elapsed_ms = (
            time.perf_counter()
            - started
        ) * 1000

        return {
            "success": False,
            "rate_limited": True,
            "error": str(exc),
            "client_total_ms": elapsed_ms,

            "raw": None,
            "prediction": None,

            "queue_ms": None,
            "prompt_ms": None,
            "completion_ms": None,
            "server_total_ms": None,
            "client_server_gap_ms": None,

            "prompt_tokens": None,
            "completion_tokens": None,
        }

    except BadRequestError as exc:

        elapsed_ms = (
            time.perf_counter()
            - started
        ) * 1000

        return {
            "success": False,
            "rate_limited": False,
            "error": str(exc),
            "client_total_ms": elapsed_ms,

            "raw": None,
            "prediction": None,

            "queue_ms": None,
            "prompt_ms": None,
            "completion_ms": None,
            "server_total_ms": None,
            "client_server_gap_ms": None,

            "prompt_tokens": None,
            "completion_tokens": None,
        }

    # ========================================================
    # CLIENT TOTAL
    # ========================================================

    client_total_seconds = (
        time.perf_counter()
        - started
    )

    client_total_ms = (
        client_total_seconds
        * 1000
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    raw = (
        response
        .choices[0]
        .message
        .content
    )

    prediction = parse_json_object(
        raw
    )

    # ========================================================
    # GROQ SERVER TIMINGS
    # ========================================================

    usage = response.usage

    queue_time = getattr(
        usage,
        "queue_time",
        None,
    )

    prompt_time = getattr(
        usage,
        "prompt_time",
        None,
    )

    completion_time = getattr(
        usage,
        "completion_time",
        None,
    )

    server_total = getattr(
        usage,
        "total_time",
        None,
    )

    queue_ms = (
        queue_time * 1000
        if queue_time is not None
        else None
    )

    prompt_ms = (
        prompt_time * 1000
        if prompt_time is not None
        else None
    )

    completion_ms = (
        completion_time * 1000
        if completion_time is not None
        else None
    )

    server_total_ms = (
        server_total * 1000
        if server_total is not None
        else None
    )

    client_server_gap_ms = None

    if server_total_ms is not None:
        client_server_gap_ms = (
            client_total_ms
            - server_total_ms
        )

    return {
        "success": True,
        "rate_limited": False,
        "error": None,

        "raw": raw,
        "prediction": prediction,

        "client_total_ms": client_total_ms,

        "queue_ms": queue_ms,
        "prompt_ms": prompt_ms,
        "completion_ms": completion_ms,
        "server_total_ms": server_total_ms,

        "client_server_gap_ms": (
            client_server_gap_ms
        ),

        "prompt_tokens": (
            usage.prompt_tokens
            if usage
            else None
        ),

        "completion_tokens": (
            usage.completion_tokens
            if usage
            else None
        ),
    }


# ============================================================
# WARMUP
# ============================================================

print()
print("=" * 75)
print("WARMUP")
print("=" * 75)

warmup = run_case(
    validation_rows[0]
)

if warmup["success"]:

    print(
        f"Client total = "
        f"{warmup['client_total_ms']:.1f} ms"
    )

    if warmup["server_total_ms"] is not None:

        print(
            f"Server total = "
            f"{warmup['server_total_ms']:.1f} ms"
        )

    print(
        "Output =",
        warmup["raw"][:500],
    )

else:

    print(
        "Warmup failed:",
        warmup["error"],
    )


# Important:
# prevent warmup from consuming quota
# immediately before case 1.
print()
print(
    f"Waiting {REQUEST_DELAY_SECONDS}s "
    f"before benchmark..."
)

time.sleep(
    REQUEST_DELAY_SECONDS
)


# ============================================================
# RUN 22 CASES
# ============================================================

results = []

print()
print("=" * 75)
print(
    "GROQ QWEN3.6-27B — "
    "CONTROLLED 22 CASE BENCHMARK"
)
print("=" * 75)


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

    record = {
        "id": scenario_id,
        "gold": gold,
        **result,
    }

    results.append(
        record
    )

    print()
    print("-" * 75)

    if result["success"]:

        predicted_capability = (
            prediction.get("capability")
            if prediction
            else None
        )

        print(
            f"[{index:02d}/22] "
            f"{scenario_id}"
        )

        print(
            f"Capability: "
            f"gold={gold.get('capability')} | "
            f"pred={predicted_capability}"
        )

        print(
            f"CLIENT TOTAL     = "
            f"{result['client_total_ms']:.1f} ms"
        )

        if result["queue_ms"] is not None:
            print(
                f"QUEUE            = "
                f"{result['queue_ms']:.1f} ms"
            )

        if result["prompt_ms"] is not None:
            print(
                f"PROMPT           = "
                f"{result['prompt_ms']:.1f} ms"
            )

        if result["completion_ms"] is not None:
            print(
                f"COMPLETION       = "
                f"{result['completion_ms']:.1f} ms"
            )

        if result["server_total_ms"] is not None:
            print(
                f"SERVER TOTAL     = "
                f"{result['server_total_ms']:.1f} ms"
            )

        if (
            result["client_server_gap_ms"]
            is not None
        ):
            print(
                f"CLIENT-SERVER GAP= "
                f"{result['client_server_gap_ms']:.1f} ms"
            )

    else:

        print(
            f"[{index:02d}/22] "
            f"{scenario_id} FAILED"
        )

        print(
            "RATE LIMITED =",
            result["rate_limited"],
        )

        print(
            "ERROR =",
            result["error"],
        )

    # --------------------------------------------------------
    # CONTROLLED SPACING
    # --------------------------------------------------------

    if index < len(validation_rows):

        print(
            f"Waiting "
            f"{REQUEST_DELAY_SECONDS}s..."
        )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )


# ============================================================
# SUCCESSFUL RESULTS ONLY FOR LATENCY
# ============================================================

successful_results = [
    result
    for result in results
    if result["success"]
]

rate_limited_results = [
    result
    for result in results
    if result["rate_limited"]
]


# ============================================================
# ACCURACY METRICS
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

operational_exact_raw = 0
operational_exact_normalized = 0

real_argument_errors = []


for result in successful_results:

    gold = result["gold"]
    prediction = result["prediction"]

    if prediction is None:
        continue

    json_valid += 1

    # --------------------------------------------------------
    # Individual fields
    # --------------------------------------------------------

    for field in fields:

        if (
            prediction.get(field)
            == gold.get(field)
        ):
            counts[field] += 1

    # --------------------------------------------------------
    # Normalized arguments
    # --------------------------------------------------------

    gold_args = normalize_args(
        gold.get(
            "arguments",
            {},
        )
    )

    predicted_args = normalize_args(
        prediction.get(
            "arguments",
            {},
        )
    )

    if gold_args == predicted_args:

        normalized_arguments_exact += 1

    else:

        real_argument_errors.append({
            "id": result["id"],

            "gold_capability": (
                gold.get("capability")
            ),

            "pred_capability": (
                prediction.get("capability")
            ),

            "gold_arguments": gold_args,
            "pred_arguments": predicted_args,
        })

    # --------------------------------------------------------
    # Literal full object
    # --------------------------------------------------------

    if prediction == gold:
        full_toolplan_exact += 1

    # --------------------------------------------------------
    # Operational exact — RAW
    # --------------------------------------------------------

    if (
        operational_toolplan(
            prediction,
            normalize_arguments=False,
        )
        ==
        operational_toolplan(
            gold,
            normalize_arguments=False,
        )
    ):
        operational_exact_raw += 1

    # --------------------------------------------------------
    # Operational exact — NORMALIZED
    # --------------------------------------------------------

    if (
        operational_toolplan(
            prediction,
            normalize_arguments=True,
        )
        ==
        operational_toolplan(
            gold,
            normalize_arguments=True,
        )
    ):
        operational_exact_normalized += 1


# ============================================================
# PERCENTILE HELPER
# ============================================================

def percentile_95(values):

    if not values:
        return None

    ordered = sorted(values)

    index = (
        math.ceil(
            0.95 * len(ordered)
        )
        - 1
    )

    return ordered[index]


def metric_summary(values):

    if not values:

        return {
            "count": 0,
            "p50": None,
            "p95": None,
            "avg": None,
        }

    return {
        "count": len(values),

        "p50": statistics.median(
            values
        ),

        "p95": percentile_95(
            values
        ),

        "avg": statistics.mean(
            values
        ),
    }


# ============================================================
# LATENCY LISTS
# ============================================================

client_latencies = [
    r["client_total_ms"]
    for r in successful_results
    if r["client_total_ms"] is not None
]

server_latencies = [
    r["server_total_ms"]
    for r in successful_results
    if r["server_total_ms"] is not None
]

queue_latencies = [
    r["queue_ms"]
    for r in successful_results
    if r["queue_ms"] is not None
]

prompt_latencies = [
    r["prompt_ms"]
    for r in successful_results
    if r["prompt_ms"] is not None
]

completion_latencies = [
    r["completion_ms"]
    for r in successful_results
    if r["completion_ms"] is not None
]

gap_latencies = [
    r["client_server_gap_ms"]
    for r in successful_results
    if r["client_server_gap_ms"] is not None
]


client_stats = metric_summary(
    client_latencies
)

server_stats = metric_summary(
    server_latencies
)

queue_stats = metric_summary(
    queue_latencies
)

prompt_stats = metric_summary(
    prompt_latencies
)

completion_stats = metric_summary(
    completion_latencies
)

gap_stats = metric_summary(
    gap_latencies
)


# ============================================================
# TOKEN METRICS
# ============================================================

prompt_tokens = [
    r["prompt_tokens"]
    for r in successful_results
    if r["prompt_tokens"] is not None
]

completion_tokens = [
    r["completion_tokens"]
    for r in successful_results
    if r["completion_tokens"] is not None
]

prompt_token_p50 = (
    statistics.median(
        prompt_tokens
    )
    if prompt_tokens
    else None
)

completion_token_p50 = (
    statistics.median(
        completion_tokens
    )
    if completion_tokens
    else None
)


# ============================================================
# SCORE HELPER
# ============================================================

successful_count = len(
    successful_results
)


def score(
    value,
):

    if successful_count == 0:
        return "N/A"

    percentage = (
        value
        / successful_count
        * 100
    )

    return (
        f"{value}/{successful_count} "
        f"({percentage:.1f}%)"
    )


# ============================================================
# FINAL RESULTS
# ============================================================

print()
print("=" * 75)
print(
    "GROQ QWEN3.6-27B "
    "— CONTROLLED FINAL RESULTS"
)
print("=" * 75)

print(
    "Successful cases     =",
    f"{successful_count}/22",
)

print(
    "Rate limited cases   =",
    len(rate_limited_results),
)

print()

print(
    "JSON valid           =",
    score(json_valid),
)

print(
    "Status               =",
    score(counts["status"]),
)

print(
    "Capability           =",
    score(counts["capability"]),
)

print(
    "Arguments raw        =",
    score(counts["arguments"]),
)

print(
    "Arguments normalized =",
    score(
        normalized_arguments_exact
    ),
)

print(
    "Confirmation         =",
    score(counts["confirmation"]),
)

print(
    "Ambiguity            =",
    score(counts["ambiguity_kind"]),
)

print(
    "Correction target    =",
    score(
        counts["correction_target"]
    ),
)

print(
    "Full object exact    =",
    score(full_toolplan_exact),
)

print(
    "Operational exact RAW=",
    score(operational_exact_raw),
)

print(
    "Operational exact NORM=",
    score(
        operational_exact_normalized
    ),
)


# ============================================================
# LATENCY SUMMARY
# ============================================================

def print_latency(
    title,
    stats,
):

    print()
    print(title)

    print(
        f"  P50 = "
        f"{stats['p50']:.1f} ms"
        if stats["p50"] is not None
        else "  P50 = N/A"
    )

    print(
        f"  P95 = "
        f"{stats['p95']:.1f} ms"
        if stats["p95"] is not None
        else "  P95 = N/A"
    )

    print(
        f"  AVG = "
        f"{stats['avg']:.1f} ms"
        if stats["avg"] is not None
        else "  AVG = N/A"
    )


print()
print("=" * 75)
print("CONTROLLED LATENCY")
print("=" * 75)

print_latency(
    "CLIENT TOTAL",
    client_stats,
)

print_latency(
    "GROQ SERVER TOTAL",
    server_stats,
)

print_latency(
    "GROQ QUEUE",
    queue_stats,
)

print_latency(
    "PROMPT PROCESSING",
    prompt_stats,
)

print_latency(
    "COMPLETION",
    completion_stats,
)

print_latency(
    "CLIENT-SERVER GAP",
    gap_stats,
)


# ============================================================
# TOKENS
# ============================================================

print()
print("--- TOKENS ---")

print(
    "Prompt P50 =",
    prompt_token_p50,
)

print(
    "Completion P50 =",
    completion_token_p50,
)


# ============================================================
# ARGUMENT ERRORS
# ============================================================

print()
print(
    "--- REAL ARGUMENT ERRORS ---"
)

print(
    "COUNT =",
    len(real_argument_errors),
)

for error in real_argument_errors:

    print(
        json.dumps(
            error,
            ensure_ascii=False,
        )
    )


# ============================================================
# RATE LIMITED CASES
# ============================================================

if rate_limited_results:

    print()
    print(
        "--- RATE LIMITED CASES ---"
    )

    for result in rate_limited_results:

        print(
            result["id"]
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
    "GPT-4.1 planner      ≈ 1250 ms"
)

print(
    "GPT-4.1-mini         ≈ 980 ms + spikes"
)

print(
    "Qwen2.5 local P50    ≈ 1964 ms"
)

print(
    "Qwen2.5 local P95    ≈ 2362 ms"
)

print(
    "Qwen2.5 Capability   = 20/22 (90.9%)"
)

print(
    "Qwen2.5 Norm Args    = 14/22 (63.6%)"
)


# ============================================================
# SAVE
# ============================================================

RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

summary = {
    "model": MODEL,
    "controlled": True,
    "request_delay_seconds": (
        REQUEST_DELAY_SECONDS
    ),

    "validation_cases": 22,

    "successful_cases": (
        successful_count
    ),

    "rate_limited_cases": (
        len(rate_limited_results)
    ),

    "accuracy": {
        "json_valid": json_valid,

        "status": counts["status"],

        "capability": (
            counts["capability"]
        ),

        "arguments_raw": (
            counts["arguments"]
        ),

        "arguments_normalized": (
            normalized_arguments_exact
        ),

        "confirmation": (
            counts["confirmation"]
        ),

        "ambiguity": (
            counts["ambiguity_kind"]
        ),

        "correction_target": (
            counts["correction_target"]
        ),

        "full_object_exact": (
            full_toolplan_exact
        ),

        "operational_exact_raw": (
            operational_exact_raw
        ),

        "operational_exact_normalized": (
            operational_exact_normalized
        ),
    },

    "latency": {
        "client_total": client_stats,
        "server_total": server_stats,
        "queue": queue_stats,
        "prompt": prompt_stats,
        "completion": completion_stats,
        "client_server_gap": gap_stats,
    },

    "tokens": {
        "prompt_p50": (
            prompt_token_p50
        ),

        "completion_p50": (
            completion_token_p50
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
    RESULTS_PATH,
)