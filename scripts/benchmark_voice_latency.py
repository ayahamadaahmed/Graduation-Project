from __future__ import annotations

import argparse
import csv
import math
import statistics

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S,%f"


@dataclass
class VoiceTurn:
    vad_end: datetime | None = None
    stt_start: datetime | None = None
    transcript_ready: datetime | None = None
    tts_text_ready: datetime | None = None
    tts_start: datetime | None = None
    playback_start: datetime | None = None


def parse_timestamp(
    line: str,
) -> datetime | None:

    if len(line) < 23:
        return None

    value = line[:23]

    try:
        return datetime.strptime(
            value,
            TIMESTAMP_FORMAT,
        )
    except ValueError:
        return None


def elapsed_ms(
    start: datetime | None,
    end: datetime | None,
) -> float | None:

    if (
        start is None
        or end is None
    ):
        return None

    return (
        end - start
    ).total_seconds() * 1000


def read_log_text(
    path: Path,
) -> str:

    raw = path.read_bytes()

    # UTF-16 BOM
    if raw.startswith(
        (b"\xff\xfe", b"\xfe\xff")
    ):
        return raw.decode(
            "utf-16"
        )

    # PowerShell UTF-16 without a useful BOM
    if b"\x00" in raw[:200]:
        return raw.decode(
            "utf-16-le",
            errors="replace",
        )

    return raw.decode(
        "utf-8-sig",
        errors="replace",
    )

def percentile(
    values: list[float],
    p: float,
) -> float:

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        len(ordered) - 1
    ) * p

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    fraction = (
        position - lower
    )

    return (
        ordered[lower]
        + (
            ordered[upper]
            - ordered[lower]
        )
        * fraction
    )


def parse_voice_log(
    path: Path,
) -> list[VoiceTurn]:

    completed: list[
        VoiceTurn
    ] = []

    current: VoiceTurn | None = None

    text = read_log_text(
        path
    )

    for line in text.splitlines():

        timestamp = parse_timestamp(
            line
        )

        if timestamp is None:
            continue

        # ---------------------------------------------
        # Start a new candidate user turn
        # ---------------------------------------------

        if "vad_speech_ended" in line:

            current = VoiceTurn(
                vad_end=timestamp
            )

            continue

        if current is None:
            continue

        # ---------------------------------------------
        # Hamsa STT request starts
        # ---------------------------------------------

        if "hamsa_primary_started" in line:

            if current.stt_start is None:
                current.stt_start = (
                    timestamp
                )

            continue

        # ---------------------------------------------
        # Final transcript becomes available
        # ---------------------------------------------

        if (
            "hamsa_primary_transcript_queued"
            in line
        ):

            current.transcript_ready = (
                timestamp
            )

            continue

        # ---------------------------------------------
        # Backend reply is ready for TTS
        # ---------------------------------------------

        if "voice_tts_text_prepared" in line:

            current.tts_text_ready = (
                timestamp
            )

            continue

        # ---------------------------------------------
        # Hamsa TTS request starts
        # ---------------------------------------------

        if "voice_tts_stream_started" in line:

            current.tts_start = (
                timestamp
            )

            continue

        # ---------------------------------------------
        # Agent audio actually starts
        # ---------------------------------------------

        if "voice_playback_started" in line:

            current.playback_start = (
                timestamp
            )

            if (
                current.vad_end is not None
                and
                current.playback_start is not None
            ):

                completed.append(
                    current
                )

            current = None

    return completed


def to_number(
    value: float | None,
):

    if value is None:
        return ""

    return round(
        value,
        2,
    )


def build_rows(
    turns: list[VoiceTurn],
    vad_silence_ms: float,
) -> list[dict]:

    rows = []

    for index, turn in enumerate(
        turns,
        start=1,
    ):

        endpoint_ms = elapsed_ms(
            turn.vad_end,
            turn.stt_start,
        )

        stt_ms = elapsed_ms(
            turn.stt_start,
            turn.transcript_ready,
        )

        backend_ms = elapsed_ms(
            turn.transcript_ready,
            turn.tts_text_ready,
        )

        tts_ms = elapsed_ms(
            turn.tts_start,
            turn.playback_start,
        )

        e2e_ms = elapsed_ms(
            turn.vad_end,
            turn.playback_start,
        )

        if e2e_ms is None:
            continue

        rows.append(
            {
                "turn":
                    index,

                "endpoint_ms":
                    to_number(
                        endpoint_ms
                    ),

                "stt_ms":
                    to_number(
                        stt_ms
                    ),

                "backend_ms":
                    to_number(
                        backend_ms
                    ),

                "tts_ms":
                    to_number(
                        tts_ms
                    ),

                "vad_end_to_audio_ms":
                    round(
                        e2e_ms,
                        2,
                    ),

                "estimated_user_latency_ms":
                    round(
                        e2e_ms
                        + vad_silence_ms,
                        2,
                    ),
            }
        )

    return rows


def numeric_values(
    rows: list[dict],
    key: str,
) -> list[float]:

    result = []

    for row in rows:

        value = row.get(
            key
        )

        if isinstance(
            value,
            (int, float),
        ):
            result.append(
                float(value)
            )

    return result


def print_summary(
    title: str,
    values: list[float],
) -> None:

    if not values:
        return

    print()
    print(title)

    print(
        f"  samples : {len(values)}"
    )

    print(
        f"  mean    : "
        f"{statistics.mean(values):.2f} ms"
    )

    print(
        f"  P50     : "
        f"{percentile(values, 0.50):.2f} ms"
    )

    print(
        f"  P95     : "
        f"{percentile(values, 0.95):.2f} ms"
    )

    print(
        f"  max     : "
        f"{max(values):.2f} ms"
    )


def main() -> None:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--log",
        default=(
            "voice-gateway-live.log"
        ),
    )

    parser.add_argument(
        "--skip",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--vad-silence-ms",
        type=float,
        default=500.0,
    )

    parser.add_argument(
        "--csv",
        default=(
            "voice_latency_results.csv"
        ),
    )

    args = parser.parse_args()

    path = Path(
        args.log
    )

    turns = parse_voice_log(
        path
    )

    rows = build_rows(
        turns,
        vad_silence_ms=
            args.vad_silence_ms,
    )

    if args.skip:
        rows = rows[
            args.skip:
        ]

    if args.limit:
        rows = rows[
            :args.limit
        ]

    if not rows:
        raise SystemExit(
            "No complete voice turns "
            "were found."
        )

    print()
    print(
        "================================"
    )
    print(
        " MedMind Voice Latency Benchmark"
    )
    print(
        "================================"
    )

    for row in rows:

        print(
            f"Turn {row['turn']:02d} | "
            f"endpoint={row['endpoint_ms']} ms | "
            f"STT={row['stt_ms']} ms | "
            f"backend={row['backend_ms']} ms | "
            f"TTS={row['tts_ms']} ms | "
            f"E2E={row['vad_end_to_audio_ms']} ms | "
            f"perceived≈"
            f"{row['estimated_user_latency_ms']} ms"
        )

    print_summary(
        "VAD-end -> first playable audio",
        numeric_values(
            rows,
            "vad_end_to_audio_ms",
        ),
    )

    print_summary(
        "Estimated user-perceived latency",
        numeric_values(
            rows,
            "estimated_user_latency_ms",
        ),
    )

    print_summary(
        "Hamsa STT",
        numeric_values(
            rows,
            "stt_ms",
        ),
    )

    print_summary(
        "Backend / AI / Workflow",
        numeric_values(
            rows,
            "backend_ms",
        ),
    )

    print_summary(
        "Hamsa TTS",
        numeric_values(
            rows,
            "tts_ms",
        ),
    )

    csv_path = Path(
        args.csv
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(
            rows
        )

    print()
    print(
        f"CSV saved to: "
        f"{csv_path.resolve()}"
    )


if __name__ == "__main__":
    main()