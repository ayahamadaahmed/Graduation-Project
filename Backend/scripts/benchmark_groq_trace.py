from __future__ import annotations

import asyncio
import os
import time

import httpx
from dotenv import load_dotenv


load_dotenv()


GROQ_URL = (
    "https://api.groq.com/openai/v1/"
    "chat/completions"
)

IDLE_DELAYS = [
    1,
    7,
    10,
]


async def make_request(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    label: str,
) -> None:

    request_started = (
        time.perf_counter()
    )

    trace_state = {
        "tcp_started": False,
        "tls_started": False,
        "headers_ms": None,
    }

    async def trace(
        event_name: str,
        info: dict,
    ) -> None:

        elapsed_ms = (
            time.perf_counter()
            - request_started
        ) * 1000

        if (
            event_name
            == "connection.connect_tcp.started"
        ):
            trace_state[
                "tcp_started"
            ] = True

            print(
                f"  TRACE "
                f"TCP_CONNECT_STARTED "
                f"{elapsed_ms:.2f} ms"
            )

        elif (
            event_name
            == "connection.connect_tcp.complete"
        ):
            print(
                f"  TRACE "
                f"TCP_CONNECT_COMPLETE "
                f"{elapsed_ms:.2f} ms"
            )

        elif (
            event_name
            == "connection.start_tls.started"
        ):
            trace_state[
                "tls_started"
            ] = True

            print(
                f"  TRACE "
                f"TLS_STARTED "
                f"{elapsed_ms:.2f} ms"
            )

        elif (
            event_name
            == "connection.start_tls.complete"
        ):
            print(
                f"  TRACE "
                f"TLS_COMPLETE "
                f"{elapsed_ms:.2f} ms"
            )

        elif event_name in {
            (
                "http11."
                "receive_response_headers."
                "complete"
            ),
            (
                "http2."
                "receive_response_headers."
                "complete"
            ),
        }:
            trace_state[
                "headers_ms"
            ] = elapsed_ms

            print(
                f"  TRACE "
                f"RESPONSE_HEADERS "
                f"{elapsed_ms:.2f} ms"
            )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    'Return exactly '
                    '{"status":"ok"}'
                ),
            },
        ],
        "reasoning_effort": "none",
        "temperature": 0,
        "response_format": {
            "type": "json_object",
        },
        "max_completion_tokens": 32,
    }

    response = await client.post(
        GROQ_URL,
        headers={
            "Authorization":
                f"Bearer {api_key}",
            "Content-Type":
                "application/json",
        },
        json=payload,
        extensions={
            "trace": trace,
        },
    )

    total_ms = (
        time.perf_counter()
        - request_started
    ) * 1000

    response.raise_for_status()

    data = response.json()

    usage = (
        data.get("usage")
        or {}
    )

    server_total = (
        usage.get("total_time")
    )

    server_total_ms = (
        server_total * 1000
        if server_total is not None
        else None
    )

    outside_ms = (
        total_ms - server_total_ms
        if server_total_ms is not None
        else None
    )

    print()
    print(
        f"=== {label} ==="
    )

    print(
        f"new_tcp         = "
        f"{trace_state['tcp_started']}"
    )

    print(
        f"new_tls         = "
        f"{trace_state['tls_started']}"
    )

    print(
        "headers_ms      = "
        + (
            f"{trace_state['headers_ms']:.2f}"
            if trace_state[
                "headers_ms"
            ] is not None
            else "unknown"
        )
    )

    print(
        f"client_ms       = "
        f"{total_ms:.2f}"
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
            f"{outside_ms:.2f}"
            if outside_ms
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

    limits = httpx.Limits(
        max_connections=100,
        max_keepalive_connections=20,
        keepalive_expiry=60.0,
    )

    timeout = httpx.Timeout(
        5.0,
    )

    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
    ) as client:

        print(
            "\nStarting warm-up..."
        )

        await make_request(
            client,
            api_key=api_key,
            model=model,
            label="warmup",
        )

        for idle_seconds in (
            IDLE_DELAYS
        ):

            print(
                f"\nSleeping "
                f"{idle_seconds}s..."
            )

            await asyncio.sleep(
                idle_seconds
            )

            await make_request(
                client,
                api_key=api_key,
                model=model,
                label=(
                    f"after_"
                    f"{idle_seconds}s_idle"
                ),
            )


if __name__ == "__main__":
    asyncio.run(
        main()
    )