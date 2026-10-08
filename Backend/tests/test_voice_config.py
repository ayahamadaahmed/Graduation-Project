from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice_gateway.config import VoiceSettings


VOICE_ENV_KEYS = (
    "VOICE_DEFAULT_TURN_END_GRACE_SECONDS",
    "VOICE_DIGIT_TURN_END_GRACE_SECONDS",
    "VOICE_DIGIT_MAX_UTTERANCE_SECONDS",
    "VOICE_HAMSA_PREROLL_SECONDS",
    "VOICE_HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS",
    "VOICE_HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS",
    "VOICE_DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS",
    "VOICE_DIGIT_INCOMPLETE_RETRY_SECONDS",
    "VOICE_BARGE_IN_ENABLED",
    "VOICE_BARGE_IN_MIN_SPEECH_SECONDS",
    "VOICE_BARGE_IN_INITIAL_PROTECTION_SECONDS",
    "VOICE_BARGE_IN_COOLDOWN_SECONDS",
    "VOICE_FAST_BARGE_IN_ENABLED",
    "VOICE_FAST_BARGE_IN_ECHO_PROTECTION_SECONDS",
    "VOICE_FAST_BARGE_IN_RMS_THRESHOLD",
    "VOICE_FAST_BARGE_IN_REQUIRED_FRAMES",
)


def clear_voice_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in VOICE_ENV_KEYS:
        monkeypatch.delenv(
            key,
            raising=False,
        )


def test_voice_settings_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_voice_environment(monkeypatch)

    settings = VoiceSettings()

    assert (
        settings.default_turn_end_grace_seconds
        == 0.20
    )

    assert (
        settings.digit_turn_end_grace_seconds
        == 0.30
    )

    assert (
        settings.hamsa_normal_soft_timeout_seconds
        == 3.0
    )

    assert (
        settings.deepgram_normal_fallback_wait_seconds
        == 1.0
    )

    assert settings.barge_in_enabled is True

    assert settings.fast_barge_in_enabled is True

    assert (
        settings.fast_barge_in_required_frames
        == 2
    )


def test_voice_settings_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_voice_environment(monkeypatch)

    monkeypatch.setenv(
        "VOICE_HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS",
        "2.5",
    )

    monkeypatch.setenv(
        "VOICE_BARGE_IN_ENABLED",
        "0",
    )

    monkeypatch.setenv(
        "VOICE_FAST_BARGE_IN_REQUIRED_FRAMES",
        "3",
    )

    settings = VoiceSettings()

    assert (
        settings.hamsa_normal_soft_timeout_seconds
        == 2.5
    )

    assert settings.barge_in_enabled is False

    assert (
        settings.fast_barge_in_required_frames
        == 3
    )


def test_voice_settings_rejects_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_voice_environment(monkeypatch)

    monkeypatch.setenv(
        "VOICE_HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS",
        "-1",
    )

    with pytest.raises(ValidationError):
        VoiceSettings()


def test_voice_settings_rejects_invalid_rms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_voice_environment(monkeypatch)

    monkeypatch.setenv(
        "VOICE_FAST_BARGE_IN_RMS_THRESHOLD",
        "50000",
    )

    with pytest.raises(ValidationError):
        VoiceSettings()


def test_voice_settings_rejects_zero_required_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_voice_environment(monkeypatch)

    monkeypatch.setenv(
        "VOICE_FAST_BARGE_IN_REQUIRED_FRAMES",
        "0",
    )

    with pytest.raises(ValidationError):
        VoiceSettings()