from __future__ import annotations

import asyncio
import sys
import wave
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


load_dotenv(
    PROJECT_ROOT / ".env",
    override=True,
)


from voice_gateway.providers.elevenlabs_tts import (
    ElevenLabsTTS,
)


async def main() -> None:

    tts = ElevenLabsTTS()

    output_pcm = (
        PROJECT_ROOT
        / "artifacts/voice_audio/tts/elevenlabs_true_stream.pcm"
    )

    output_wav = (
        PROJECT_ROOT
        / "artifacts/voice_audio/tts/elevenlabs_true_stream.wav"
    )

    text = (
        "تمام. ممكن الرقم القومي "
        "عشان أتأكد من الحجز؟"
    )

    chunks = 0
    total_bytes = 0

    with output_pcm.open(
        "wb"
    ) as pcm_file:

        async for chunk in (
            tts.stream_pcm24k(
                text
            )
        ):

            chunks += 1

            total_bytes += (
                len(chunk)
            )

            pcm_file.write(
                chunk
            )

            print(
                "chunk",
                chunks,
                "bytes=",
                len(chunk),
            )

    await tts.aclose()
    tts.close()

    # --------------------------------------------------------
    # Wrap resulting raw PCM as WAV.
    # --------------------------------------------------------

    pcm = (
        output_pcm.read_bytes()
    )

    with wave.open(
        str(output_wav),
        "wb",
    ) as wav_file:

        wav_file.setnchannels(1)

        wav_file.setsampwidth(2)

        wav_file.setframerate(
            24000
        )

        wav_file.writeframes(
            pcm
        )

    print()
    print("SUCCESS")
    print("Chunks:", chunks)
    print("Bytes:", total_bytes)
    print("PCM:", output_pcm)
    print("WAV:", output_wav)


if __name__ == "__main__":

    asyncio.run(
        main()
    )