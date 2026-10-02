from __future__ import annotations

import audioop


ULAW_SAMPLE_RATE = 8000

PCM_SAMPLE_WIDTH = 2
PCM_CHANNELS = 1

GEMINI_SAMPLE_RATE = 24000
SLIN24_SAMPLE_RATE = 24000

VAD_SAMPLE_RATE = 8000


def _validate_pcm16(
    audio: bytes,
) -> None:
    """
    Validate PCM16 sample alignment.

    PCM16 samples must always contain an even
    number of bytes.
    """

    if (
        len(audio)
        % PCM_SAMPLE_WIDTH
        != 0
    ):
        raise ValueError(
            "PCM16 audio is not sample aligned"
        )


class StreamingPCM16Resampler:
    """
    Stateful PCM16 mono resampler.

    audioop.ratecv returns an internal state object
    which must be reused across streaming chunks.

    Reset the converter when a call/session ends.
    """

    def __init__(
        self,
        *,
        input_rate: int,
        output_rate: int,
    ) -> None:

        if input_rate <= 0:
            raise ValueError(
                "input_rate must be positive"
            )

        if output_rate <= 0:
            raise ValueError(
                "output_rate must be positive"
            )

        self.input_rate = input_rate
        self.output_rate = output_rate

        self._state = None

    def convert(
        self,
        audio: bytes,
    ) -> bytes:

        if not audio:
            return b""

        _validate_pcm16(
            audio
        )

        converted, self._state = (
            audioop.ratecv(
                audio,
                PCM_SAMPLE_WIDTH,
                PCM_CHANNELS,
                self.input_rate,
                self.output_rate,
                self._state,
            )
        )

        return converted

    def reset(
        self,
    ) -> None:
        """
        Reset streaming interpolation state.

        Call this when starting a new independent
        audio stream.
        """

        self._state = None


def create_slin24_vad_resampler(
) -> StreamingPCM16Resampler:
    """
    Create one resampler per VoiceSession.

    Asterisk:
        PCM16 mono 24 kHz

    Silero VAD:
        PCM16 mono 8 kHz
    """

    return StreamingPCM16Resampler(
        input_rate=SLIN24_SAMPLE_RATE,
        output_rate=VAD_SAMPLE_RATE,
    )


def slin24_to_pcm16_8k(
    audio: bytes,
) -> bytes:
    """
    Stateless conversion helper.

    Kept for backward compatibility and whole-buffer
    conversion.

    For live call streaming, prefer:
        create_slin24_vad_resampler()
    """

    if not audio:
        return b""

    _validate_pcm16(
        audio
    )

    pcm8k, _ = audioop.ratecv(
        audio,
        PCM_SAMPLE_WIDTH,
        PCM_CHANNELS,
        SLIN24_SAMPLE_RATE,
        VAD_SAMPLE_RATE,
        None,
    )

    return pcm8k


def ulaw_to_pcm16(
    audio: bytes,
) -> bytes:
    """
    Convert G.711 mu-law 8 kHz audio from Asterisk
    to PCM16 mono 8 kHz.
    """

    if not audio:
        return b""

    return audioop.ulaw2lin(
        audio,
        PCM_SAMPLE_WIDTH,
    )


def pcm16_24k_to_ulaw8k(
    audio: bytes,
) -> bytes:
    """
    Convert PCM16 mono 24 kHz TTS audio to
    G.711 mu-law mono 8 kHz.

    This helper is intended for complete TTS buffers.
    """

    if not audio:
        return b""

    _validate_pcm16(
        audio
    )

    pcm8k, _ = audioop.ratecv(
        audio,
        PCM_SAMPLE_WIDTH,
        PCM_CHANNELS,
        GEMINI_SAMPLE_RATE,
        ULAW_SAMPLE_RATE,
        None,
    )

    return audioop.lin2ulaw(
        pcm8k,
        PCM_SAMPLE_WIDTH,
    )