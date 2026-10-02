from __future__ import annotations

import asyncio
import os
import time
import httpx
from dotenv import load_dotenv
from groq import AsyncGroq


load_dotenv()


# Approximate the real planner payload size.
# We intentionally use a long prompt similar to the
# ~1000-token MedMind planner request.
PRODUCTION_LIKE_PROMPT = """
You are MedMind's capability planner.

Select the correct healthcare capability from the candidates.
Use the current context and current user message.
Return ONLY valid JSON.

Rules:
- Select only from candidate capabilities.
- Use context for short contextual replies.
- Never invent arguments.
- Preserve spoken date/time text.
- Booking means appointment.create.
- Cancellation means appointment.cancel.
- Rescheduling means appointment.reschedule.
- Existing appointment lookup means appointment.search.
- If ambiguous, return ambiguous.
- Return only values stated in the current message.
- Do not copy unchanged context values.
- Never invent a service outside offered services.
- If several services are plausible, do not guess.

CURRENT CONTEXT:
{
    "channel": "voice",
    "stage": "new",
    "operation_type": null,
    "language": "ar",
    "provider_type": "clinic",
    "active_capability": null,
    "doctor_name": null,
    "specialty": null,
    "date": null,
    "time": null,
    "service": null
}

CANDIDATE CAPABILITIES:
appointment.create | create a new appointment
appointment.search | find an existing appointment
appointment.cancel | cancel an existing appointment
appointment.reschedule | change an existing appointment
catalog.doctors | search doctors
catalog.specialties | search specialties
catalog.services | search services
schedule.working_hours | provider working hours

CURRENT USER MESSAGE:
عايزة أحجز مع دكتور جلدية بكرة
""" * 3


async def run_request(
    client: AsyncGroq,
    *,
    model: str,
    label: str,
) -> None:

    started = time.perf_counter()

    response = await client.chat.completions.create(
        model=model,

        messages=[
            {
                "role": "system",
                "content": (
                    "Return ONLY one valid JSON object."
                ),
            },
            {
                "role": "user",
                "content": PRODUCTION_LIKE_PROMPT,
            },
        ],

        reasoning_effort="none",
        temperature=0,

        response_format={
            "type": "json_object",
        },

        max_completion_tokens=160,
    )

    client_ms = (
        time.perf_counter()
        - started
    ) * 1000

    usage = response.usage

    server_total_ms = (
        usage.total_time * 1000
        if usage
        and usage.total_time is not None
        else None
    )

    outside_ms = (
        client_ms - server_total_ms
        if server_total_ms is not None
        else None
    )

    print()
    print(label)

    print(
        f"prompt_tokens    = "
        f"{usage.prompt_tokens}"
    )

    print(
        f"completion_tokens= "
        f"{usage.completion_tokens}"
    )

    print(
        f"client_ms        = "
        f"{client_ms:.2f}"
    )

    print(
        f"server_total_ms  = "
        f"{server_total_ms:.2f}"
    )

    print(
        f"outside_ms       = "
        f"{outside_ms:.2f}"
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
            "GROQ_API_KEY missing"
        )

    model = (
        os.getenv(
            "QWEN_PLANNER_MODEL",
            "qwen/qwen3.6-27b",
        )
        .strip()
    )

    http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=60.0,
        ),
        timeout=httpx.Timeout(
            5.0,
        ),
    )

    client = AsyncGroq(
        api_key=api_key,
        max_retries=0,
        http_client=http_client,
    )

    try:

        await run_request(
            client,
            model=model,
            label="warmup",
        )

        await asyncio.sleep(1)

        await run_request(
            client,
            model=model,
            label="after_1s",
        )

        await asyncio.sleep(10)

        await run_request(
            client,
            model=model,
            label="after_10s",
        )

    finally:

        await client.close()


if __name__ == "__main__":
    asyncio.run(main())