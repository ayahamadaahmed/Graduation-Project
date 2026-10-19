from voice_gateway.providers.deepgram_stt import (
    DeepgramStreamingSTT,
)


def test_late_deepgram_final_keeps_original_turn_owner():
    received = []

    stt = DeepgramStreamingSTT.__new__(
        DeepgramStreamingSTT
    )

    stt._final_parts = [
        "عايز احجز كشف"
    ]

    stt._finalize_owner = (
        7,
        "new",
        0,
    )

    stt._on_transcript = None

    stt._benchmark_log_transcripts = False

    stt._on_transcript_with_owner = (
        lambda text, is_final, owner: (
            received.append(
                (
                    text,
                    is_final,
                    owner,
                )
            )
        )
    )

    # Simulate Voice Gateway already moving
    # to a newer Hamsa turn before Deepgram
    # finally returns Turn 7.
    current_hamsa_turn = 8

    assert current_hamsa_turn == 8

    stt._flush_final_transcript(
        reason="test_late_result",
    )

    assert received == [
        (
            "عايز احجز كشف",
            True,
            (
                7,
                "new",
                0,
            ),
        )
    ]

    # Owner is single-use and cannot leak
    # into another transcript.
    assert stt._finalize_owner is None