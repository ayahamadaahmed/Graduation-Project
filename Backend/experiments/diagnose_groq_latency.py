import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq


# ============================================================
# CONFIG
# ============================================================

MODEL = "qwen/qwen3.6-27b"

BACKEND_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(
    BACKEND_ROOT / ".env",
    override=True,
)

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError("GROQ_API_KEY not found")

client = Groq(api_key=api_key)


# ============================================================
# LOAD VALIDATION
# ============================================================

VALIDATION_PATH = (
    BACKEND_ROOT
    / "data"
    / "planner"
    / "medmind_planner_validation_gold.jsonl"
)

rows = [
    json.loads(line)
    for line in VALIDATION_PATH.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
]

print("Cases loaded =", len(rows))


# ============================================================
# RUN ONLY FIRST 8
#
# Enough to reproduce:
# ~450ms -> ~10-12s behavior
# without running all 22 again.
# ============================================================

for index, row in enumerate(rows[:8], start=1):

    case_id = row.get("id", f"case-{index}")

    prompt = row["messages"][0]["content"]

    messages = [
        {
            "role": "system",
            "content": (
                "Return ONLY one valid JSON object. "
                "No markdown. No explanation."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]


    # --------------------------------------------------------
    # CLIENT TIMER
    # --------------------------------------------------------

    start = time.perf_counter()

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,

        reasoning_effort="none",

        temperature=0,

        response_format={
            "type": "json_object"
        },

        max_completion_tokens=160,
    )

    client_total = (
        time.perf_counter() - start
    )


    # --------------------------------------------------------
    # GROQ SERVER METRICS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # CLIENT - SERVER DIFFERENCE
    # --------------------------------------------------------

    network_other = None

    if server_total is not None:
        network_other = (
            client_total - server_total
        )


    print()
    print("=" * 70)

    print(
        f"[{index}/8] {case_id}"
    )

    print("-" * 70)

    print(
        f"CLIENT TOTAL      = "
        f"{client_total * 1000:.1f} ms"
    )

    if queue_time is not None:
        print(
            f"QUEUE TIME        = "
            f"{queue_time * 1000:.1f} ms"
        )

    if prompt_time is not None:
        print(
            f"PROMPT TIME       = "
            f"{prompt_time * 1000:.1f} ms"
        )

    if completion_time is not None:
        print(
            f"COMPLETION TIME   = "
            f"{completion_time * 1000:.1f} ms"
        )

    if server_total is not None:
        print(
            f"SERVER TOTAL      = "
            f"{server_total * 1000:.1f} ms"
        )

    if network_other is not None:
        print(
            f"CLIENT-SERVER GAP = "
            f"{network_other * 1000:.1f} ms"
        )


    print(
        "PROMPT TOKENS     =",
        usage.prompt_tokens,
    )

    print(
        "COMPLETION TOKENS =",
        usage.completion_tokens,
    )


print()
print("=" * 70)
print("DIAGNOSTIC FINISHED")
print("=" * 70)