from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def staging_selected(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """
    APP_ENV=staging in the PROCESS environment (trimmed,
    case-insensitive). Same rule as the backend
    (app/core/config.py staging_selected); duplicated because
    the Voice Gateway runs in its own environment without the
    app package. Never decided from a .env file.
    """

    env = os.environ if environ is None else environ

    return (
        env.get("APP_ENV")
        or ""
    ).strip().lower() == "staging"


def load_environment(
    dotenv_path: Path | None = None,
) -> bool:
    """
    Load local .env values without overriding variables already
    supplied by Docker, Azure, CI/CD, or the host environment.

    Production environment variables always take precedence.

    In staging (APP_ENV=staging in the process environment) no
    .env is loaded at all, so every value must come from the
    process environment. This runs when voice_gateway.main and
    voice_gateway.providers.hamsa_tts are imported.
    """

    if staging_selected():
        return False

    return load_dotenv(
        dotenv_path=dotenv_path or ENV_FILE,
        override=False,
    )


class VoiceSettings(BaseSettings):
    """
    Runtime configuration for the MedMind Voice Gateway.

    The goal is to keep voice timing and turn-taking configuration
    centralized and validated before accepting calls.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ============================================================
    # Turn taking
    # ============================================================

    default_turn_end_grace_seconds: float = Field(
        default=0.20,
        ge=0.0,
        le=5.0,
        validation_alias=(
            "VOICE_DEFAULT_TURN_END_GRACE_SECONDS"
        ),
    )

    digit_turn_end_grace_seconds: float = Field(
        default=0.30,
        ge=0.0,
        le=5.0,
        validation_alias=(
            "VOICE_DIGIT_TURN_END_GRACE_SECONDS"
        ),
    )

    digit_max_utterance_seconds: float = Field(
        default=4.0,
        gt=0.0,
        le=30.0,
        validation_alias=(
            "VOICE_DIGIT_MAX_UTTERANCE_SECONDS"
        ),
    )

    hamsa_preroll_seconds: float = Field(
        default=0.25,
        ge=0.0,
        le=2.0,
        validation_alias=(
            "VOICE_HAMSA_PREROLL_SECONDS"
        ),
    )

    # ============================================================
    # STT arbitration / fallback
    # ============================================================

    hamsa_normal_soft_timeout_seconds: float = Field(
        default=3.0,
        gt=0.0,
        le=30.0,
        validation_alias=(
            "VOICE_HAMSA_NORMAL_SOFT_TIMEOUT_SECONDS"
        ),
    )

    hamsa_digit_soft_timeout_seconds: float = Field(
        default=3.0,
        gt=0.0,
        le=30.0,
        validation_alias=(
            "VOICE_HAMSA_DIGIT_SOFT_TIMEOUT_SECONDS"
        ),
    )

    deepgram_normal_fallback_wait_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        validation_alias=(
            "VOICE_DEEPGRAM_NORMAL_FALLBACK_WAIT_SECONDS"
        ),
    )

    digit_incomplete_retry_seconds: float = Field(
        default=3.0,
        gt=0.0,
        le=30.0,
        validation_alias=(
            "VOICE_DIGIT_INCOMPLETE_RETRY_SECONDS"
        ),
    )

    # ============================================================
    # Barge-in
    # ============================================================

    barge_in_enabled: bool = Field(
        default=True,
        validation_alias="VOICE_BARGE_IN_ENABLED",
    )

    barge_in_min_speech_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=5.0,
        validation_alias=(
            "VOICE_BARGE_IN_MIN_SPEECH_SECONDS"
        ),
    )

    barge_in_initial_protection_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        validation_alias=(
            "VOICE_BARGE_IN_INITIAL_PROTECTION_SECONDS"
        ),
    )

    barge_in_cooldown_seconds: float = Field(
        default=0.60,
        ge=0.0,
        le=10.0,
        validation_alias=(
            "VOICE_BARGE_IN_COOLDOWN_SECONDS"
        ),
    )

    # ============================================================
    # Fast pre-VAD barge-in
    # ============================================================

    fast_barge_in_enabled: bool = Field(
        default=True,
        validation_alias=(
            "VOICE_FAST_BARGE_IN_ENABLED"
        ),
    )

    fast_barge_in_echo_protection_seconds: float = Field(
        default=0.10,
        ge=0.0,
        le=5.0,
        validation_alias=(
            "VOICE_FAST_BARGE_IN_ECHO_PROTECTION_SECONDS"
        ),
    )

    fast_barge_in_rms_threshold: float = Field(
        default=1700.0,
        gt=0.0,
        le=32767.0,
        validation_alias=(
            "VOICE_FAST_BARGE_IN_RMS_THRESHOLD"
        ),
    )

    fast_barge_in_required_frames: int = Field(
        default=2,
        ge=1,
        le=50,
        validation_alias=(
            "VOICE_FAST_BARGE_IN_REQUIRED_FRAMES"
        ),
    )


def get_voice_settings() -> VoiceSettings:
    """
    Build and validate the current Voice Gateway configuration.

    A ValidationError is intentionally allowed to propagate so that
    invalid production configuration fails during startup rather than
    causing unpredictable behavior during a live call.
    """

    return VoiceSettings()