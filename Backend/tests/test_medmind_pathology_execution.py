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
                "diagnostics.pathology.analyze"
            ),

            arguments={},

            attempts=1,

            used_broad_candidates=False,
        )


# ============================================================
# FAKE PATHOLOGY RESULT ITEM
# ============================================================


class FakePathologyResultItem:

    def model_dump(
        self,
        *,
        mode=None,
    ):

        return {
            "result_index":
                0,

            "panel":
                "cbc",

            "raw_name":
                "Hemoglobin",

            "canonical_name":
                "hemoglobin",

            "value":
                12.0,

            "unit":
                "g/dL",

            "reference_min":
                12.0,

            "reference_max":
                16.0,

            "reference_text":
                None,

            "flag":
                "normal",

            "mapping_status":
                "mapped",
        }


# ============================================================
# FAKE DIAGNOSTIC AGENT CLIENT
# ============================================================


class FakeDiagnosticAgentClient:

    def __init__(
        self,
    ) -> None:

        self.calls = []

    async def analyze_pathology(
        self,
        *,
        image_bytes,
        filename,
        content_type,
    ):

        self.calls.append(
            {
                "image_bytes":
                    image_bytes,

                "filename":
                    filename,

                "content_type":
                    content_type,
            }
        )

        return SimpleNamespace(
            schema_version="1.0",

            document_type="cbc",

            unreadable_fields=[],

            results=[
                FakePathologyResultItem()
            ],
        )


# ============================================================
# TEST
# ============================================================


@pytest.mark.asyncio
async def test_pathology_execution_uses_trusted_attachment(
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
    # --------------------------------------------------------

    def fake_adapt_understanding_to_nlu(
        *,
        result,
        state,
    ):

        assert (
            result.capability
            == "diagnostics.pathology.analyze"
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
    # Trusted lab-report attachment.
    # --------------------------------------------------------

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
                "pathology-session-1"
            ),

            original_filename=(
                "cbc.png"
            ),

            content_type=(
                "image/png"
            ),

            data=(
                b"fake-lab-image-bytes"
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
            "pathology-session-1"
        ),

        message=(
            "Analyze this blood test"
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
    # Understanding selected Pathology exactly once.
    # --------------------------------------------------------

    assert len(
        understanding.calls
    ) == 1

    # --------------------------------------------------------
    # Diagnostic Agent called exactly once.
    # --------------------------------------------------------

    assert len(
        diagnostic_client.calls
    ) == 1

    diagnostic_call = (
        diagnostic_client.calls[0]
    )

    # --------------------------------------------------------
    # Trusted bytes + metadata reached client unchanged.
    # --------------------------------------------------------

    assert (
        diagnostic_call[
            "image_bytes"
        ]
        == b"fake-lab-image-bytes"
    )

    assert (
        diagnostic_call[
            "filename"
        ]
        == "cbc.png"
    )

    assert (
        diagnostic_call[
            "content_type"
        ]
        == "image/png"
    )

    # --------------------------------------------------------
    # Ensure Pathology branch completed.
    # --------------------------------------------------------

    assert (
        result["route"]
        == "diagnostics_pathology"
    )

    assert (
        result["response_type"]
        == "diagnostic_pathology"
    )

    assert (
        result["language"]
        == "en"
    )

    assert (
        "The laboratory report was processed"
        in result["reply"]
    )

    assert (
        "No mapped result was flagged as low or high."
        in result["reply"]
    )

    assert (
        "do not establish a diagnosis"
        in result["reply"]
    )

    assert (
        "Hemoglobin:"
        not in result["reply"]
    )

    # --------------------------------------------------------
    # Structured pathology_result handoff.
    # --------------------------------------------------------

    diagnostic_result = (
        result[
            "diagnostic_result"
        ]
    )

    assert diagnostic_result is not None

    assert (
        diagnostic_result["kind"]
        == "pathology"
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
            "document_type"
        ]
        == "cbc"
    )

    assert (
        diagnostic_result[
            "unreadable_fields"
        ]
        == []
    )

    assert (
        len(
            diagnostic_result[
                "results"
            ]
        )
        == 1
    )

    pathology_item = (
        diagnostic_result[
            "results"
        ][0]
    )

    assert (
        pathology_item[
            "result_index"
        ]
        == 0
    )

    assert (
        pathology_item[
            "panel"
        ]
        == "cbc"
    )

    assert (
        pathology_item[
            "raw_name"
        ]
        == "Hemoglobin"
    )

    assert (
        pathology_item[
            "canonical_name"
        ]
        == "hemoglobin"
    )

    assert (
        pathology_item[
            "value"
        ]
        == 12.0
    )

    assert (
        pathology_item[
            "flag"
        ]
        == "normal"
    )

    assert (
        pathology_item[
            "mapping_status"
        ]
        == "mapped"
    )