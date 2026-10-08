from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import httpx
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


load_dotenv(
    PROJECT_ROOT / ".env",
    override=True,
)


API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")
MODEL_ID = os.getenv(
    "ELEVENLABS_MODEL_ID",
    "eleven_multilingual_v2",
)


if not API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY missing")

if not VOICE_ID:
    raise RuntimeError("ELEVENLABS_VOICE_ID missing")


TEXT = (
    "تمام، ممكن الرقم القومي "
    "عشان أتأكد من الحجز؟"
)


def generate(
    output_format: str,
) -> bytes:

    url = (
        "https://api.elevenlabs.io"
        f"/v1/text-to-speech/{VOICE_ID}"
    )

    response = httpx.post(
        url,
        headers={
            "xi-api-key": API_KEY,
            "Content-Type": "application/json",
        },
        params={
            "output_format": output_format,
        },
        json={
            "text": TEXT,
            "model_id": MODEL_ID,
            "language_code": "ar",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
                "speed": 1.0,
            },
        },
        timeout=30.0,
    )

    if response.is_error:
        print(
            "ERROR:",
            output_format,
            response.status_code,
            response.text,
        )
        response.raise_for_status()

    print(
        output_format,
        "bytes=",
        len(response.content),
        "content-type=",
        response.headers.get("content-type"),
    )

    return response.content


def save_pcm_as_wav(
    pcm: bytes,
    path: Path,
) -> None:

    print(
        "PCM first 16 bytes:",
        pcm[:16].hex(" "),
    )

    print(
        "PCM even byte length:",
        len(pcm) % 2 == 0,
    )

    with wave.open(
        str(path),
        "wb",
    ) as wav_file:

        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)

        wav_file.writeframes(pcm)


def main() -> None:

    print("Model:", MODEL_ID)
    print("Voice:", VOICE_ID)

    # =====================================
    # MP3
    # =====================================

    mp3 = generate(
        "mp3_44100_128"
    )

    mp3_path = (
        PROJECT_ROOT
        / "artifacts/voice_audio/tts/elevenlabs_debug.mp3"
    )

    mp3_path.write_bytes(
        mp3
    )

    # =====================================
    # PCM 24 kHz
    # =====================================

    pcm = generate(
        "pcm_24000"
    )

    raw_pcm_path = (
        PROJECT_ROOT
        / "artifacts/voice_audio/tts/elevenlabs_debug.pcm"
    )

    raw_pcm_path.write_bytes(
        pcm
    )

    pcm_path = (
        PROJECT_ROOT
        / "artifacts/voice_audio/tts/elevenlabs_debug.wav"
    )

    save_pcm_as_wav(
        pcm,
        pcm_path,
    )

    print()
    print("Saved:")
    print(mp3_path)
    print(pcm_path)
    print(raw_pcm_path)

if __name__ == "__main__":
    main()