import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import (
    Groq,
    RateLimitError,
    APIStatusError,
    APIConnectionError,
)


# ============================================================
# CONFIG
# ============================================================

MODEL = "qwen/qwen3.6-27b"

NUMBER_OF_CASES = 8

# Small spacing only.
# We WANT to observe the headers / quota behavior.
REQUEST_DELAY_SECONDS = 2


# ============================================================
# PATHS
# ============================================================

BACKEND_ROOT = Path(__file__).resolve().parents[1]

ENV_PATH = BACKEND_ROOT / ".env"

VALIDATION_PATH = (
    BACKEND_ROOT
    / "data"
    / "planner"
    / "medmind_planner_validation_gold.jsonl"
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
        "GROQ_API_KEY not found"
    )


# ============================================================
# CLIENT
#
# IMPORTANT:
# no hidden retries
# ============================================================

client = Groq(
    api_key=api_key,
    max_retries=0,
    timeout=30.0,
)


# ============================================================
# LOAD VALIDATION CASES
# ============================================================

rows = [
    json.loads(line)
    for line in VALIDATION_PATH.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
]

print()
print("Cases loaded =", len(rows))

assert len(rows) == 22


# ============================================================
# HEADER HELPERS
# ============================================================

def get_header(
    headers,
    name,
):

    value = headers.get(name)

    if value is None:
        return "N/A"

    return value


def print_rate_limit_headers(
    headers,
):

    print()
    print("--- RATE LIMIT HEADERS ---")

    print(
        "LIMIT REQUESTS       =",
        get_header(
            headers,
            "x-ratelimit-limit-requests",
        ),
    )

    print(
        "REMAINING REQUESTS   =",
        get_header(
            headers,
            "x-ratelimit-remaining-requests",
        ),
    )

    print(
        "RESET REQUESTS       =",
        get_header(
            headers,
            "x-ratelimit-reset-requests",
        ),
    )

    print(
        "LIMIT TOKENS         =",
        get_header(
            headers,
            "x-ratelimit-limit-tokens",
        ),
    )

    print(
        "REMAINING TOKENS     =",
        get_header(
            headers,
            "x-ratelimit-remaining-tokens",
        ),
    )

    print(
        "RESET TOKENS         =",
        get_header(
            headers,
            "x-ratelimit-reset-tokens",
        ),
    )

    print(
        "RETRY AFTER          =",
        get_header(
            headers,
            "retry-after",
        ),
    )


# ============================================================
# RUN CASE
# ============================================================

def run_case(
    row,
):

    prompt = (
        row["messages"][0]["content"]
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Return ONLY one valid JSON object. "
                "No markdown. "
                "No explanation. "
                "No text before or after the JSON."
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

    started = time.perf_counter()


    # --------------------------------------------------------
    # RAW RESPONSE
    #
    # This lets us inspect HTTP headers.
    # --------------------------------------------------------

    raw_response = (
        client
        .chat
        .completions
        .with_raw_response
        .create(
            model=MODEL,

            messages=messages,

            reasoning_effort="none",

            temperature=0,

            response_format={
                "type": "json_object"
            },

            max_completion_tokens=160,
        )
    )


    # --------------------------------------------------------
    # Full client time
    #
    # with_raw_response is eager, so at this point the response
    # has been received.
    # --------------------------------------------------------

    client_total_ms = (
        time.perf_counter()
        - started
    ) * 1000


    # --------------------------------------------------------
    # HTTP HEADERS
    # --------------------------------------------------------

    headers = raw_response.headers


    # --------------------------------------------------------
    # Parse normal Groq response
    # --------------------------------------------------------

    completion = (
        raw_response.parse()
    )


    usage = completion.usage


    # ========================================================
    # GROQ TIMINGS
    # ========================================================

    queue_seconds = getattr(
        usage,
        "queue_time",
        None,
    )

    prompt_seconds = getattr(
        usage,
        "prompt_time",
        None,
    )

    completion_seconds = getattr(
        usage,
        "completion_time",
        None,
    )

    server_seconds = getattr(
        usage,
        "total_time",
        None,
    )


    queue_ms = (
        queue_seconds * 1000
        if queue_seconds is not None
        else None
    )

    prompt_ms = (
        prompt_seconds * 1000
        if prompt_seconds is not None
        else None
    )

    completion_ms = (
        completion_seconds * 1000
        if completion_seconds is not None
        else None
    )

    server_ms = (
        server_seconds * 1000
        if server_seconds is not None
        else None
    )


    # ========================================================
    # DERIVED TIMINGS
    # ========================================================

    unexplained_ms = None

    if server_ms is not None:

        unexplained_ms = (
            client_total_ms
            - server_ms
        )


    # This is useful because Groq sometimes reports queue
    # separately from total_time depending on API metrics.
    estimated_full_server_ms = None

    if (
        queue_ms is not None
        and server_ms is not None
    ):

        estimated_full_server_ms = (
            queue_ms
            + server_ms
        )


    outside_queue_and_compute_ms = None

    if (
        estimated_full_server_ms
        is not None
    ):

        outside_queue_and_compute_ms = (
            client_total_ms
            - estimated_full_server_ms
        )


    # ========================================================
    # RESPONSE INFO
    # ========================================================

    output = (
        completion
        .choices[0]
        .message
        .content
    )


    return {
        "client_total_ms": (
            client_total_ms
        ),

        "queue_ms": (
            queue_ms
        ),

        "prompt_ms": (
            prompt_ms
        ),

        "completion_ms": (
            completion_ms
        ),

        "server_ms": (
            server_ms
        ),

        "unexplained_ms": (
            unexplained_ms
        ),

        "estimated_full_server_ms": (
            estimated_full_server_ms
        ),

        "outside_queue_compute_ms": (
            outside_queue_and_compute_ms
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

        "headers": headers,

        "output": output,
    }


# ============================================================
# MAIN DIAGNOSTIC
# ============================================================

print()
print("=" * 75)
print("GROQ TRANSPORT / QUOTA DIAGNOSTIC")
print("=" * 75)


for index, row in enumerate(
    rows[:NUMBER_OF_CASES],
    start=1,
):

    case_id = (
        row.get("id")
        or f"case-{index}"
    )

    print()
    print()
    print("=" * 75)
    print(
        f"[{index}/{NUMBER_OF_CASES}] "
        f"{case_id}"
    )
    print("=" * 75)


    try:

        result = run_case(
            row
        )


        # ====================================================
        # TIMINGS
        # ====================================================

        print()
        print("--- TIMINGS ---")


        print(
            f"CLIENT TOTAL              = "
            f"{result['client_total_ms']:.1f} ms"
        )


        if result["queue_ms"] is not None:

            print(
                f"GROQ QUEUE                = "
                f"{result['queue_ms']:.1f} ms"
            )


        if result["prompt_ms"] is not None:

            print(
                f"PROMPT PROCESSING         = "
                f"{result['prompt_ms']:.1f} ms"
            )


        if (
            result["completion_ms"]
            is not None
        ):

            print(
                f"COMPLETION                = "
                f"{result['completion_ms']:.1f} ms"
            )


        if result["server_ms"] is not None:

            print(
                f"GROQ SERVER TOTAL         = "
                f"{result['server_ms']:.1f} ms"
            )


        if (
            result[
                "estimated_full_server_ms"
            ]
            is not None
        ):

            print(
                f"QUEUE + SERVER            = "
                f"{result['estimated_full_server_ms']:.1f} ms"
            )


        if (
            result[
                "outside_queue_compute_ms"
            ]
            is not None
        ):

            print(
                f"OUTSIDE QUEUE + COMPUTE   = "
                f"{result['outside_queue_compute_ms']:.1f} ms"
            )


        # ====================================================
        # TOKENS
        # ====================================================

        print()
        print("--- TOKENS ---")

        print(
            "PROMPT TOKENS     =",
            result["prompt_tokens"],
        )

        print(
            "COMPLETION TOKENS =",
            result[
                "completion_tokens"
            ],
        )


        # ====================================================
        # RATE LIMIT HEADERS
        # ====================================================

        print_rate_limit_headers(
            result["headers"]
        )


        # ====================================================
        # SHORT OUTPUT
        # ====================================================

        print()
        print("--- OUTPUT ---")

        print(
            result["output"][:350]
        )


    # ========================================================
    # 429
    # ========================================================

    except RateLimitError as exc:

        elapsed_ms = (
            time.perf_counter()
            if False
            else None
        )

        print()
        print("RATE LIMIT HIT = TRUE")
        print("STATUS = 429")

        if getattr(
            exc,
            "response",
            None,
        ) is not None:

            print_rate_limit_headers(
                exc.response.headers
            )

        print()
        print(
            "ERROR =",
            exc,
        )


    # ========================================================
    # OTHER API ERRORS
    # ========================================================

    except APIStatusError as exc:

        print()
        print(
            "API STATUS ERROR =",
            exc.status_code,
        )

        if getattr(
            exc,
            "response",
            None,
        ) is not None:

            print_rate_limit_headers(
                exc.response.headers
            )

        print(
            "ERROR =",
            exc,
        )


    # ========================================================
    # CONNECTION ERROR
    # ========================================================

    except APIConnectionError as exc:

        print()
        print(
            "API CONNECTION ERROR"
        )

        print(
            "ERROR =",
            exc,
        )


    # ========================================================
    # DELAY
    # ========================================================

    if index < NUMBER_OF_CASES:

        print()
        print(
            f"Waiting "
            f"{REQUEST_DELAY_SECONDS}s..."
        )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )


print()
print()
print("=" * 75)
print("DIAGNOSTIC FINISHED")
print("=" * 75)