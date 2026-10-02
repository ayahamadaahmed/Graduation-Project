from __future__ import annotations

import asyncio
import os
import time
import httpx
from dotenv import load_dotenv
from groq import AsyncGroq


load_dotenv()


IDLE_DELAYS = [
    1,
    7,
    10,
]

RUNS_PER_DELAY = 3


async def make_request(
    client: AsyncGroq,
    *,
    model: str,
    label: str,
) -> None:

    started = time.perf_counter()

    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,

            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        'Return exactly: '
                        '{"status":"ok"}'
                    ),
                },
            ],

            reasoning_effort="none",
            temperature=0,

            response_format={
                "type": "json_object",
            },

            max_completion_tokens=32,
        ),
        timeout=5.0,
    )

    client_ms = (
        time.perf_counter()
        - started
    ) * 1000

    usage = getattr(
        response,
        "usage",
        None,
    )

    server_total = (
        getattr(
            usage,
            "total_time",
            None,
        )
        if usage
        else None
    )

    server_total_ms = (
        server_total * 1000
        if server_total is not None
        else None
    )

    overhead_ms = (
        client_ms - server_total_ms
        if server_total_ms is not None
        else None
    )

    print()
    print(
        f"{label}"
    )

    print(
        f"client_ms       = "
        f"{client_ms:.2f}"
    )

    print(
        "server_total_ms = "
        + (
            f"{server_total_ms:.2f}"
            if server_total_ms
            is not None
            else "unknown"
        )
    )

    print(
        "outside_ms      = "
        + (
            f"{overhead_ms:.2f}"
            if overhead_ms
            is not None
            else "unknown"
        )
    )


async def main() -> None:

    api_key = (
        os.getenv(
            "GROQ_API_KEY",
            "",
        )
        .strip()
    )

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured."
        )

    model = (
        os.getenv(
            "QWEN_PLANNER_MODEL",
            "qwen/qwen3.6-27b",
        )
        .strip()
    )

    print(
        f"Model: {model}"
    )

    http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=60.0,
        ),
    )

    client = AsyncGroq(
        api_key=api_key,
        max_retries=0,
        http_client=http_client,
    )

    try:

        print(
            "\n=== Warm-up ==="
        )

        await make_request(
            client,
            model=model,
            label="warmup",
        )

        for idle_seconds in IDLE_DELAYS:

            for run_number in range(
                    1,
                    RUNS_PER_DELAY + 1,
                ):

                    print(
                        f"\nSleeping "
                        f"{idle_seconds}s "
                        f"(run {run_number})..."
                    )

                    await asyncio.sleep(
                        idle_seconds
                    )

                    await make_request(
                        client,
                        model=model,
                        label=(
                            f"after_"
                            f"{idle_seconds}s_idle_"
                            f"run_{run_number}"
                        ),
                    )

    finally:

        await client.close()


if __name__ == "__main__":
    asyncio.run(
        main()
    )