"""Final caller transcripts never reach the Voice Gateway logs.

Drives the real consume_final_transcripts() with fake MedMind and TTS
clients. The fake MedMind call fails on purpose, so each transcript is
logged, forwarded once, and then dropped before any reply or audio is
produced. Synthetic data only; no network, no credentials.
"""

import ast
import asyncio
import logging
from pathlib import Path

import pytest

import voice_gateway.main as voice_main

# Synthetic test data (not real people or identifiers).
PATIENT_NAME = "زمردة قنديل"
NATIONAL_ID = "29001011234567"
PHONE = "01098765432"

CASES = [
    # (stage, transcript, expected digit_count or None for non-digit stages)
    ("awaiting_patient_name", PATIENT_NAME, None),
    ("awaiting_patient_name_correction", f"لا اسمي {PATIENT_NAME}", None),
    ("awaiting_national_id", NATIONAL_ID, 14),
    ("awaiting_national_id", " ".join(NATIONAL_ID), 14),
    ("awaiting_phone", PHONE, 11),
    ("new", f"عايز احجز باسم {PATIENT_NAME} ورقمي {PHONE}", None),
]

SENSITIVE_FRAGMENTS = [
    PATIENT_NAME,
    *PATIENT_NAME.split(),
    NATIONAL_ID,
    " ".join(NATIONAL_ID),
    PHONE,
]


class FakeMedMind:
    def __init__(self):
        self.messages = []

    async def warmup(self, **kwargs):
        return None

    async def start_session(self, **kwargs):
        return "mms_test_session"

    async def chat(self, *, message, **kwargs):
        self.messages.append(message)
        raise RuntimeError("synthetic backend failure")

    async def end_session(self, **kwargs):
        return None

    async def close(self):
        return None


class FakeTTS:
    """No warmup/aclose/close: the consumer skips those steps."""


async def consume_one(monkeypatch, stage, transcript):
    medmind = FakeMedMind()
    monkeypatch.setattr(voice_main, "MedMindClient", lambda: medmind)
    monkeypatch.setattr(voice_main, "create_tts_provider", lambda: ("fake", FakeTTS()))

    queue = asyncio.Queue()
    await queue.put(transcript)

    task = asyncio.create_task(
        voice_main.consume_final_transcripts(
            queue,
            websocket=None,
            channel_id="test-channel",
            tenant_id="test-tenant",
            audio_format="ulaw",
            conversation_state={"stage": stage},
            media_send_lock=asyncio.Lock(),
        )
    )

    for _ in range(500):
        if medmind.messages:
            break
        await asyncio.sleep(0.01)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return medmind


def logged_text(caplog):
    # Both the formatted message and the raw arguments, so nothing hides in args.
    parts = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.args))
        if record.exc_text:
            parts.append(record.exc_text)
    return "\n".join(parts)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage, transcript, digit_count", CASES)
async def test_final_transcript_content_is_never_logged(
    monkeypatch, caplog, stage, transcript, digit_count
):
    caplog.set_level(logging.DEBUG)

    medmind = await consume_one(monkeypatch, stage, transcript)

    # Behavior preserved: the full transcript is still forwarded to MedMind once.
    assert medmind.messages == [transcript]

    received = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("voice_final_transcript_received ")
    ]
    assert len(received) == 1
    assert f"stage={stage}" in received[0]
    assert f"transcript_chars={len(transcript)}" in received[0]
    if digit_count is None:
        assert "digit_count=" not in received[0]
    else:
        assert f"digit_count={digit_count}" in received[0]

    text = logged_text(caplog)
    assert transcript not in text
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in text, fragment


def test_consumer_never_passes_the_transcript_to_a_logger():
    path = Path(__file__).resolve().parents[1] / "voice_gateway" / "main.py"
    tree = ast.parse(path.read_bytes())
    consumer = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "consume_final_transcripts"
    )

    offending = []
    for node in ast.walk(consumer):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            for arg in node.args[1:]:
                if isinstance(arg, ast.Name) and arg.id == "transcript":
                    offending.append(node.lineno)

    assert offending == []
