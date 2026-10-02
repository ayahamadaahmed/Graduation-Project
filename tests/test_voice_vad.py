from voice_gateway.audio.vad import (
    StreamingVAD,
    VAD_WINDOW_BYTES,
    VAD_WINDOW_SAMPLES,
)


def test_vad_instances_have_isolated_models() -> None:

    first = StreamingVAD()
    second = StreamingVAD()

    assert first is not second

    assert (
        first.model
        is not second.model
    )

    assert (
        first.iterator
        is not second.iterator
    )

    assert (
        first.iterator.model
        is not second.iterator.model
    )


def test_vad_stream_state_is_isolated() -> None:

    first = StreamingVAD()
    second = StreamingVAD()

    silence_frame = (
        b"\x00\x00"
        * VAD_WINDOW_SAMPLES
    )

    first.feed_pcm16(
        silence_frame
    )

    assert (
        first.iterator.current_sample
        == VAD_WINDOW_SAMPLES
    )

    assert (
        second.iterator.current_sample
        == 0
    )


def test_vad_reset_clears_buffer_and_state() -> None:

    vad = StreamingVAD()

    partial_frame = (
        b"\x00"
        * 100
    )

    vad.feed_pcm16(
        partial_frame
    )

    assert (
        vad.buffered_bytes
        == 100
    )

    vad.reset()

    assert (
        vad.buffered_bytes
        == 0
    )

    assert (
        vad.iterator.current_sample
        == 0
    )


def test_vad_bridges_20ms_audio_into_32ms_window() -> None:

    vad = StreamingVAD()

    # 160 PCM16 samples = 320 bytes = 20 ms @ 8 kHz
    first_20ms = (
        b"\x00\x00"
        * 160
    )

    vad.feed_pcm16(
        first_20ms
    )

    assert (
        vad.buffered_bytes
        == 320
    )

    assert (
        vad.iterator.current_sample
        == 0
    )

    # Add exactly the remaining 96 samples required
    # for one 256-sample Silero window.
    remainder = (
        b"\x00\x00"
        * 96
    )

    vad.feed_pcm16(
        remainder
    )

    assert (
        vad.buffered_bytes
        == 0
    )

    assert (
        vad.iterator.current_sample
        == VAD_WINDOW_SAMPLES
    )

    assert (
        VAD_WINDOW_BYTES
        == 512
    )