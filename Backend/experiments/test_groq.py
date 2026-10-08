import os
import time
import json
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq


# ============================================================
# ENV
# ============================================================

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / ".env"

load_dotenv(ENV_PATH, override=True)

api_key = os.getenv("GROQ_API_KEY")

print("ENV PATH =", ENV_PATH)
print("ENV EXISTS =", ENV_PATH.exists())
print("GROQ_API_KEY loaded =", bool(api_key))

if not api_key:
    raise RuntimeError("GROQ_API_KEY not found")


# ============================================================
# CLIENT
# ============================================================

client = Groq(
    api_key=api_key
)

MODEL = "qwen/qwen3.6-27b"


# ============================================================
# TEST
# ============================================================

messages = [
    {
        "role": "system",
        "content": """
You are MedMind's fast capability planner.

Understand Egyptian Arabic and English.

Return ONLY one valid JSON object.
Do not explain.
Do not reason aloud.

Allowed capability:
appointment.create

JSON format:
{
  "capability": "appointment.create",
  "arguments": {
    "doctor_name": "..."
  }
}
"""
    },
    {
        "role": "user",
        "content": "عايزة احجز مع دكتور ماهر محمود"
    }
]


# ============================================================
# REQUEST
# ============================================================

start = time.perf_counter()

response = client.chat.completions.create(
    model=MODEL,

    messages=messages,

    # IMPORTANT FOR LOW LATENCY
    reasoning_effort="none",

    temperature=0,

    response_format={
        "type": "json_object"
    },

    max_completion_tokens=256,
)

latency_ms = (
    time.perf_counter() - start
) * 1000


# ============================================================
# RESULT
# ============================================================

raw = response.choices[0].message.content

print()
print("=" * 60)
print("GROQ + QWEN 3.6 27B")
print("=" * 60)

print("MODEL =", MODEL)

print(
    "LATENCY =",
    round(latency_ms, 1),
    "ms"
)

print()
print("RAW OUTPUT:")
print(raw)


try:
    parsed = json.loads(raw)

    print()
    print("JSON VALID = True")

    print(
        json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2
        )
    )

except Exception as e:

    print()
    print("JSON VALID = False")
    print("ERROR =", e)


# ============================================================
# USAGE
# ============================================================

if response.usage:

    print()
    print("PROMPT TOKENS =", response.usage.prompt_tokens)
    print(
        "COMPLETION TOKENS =",
        response.usage.completion_tokens
    )