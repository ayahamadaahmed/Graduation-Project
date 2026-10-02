from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import websockets
from dotenv import load_dotenv


load_dotenv()


HAMSA_WS_URL = (
    "wss://api.tryhamsa.com/v1/realtime/ws"
)


async def transcribe(
    audio_path: str,
) -> None:

    api_key = os.getenv(
        "HAMSA_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "HAMSA_API_KEY is missing"
        )

    audio_bytes = Path(
        audio_path
    ).read_bytes()

    audio_base64 = base64.b64encode(
        audio_bytes
    ).decode("ascii")

    uri = (
        f"{HAMSA_WS_URL}"
        f"?api_key={api_key}"
    )

    async with websockets.connect(
        uri,
        max_size=None,
    ) as ws:

        # Hamsa sends an initial info message
        first_message = await ws.recv()

        print(
            "CONNECTED:",
            first_message,
        )

        request = {
            "type": "stt",
            "payload": {
                "audioBase64": audio_base64,
                "language": "ar",
                "isEosEnabled": True,
                "eosThreshold": 0.3,
                "model": "s3",
            },
        }

        await ws.send(
            json.dumps(
                request
            )
        )

        while True:

            response = await ws.recv()

            # Successful transcription is
            # documented as plain text.
            try:
                message = json.loads(
                    response
                )

            except json.JSONDecodeError:

                print(
                    "HAMSA TRANSCRIPT:",
                    response,
                )

                return

            message_type = message.get(
                "type"
            )

            if message_type == "error":

                raise RuntimeError(
                    message
                )

            print(
                "HAMSA MESSAGE:",
                message,
            )


if __name__ == "__main__":

    asyncio.run(
        transcribe(
            r"experiments\stt_benchmark\v0_1\audio\real_001.wav"
        )
    )