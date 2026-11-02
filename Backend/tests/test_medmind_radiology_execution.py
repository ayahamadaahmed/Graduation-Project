from types import SimpleNamespace
from uuid import uuid4

import pytest

import medmind.service as service_module

from medmind.service import (
    MedMindService,
)

from medmind.memory.conversation import (
    ConversationMemory,
)

from medmind.state.store import (
    InMemoryStateStore,
)

from medmind.understanding.types import (
    NLUResult,
)

from medmind.diagnostic_attachment import (
    TrustedDiagnosticAttachment,
)


# ============================================================
# FAKE UNDERSTANDING
# ============================================================


class FakeUnderstanding:

    def __init__(
        self,
    ) -> None:

        self.calls = []

    async def understand(
        self,
        *,
        message,
        context,
    ):

        self.calls.append(
            {
                "message":
                    message,

                "context":
                    context,
            }
        )

        return SimpleNamespace(
            status="selected",

            capability=(
                "diagnostics.radiology.analyze"
            ),

            arguments={
                "modality":
                    "brain_mri",
            },

            attempts=1,

            used_broad_candidates=False,
        )


# ============================================================
# FAKE DIAGNOSTIC AGENT CLIENT
# ============================================================


class FakeDiagnosticAgentClient:

    def __init__(
        self,
    ) -> None:

        self.calls = []

    async def analyze_radiology(
        self,
        *,
        image_bytes,
        filename,
        content_type,
        modality,
    ):

        self.calls.append(
            {
                "image_bytes":
                    image_bytes,

                "filename":
                    filename,

                "content_type":
                    content_type,

                "modality":
                    modality,
            }
        )

        return SimpleNamespace(
            modality=modality,

            classification=(
                "pituitary"
            ),

            probabilities={
                "glioma": 0.02,
                "meningioma": 0.09,
                "notumor": 0.02,
                "pituitary": 0.87,
            },

            confidence=0.87,

            score_semantics="class_probability",

            inference_latency_ms=150.0,

            model_name=(
                "fake-brain-mri-model"
            ),

            model_version=(
                "test"
            ),

            limitations=[],
        )


# ============================================================
# TEST
# ============================================================


@pytest.mark.asyncio
async def test_radiology_execution_uses_trusted_attachment_and_modality(
    monkeypatch,
):

    understanding = (
        FakeUnderstanding()
    )

    diagnostic_client = (
        FakeDiagnosticAgentClient()
    )

    # --------------------------------------------------------
    # Keep this test focused on execution routing.
    #
    # The real adapter already has its own tests.
    # --------------------------------------------------------

    def fake_adapt_understanding_to_nlu(
        *,
        result,
        state,
    ):

        assert (
            result.capability
            == "diagnostics.radiology.analyze"
        )

        return NLUResult(
            intent="unknown",

            operation_type=None,

            confirmation="unknown",

            confidence=1.0,
        )

    monkeypatch.setattr(
        service_module,
        "adapt_understanding_to_nlu",
        fake_adapt_understanding_to_nlu,
    )

    # --------------------------------------------------------
    # Real lightweight state + memory.
    # --------------------------------------------------------

    state_store = (
        InMemoryStateStore()
    )

    memory = (
        ConversationMemory(
            recent_message_limit=12
        )
    )

    # --------------------------------------------------------
    # MedMind service.
    #
    # Components unrelated to this read path are deliberately
    # plain objects. They must never be called by this test.
    # --------------------------------------------------------

    service = MedMindService(
        tenant_id="clinic-001",

        agent=object(),

        nlu=object(),

        understanding=(
            understanding
        ),

        booking_workflow=object(),

        cancel_workflow=object(),

        reschedule_workflow=object(),

        state_store=(
            state_store
        ),

        memory=(
            memory
        ),

        tools=object(),

        diagnostic_agent_client=(
            diagnostic_client
        ),
    )

    # --------------------------------------------------------
    # Trusted attachment.
    # --------------------------------------------------------

    provider_id = uuid4()

    attachment = (
        TrustedDiagnosticAttachment(
            attachment_id=(
                "a" * 32
            ),

            provider_id=(
                provider_id
            ),

            session_id=(
                "radiology-session-1"
            ),

            original_filename=(
                "brain.jpg"
            ),

            content_type=(
                "image/jpeg"
            ),

            data=(
                b"fake-image-bytes"
            ),

            patient_id=None,

            encounter_id=None,
        )
    )

    # --------------------------------------------------------
    # Execute chat.
    # --------------------------------------------------------

    result = await service.chat(
        session_id=(
            "radiology-session-1"
        ),

        message=(
            "Analyze this brain MRI"
        ),

        channel="web",

        attachment_ids=[
            attachment.attachment_id
        ],

        trusted_attachments=[
            attachment
        ],
    )

    # --------------------------------------------------------
    # Understanding selected Radiology once.
    # --------------------------------------------------------

    assert len(
        understanding.calls
    ) == 1

    # --------------------------------------------------------
    # Diagnostic Agent was called exactly once.
    # --------------------------------------------------------

    assert len(
        diagnostic_client.calls
    ) == 1

    diagnostic_call = (
        diagnostic_client.calls[0]
    )

    # --------------------------------------------------------
    # Most important assertions:
    #
    # trusted bytes + metadata + explicit modality reached
    # DiagnosticAgentClient unchanged.
    # --------------------------------------------------------

    assert (
        diagnostic_call[
            "image_bytes"
        ]
        == b"fake-image-bytes"
    )

    assert (
        diagnostic_call[
            "filename"
        ]
        == "brain.jpg"
    )

    assert (
        diagnostic_call[
            "content_type"
        ]
        == "image/jpeg"
    )

    assert (
        diagnostic_call[
            "modality"
        ]
        == "brain_mri"
    )

    # --------------------------------------------------------
    # Ensure Radiology branch completed instead of falling
    # through to the generic read agent.
    # --------------------------------------------------------

    assert (
        result["route"]
        == "diagnostics_radiology"
    )

    assert (
        result["response_type"]
        == "diagnostic_radiology"
    )

    assert (
        result["language"]
        == "en"
    )

    assert (
        "brain MRI"
        in result["reply"]
    )

    assert (
        "'pituitary'"
        in result["reply"]
    )

    assert (
        "0.87"
        in result["reply"]
    )

    assert (
        "not a confirmed diagnosis"
        in result["reply"]
    )


    diagnostic_result = (
        result[
            "diagnostic_result"
        ]
    )

    assert diagnostic_result is not None

    assert (
        diagnostic_result["kind"]
        == "radiology"
    )

    assert (
        diagnostic_result[
            "schema_version"
        ]
        == "1.0"
    )

    assert (
        diagnostic_result[
            "attachment_id"
        ]
        == attachment.attachment_id
    )

    assert (
        diagnostic_result[
            "modality"
        ]
        == "brain_mri"
    )

    assert (
        diagnostic_result[
            "classification"
        ]
        == "pituitary"
    )

    assert (
        diagnostic_result[
            "confidence"
        ]
        == 0.87
    )

    assert (
        diagnostic_result[
            "model_name"
        ]
        == "fake-brain-mri-model"
    )

    assert (
        diagnostic_result[
            "model_version"
        ]
        == "test"
    )

@pytest.mark.asyncio
async def test_diagnostic_safety_guard_blocks_critical_symptoms_before_client_call(
    monkeypatch,
):

    understanding = (
        FakeUnderstanding()
    )

    diagnostic_client = (
        FakeDiagnosticAgentClient()
    )

    def fake_adapt_understanding_to_nlu(
        *,
        result,
        state,
    ):

        return NLUResult(
            intent="unknown",
            operation_type=None,
            confirmation="unknown",
            confidence=1.0,
        )

    monkeypatch.setattr(
        service_module,
        "adapt_understanding_to_nlu",
        fake_adapt_understanding_to_nlu,
    )

    state_store = (
        InMemoryStateStore()
    )

    memory = (
        ConversationMemory(
            recent_message_limit=12
        )
    )

    service = MedMindService(
        tenant_id="clinic-001",

        agent=object(),

        nlu=object(),

        understanding=(
            understanding
        ),

        booking_workflow=object(),

        cancel_workflow=object(),

        reschedule_workflow=object(),

        state_store=(
            state_store
        ),

        memory=(
            memory
        ),

        tools=object(),

        diagnostic_agent_client=(
            diagnostic_client
        ),
    )

    provider_id = uuid4()

    attachment = (
        TrustedDiagnosticAttachment(
            attachment_id=(
                "b" * 32
            ),

            provider_id=(
                provider_id
            ),

            session_id=(
                "radiology-safety-session-1"
            ),

            original_filename=(
                "brain.jpg"
            ),

            content_type=(
                "image/jpeg"
            ),

            data=(
                b"fake-image-bytes"
            ),

            patient_id=None,

            encounter_id=None,
        )
    )

    result = await service.chat(
        session_id=(
            "radiology-safety-session-1"
        ),

        message=(
            "I have chest pain with cold sweat "
            "and pain going to my arm"
        ),

        channel="web",

        attachment_ids=[
            attachment.attachment_id
        ],

        trusted_attachments=[
            attachment
        ],
    )

    assert len(
        understanding.calls
    ) == 1

    assert (
        len(
            diagnostic_client.calls
        )
        == 0
    )

    assert (
        result["route"]
        == "diagnostics_safety_guard"
    )

    assert (
        result["response_type"]
        == "diagnostic_safety"
    )

    assert (
        result["language"]
        == "en"
    )

    assert (
        "emergency"
        in result["reply"].lower()
    )

    diagnostic_result = (
        result[
            "diagnostic_result"
        ]
    )

    assert (
        diagnostic_result["kind"]
        == "diagnostic_safety"
    )

    assert (
        diagnostic_result["urgency"]
        == "critical"
    )

    assert (
        diagnostic_result["triggered_rules"]
    )

    assert (
        diagnostic_result["confirmation_field"]
        is None
    )
