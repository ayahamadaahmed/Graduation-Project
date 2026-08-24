from __future__ import annotations

import sys
from pathlib import Path


# ============================================================
# Add project root to Python import path
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


# ============================================================
# Load environment
# ============================================================

from dotenv import load_dotenv

load_dotenv(
    PROJECT_ROOT / ".env",
    override=True,
)


# ============================================================
# Imports
# ============================================================

from voice_gateway.providers.elevenlabs_tts import (
    ElevenLabsTTS,
)


def main() -> None:

    print(
        "Project root:",
        PROJECT_ROOT,
    )

    tts = ElevenLabsTTS()

    try:

        text = (
            "تمام. ممكن الرقم القومي "
            "عشان أتأكد من الحجز؟"
        )

        print(
            "Generating ElevenLabs TTS..."
        )

        pcm = tts.synthesize_pcm24k(
            text
        )

        output_path = (
            PROJECT_ROOT
            / "artifacts/voice_audio/tts/elevenlabs_test_24k.pcm"
        )

        with output_path.open(
            "wb"
        ) as file:

            file.write(
                pcm
            )

        print()
        print("SUCCESS")
        print(
            "PCM bytes:",
            len(pcm),
        )
        print(
            "Saved:",
            output_path,
        )

    finally:

        tts.close()


if __name__ == "__main__":
    main()