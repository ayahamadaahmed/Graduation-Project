from __future__ import annotations

import os
import sys
import time

from pathlib import Path


# ============================================================
# Project Root
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


import httpx

from voice_gateway.config import (
    load_environment,
)


load_environment()


# ============================================================
# Configuration
# ============================================================

HAMSA_TTS_URL = (
    "https://api.tryhamsa.com/v1/realtime/tts"
)

HAMSA_TTS_SPEAKER = "Samir"

HAMSA_TTS_DIALECT = "egy"

HAMSA_TTS_SAMPLE_RATE = "16k"

TEST_TEXT = (
    "تمام، المواعيد المتاحة يوم السبت، "
    "الساعة اتناشر الضهر، "
    "واتناشر ونص الضهر."
)


# ============================================================
# Main
# ============================================================

def main() -> None:

    api_key = (
        os.getenv(
            "HAMSA_API_KEY",
            "",
        )
        .strip()
    )

    if not api_key:

        raise RuntimeError(
            "HAMSA_API_KEY is not configured."
        )

    output_dir = (
        PROJECT_ROOT
        / "artifacts"
        / "hamsa_tts"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / "kamel_test.wav"
    )

    payload = {
        "text": TEST_TEXT,
        "speaker": HAMSA_TTS_SPEAKER,
        "dialect": HAMSA_TTS_DIALECT,
        "mulaw": False,
        "sampleRate": HAMSA_TTS_SAMPLE_RATE,
        "expressiveness": 1,
    }

    headers = {
        "Authorization":
            f"Token {api_key}",

        "Content-Type":
            "application/json",
    }

    print(
        "HAMSA_TTS_TEST_START"
    )

    print(
        f"speaker={HAMSA_TTS_SPEAKER}"
    )

    print(
        f"dialect={HAMSA_TTS_DIALECT}"
    )

    print(
        f"sample_rate={HAMSA_TTS_SAMPLE_RATE}"
    )

    started_at = (
        time.perf_counter()
    )

    with httpx.Client(
        timeout=30.0,
    ) as client:

        response = client.post(
            HAMSA_TTS_URL,
            json=payload,
            headers=headers,
        )

    elapsed_ms = (
        time.perf_counter()
        - started_at
    ) * 1000

    print(
        f"status_code={response.status_code}"
    )

    print(
        f"elapsed_ms={elapsed_ms:.2f}"
    )

    print(
        "content_type="
        f"{response.headers.get('content-type')}"
    )

    if response.status_code != 200:

        print(
            "HAMSA_TTS_FAILED"
        )

        print(
            response.text
        )

        response.raise_for_status()

    output_path.write_bytes(
        response.content
    )

    print(
        "HAMSA_TTS_OK"
    )

    print(
        f"audio_bytes={len(response.content)}"
    )

    print(
        f"saved_to={output_path}"
    )


if __name__ == "__main__":
    main()