from __future__ import annotations
import re
import unicodedata
from contextlib import (
    AsyncExitStack,
)
import httpx
from medmind.response_verbalizer import (
    QwenResponseVerbalizer,
)
from medmind.diagnostic_explanation import (
    SafeDiagnosticExplanationService,
)
from medmind.diagnostic_safety_guard import (
    DiagnosticSafetyGuardAgent,
    SafetyUrgency,
)
from medmind.medical_education_agent import (
    MedicalEducationAgent,
    MedicalEducationStatus,
)
from medmind.medical_evidence import (
    ExternalMedicalSource,
    MedicalEvidenceRetriever,
)
from mcp.client.streamable_http import (
    create_mcp_http_client,
)
from medmind.core.read_routing import (
    resolve_read_route,
)
from medmind.tenancy.context import TenantContext
import logging
import os
import time
from typing import Any
from medmind.resolvers.time import (
    resolve_time_candidates,
    resolve_time_reply_candidates,
)
from dotenv import (
    load_dotenv,
)
from medmind.resolvers.date import (
    resolve_date,
)

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)
import re
import unicodedata
from langchain_mcp_adapters.tools import (
    load_mcp_tools,
)

from langchain_openai import (
    ChatOpenAI,
)

from medmind.core.agent import (
    MedMindReadAgent,
)

from medmind.core.tool_executor import (
    MCPToolExecutor,
)

from medmind.core.tools import (
    select_read_tools,
)

from medmind.understanding.tenant_policy import (
    allowed_understanding_capabilities,
)

from medmind.language import (
    resolve_conversation_language,
)

from medmind.memory.conversation import (
    ConversationMemory,
)
from medmind.memory.models import (
    ChatMessage,
)

from medmind.rag_gateway import (
    answer_provider_knowledge,
)

from medmind.state.models import (
    ConversationChannel,
)

from medmind.state.context import (
    remember_conversation_focus,
    resolve_effective_context,
)

from medmind.state.store import (
    InMemoryStateStore,
)

from medmind.state.updater import (
    apply_tool_observation,
)

from medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from medmind.understanding.legacy_adapter import (
    adapt_understanding_to_nlu,
)

from medmind.understanding.llm import (
    LLMNLU,
)

from medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)

from medmind.understanding.tool_planner import (
    ToolPlanner,
)

from medmind.understanding.types import (
    NLUResult,
)

from medmind.workflows.booking import (
    BookingWorkflow,
)

from medmind.workflows.cancel import (
    CancelWorkflow,
)

from medmind.workflows.reschedule import (
    RescheduleWorkflow,
)
from medmind.diagnostic_attachment import (
    TrustedDiagnosticAttachment,
)

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)

async def _mcp_http_request_timing_hook(
    request: httpx.Request,
) -> None:

    if (
        request.method != "POST"
        or not request.url.path.endswith("/mcp")
    ):
        return

    request.extensions[
        "medmind_mcp_started_at"
    ] = time.perf_counter()


async def _mcp_http_response_timing_hook(
    response: httpx.Response,
) -> None:

    started_at = (
        response.request.extensions.get(
            "medmind_mcp_started_at"
        )
    )

    if started_at is None:
        return

    headers_ms = (
        (
            time.perf_counter()
            - started_at
        )
        * 1000
    )

    logger.info(
        "mcp_http_client_timing "
        "method=%s "
        "path=%s "
        "headers_ms=%.2f "
        "status_code=%s "
        "content_type=%s",
        response.request.method,
        response.request.url.path,
        headers_ms,
        response.status_code,
        response.headers.get(
            "content-type"
        ),
    )


def _create_instrumented_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:

    client = create_mcp_http_client(
        headers=headers,
        timeout=timeout,
        auth=auth,
    )

    client.event_hooks[
        "request"
    ].append(
        _mcp_http_request_timing_hook
    )

    client.event_hooks[
        "response"
    ].append(
        _mcp_http_response_timing_hook
    )

    return client

# ============================================================
# TURN ROUTING GROUPS
# ============================================================

ACTIVE_WRITE_OPERATIONS = frozenset(
    {
        "book_appointment",
        "cancel_appointment",
        "reschedule_appointment",
    }
)
DIAGNOSTIC_CAPABILITIES = frozenset(
    {
        "diagnostics.pathology.analyze",
        "diagnostics.radiology.analyze",
    }
)
INFORMATIONAL_CAPABILITIES = frozenset(
    {
        "provider.get_slots",
        "provider.get_working_hours",
        "provider.search_doctors",
        "provider.get_services",
        "provider.get_policy",
        "knowledge.search",

        # Read-only appointment discovery.
        # It may still require patient identity.
        "appointment.search",
    }
)

INFORMATIONAL_INTENTS = frozenset(
    {
        "ask_available_slots",
        "ask_working_hours",
        "ask_doctor",
        "ask_service",
        "ask_provider",
        "search_appointments",
    }
)

SIDE_READ_CONTEXT_FIELDS = (
    "conversation_specialty_id",
    "conversation_specialty_name",
    "conversation_doctor_id",
    "conversation_doctor_name",
    "conversation_service_id",
    "conversation_service_name",
    "conversation_date_text",
    "conversation_focus_capability",
)

# ============================================================
# GREETINGS
# ============================================================

_PURE_GREETINGS = frozenset(
    {
        "السلام عليكم",
        "السلام عليكم ورحمه الله",
        "السلام عليكم ورحمه الله وبركاته",
        "سلام عليكم",
        "سلا عليكم",
        "سلام",
        "اهلا",
        "اهلين",
        "مرحبا",
        "هاي",
        "ازيك",
        "صباح الخير",
        "مساء الخير",
        "hello",
        "hi",
        "hey",
    }
)


def _normalize_short_message(
    value: str,
) -> str:

    decomposed = unicodedata.normalize(
        "NFKD",
        value,
    )

    without_marks = "".join(
        character
        for character in decomposed
        if (
            unicodedata.category(
                character
            )
            != "Mn"
        )
    )

    without_punctuation = re.sub(
        r"[^\w\s]",
        " ",
        without_marks.lower(),
        flags=re.UNICODE,
    )

    return " ".join(
        without_punctuation.split()
    )


def _greeting_reply(
    message: str,
) -> str | None:

    normalized = (
        _normalize_short_message(
            message
        )
    )

    if normalized not in _PURE_GREETINGS:
        return None

    if normalized.startswith(
        (
            "السلام",
            "سلام",
            "سلا",
        )
    ):
        return (
            "وعليكم السلام، أهلاً بيك. "
            "أقدر أساعدك في الحجز أو "
            "المواعيد أو معلومات العيادة."
        )

    if normalized.startswith(
        "صباح"
    ):
        return (
            "صباح النور. "
            "أقدر أساعدك إزاي؟"
        )

    if normalized.startswith(
        "مساء"
    ):
        return (
            "مساء النور. "
            "أقدر أساعدك إزاي؟"
        )

    if normalized in {
        "hello",
        "hi",
        "hey",
    }:
        return (
            "Hello! How can I help you?"
        )

    return (
        "أهلاً وسهلاً بيك. "
        "أقدر أساعدك إزاي؟"
    )
# ============================================================
# SERVICE
# ============================================================

class MedMindService:

    def __init__(
        self,
        *,
        tenant_id: str,
        agent: MedMindReadAgent,
        nlu: LLMNLU,
        understanding: UnderstandingOrchestrator,
        booking_workflow: BookingWorkflow,
        cancel_workflow: CancelWorkflow,
        reschedule_workflow: RescheduleWorkflow,
        state_store: InMemoryStateStore,
        memory: ConversationMemory,
        tools: MCPToolExecutor,
        tenant_context: TenantContext | None = None,
        mcp_resources: AsyncExitStack | None = None,
        response_verbalizer: QwenResponseVerbalizer | None = None,
        diagnostic_agent_client: Any | None = None,
    ) -> None:

        
        if (
            tenant_context is not None
            and tenant_context.tenant_id != tenant_id
        ):
            raise ValueError(
                "tenant_context tenant_id does not match "
                "MedMindService tenant_id"
            )

        self.tenant_context = tenant_context

        self.tenant_id = (
            tenant_id
        )

        self.agent = (
            agent
        )

        self.response_verbalizer = (
            response_verbalizer
        )

        self.diagnostic_agent_client = (
            diagnostic_agent_client
        )

        self.diagnostic_explanation_service = (
            SafeDiagnosticExplanationService()
        )

        self.diagnostic_safety_guard = (
            DiagnosticSafetyGuardAgent()
        )

        self.medical_education_agent = (
            MedicalEducationAgent()
        )

        self.medical_evidence_retriever = (
            MedicalEvidenceRetriever()
        )
        
        self.nlu = (
            nlu
        )

        self.understanding = (
            understanding
        )

        self.booking_workflow = (
            booking_workflow
        )

        self.cancel_workflow = (
            cancel_workflow
        )

        self.reschedule_workflow = (
            reschedule_workflow
        )

        self.state_store = (
            state_store
        )

        self.memory = (
            memory
        )
        self.tools = tools
        self._mcp_resources = (
            mcp_resources
        )

        self._closed = False

    # ========================================================
    # RESOURCE CLEANUP
    # ========================================================

    async def close(
        self,
    ) -> None:

        if self._closed:
            return

        if (
            self._mcp_resources
            is not None
        ):

            await (
                self._mcp_resources
                .aclose()
            )

        self._closed = True

        logger.info(
            "medmind_service_closed "
            "tenant_id=%s",
            self.tenant_id,
        )

    # ========================================================
    # FACTORY
    # ========================================================

    @classmethod
    async def create(
        cls,
        tenant_id: str,
        tenant_context: TenantContext | None = None,
        capability_router: (
            SemanticCapabilityRouter
            | None
        ) = None,
        model: (
            ChatOpenAI
            | None
        ) = None,
        planner_model: (
            ChatOpenAI
            | None
        ) = None,
        planner: Any | None = None,
        response_verbalizer: QwenResponseVerbalizer | None = None,
        diagnostic_agent_client: Any | None = None,
    ) -> "MedMindService":

        create_started = (
            time.perf_counter()
        )

        # ====================================================
        # ENV / CONFIG
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        load_dotenv(
            override=True
        )

        dotenv_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        step_started = (
            time.perf_counter()
        )

        openai_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not openai_key:

            raise RuntimeError(
                "OPENAI_API_KEY is missing."
            )

        model_name = os.getenv(
            "OPENAI_MODEL",
            "gpt-4.1",
        )

        mcp_url = os.getenv(
            "MCP_URL",
            "http://127.0.0.1:9000/mcp",
        )

        resolved_tenant_id = (
            tenant_id
            or
            os.getenv(
                "TENANT_ID",
                "clinic-001",
            )
        )

        if tenant_context is not None:

            if (
                tenant_context.tenant_id
                != resolved_tenant_id
            ):
                raise ValueError(
                    "tenant_context tenant_id does not match "
                    "resolved tenant_id"
                )

        config_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # MCP CLIENT
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        client = (
            MultiServerMCPClient(
                {
                    "healthcare": {
                        "transport":
                            "http",

                        "url":
                            mcp_url,

                        "headers": {
                            "X-Tenant-ID":
                                resolved_tenant_id,
                        },

                        "httpx_client_factory":
                            _create_instrumented_mcp_http_client,
                    }
                }
            )
        )

        mcp_client_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # PERSISTENT MCP RESOURCES
        #
        # Important:
        #
        # MultiServerMCPClient.get_tools() creates a new
        # MCP session for every tool call.
        #
        # Instead, MedMind keeps one initialized session
        # alive for the lifetime of this tenant service.
        # ====================================================

        mcp_resources = (
            AsyncExitStack()
        )

        await (
            mcp_resources
            .__aenter__()
        )

        mcp_resources_transferred = (
            False
        )

        try:

            # ================================================
            # MCP SESSION + TOOL DISCOVERY
            # ================================================

            step_started = (
                time.perf_counter()
            )

            mcp_session = await (
                mcp_resources
                .enter_async_context(
                    client.session(
                        "healthcare"
                    )
                )
            )

            all_tools = await (
                load_mcp_tools(
                    mcp_session,

                    callbacks=(
                        client.callbacks
                    ),

                    tool_interceptors=(
                        client
                        .tool_interceptors
                    ),

                    server_name=(
                        "healthcare"
                    ),

                    tool_name_prefix=(
                        client
                        .tool_name_prefix
                    ),

                    handle_tool_errors=(
                        client
                        .handle_tool_errors
                    ),
                )
            )

            mcp_get_tools_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # TOOL FILTERING
            # ================================================

            step_started = (
                time.perf_counter()
            )

            read_tools = (
                select_read_tools(
                    all_tools,
                    tenant_context=
                        tenant_context,
                )
            )

            read_tools_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # TOOL EXECUTOR
            # ================================================

            step_started = (
                time.perf_counter()
            )

            tool_executor = (
                MCPToolExecutor(
                    all_tools
                )
            )

            tool_executor_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # SHARED LLM
            # ================================================

            step_started = (
                time.perf_counter()
            )

            if model is None:

                model = (
                    ChatOpenAI(
                        model=model_name,
                        temperature=0,
                        timeout=60,
                    )
                )

            if (
                planner is None
                and planner_model is None
            ):

                planner_model_name = (
                    os.getenv(
                        "PLANNER_MODEL",
                        "gpt-4.1",
                    )
                )

                planner_model = (
                    ChatOpenAI(
                        model=(
                            planner_model_name
                        ),
                        temperature=0,
                        timeout=60,
                    )
                )

            model_init_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # LEGACY NLU
            # ================================================

            step_started = (
                time.perf_counter()
            )

            nlu = (
                LLMNLU(
                    model=model
                )
            )

            legacy_nlu_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # UNIFIED UNDERSTANDING CONFIG
            # ================================================

            understanding_top_k = int(
                os.getenv(
                    "UNDERSTANDING_TOP_K",
                    "8",
                )
            )

            understanding_timeout_seconds = (
                float(
                    os.getenv(
                        "UNDERSTANDING_TIMEOUT",
                        "5",
                    )
                )
            )

            if (
                understanding_timeout_seconds
                <= 0
            ):

                raise RuntimeError(
                    "UNDERSTANDING_TIMEOUT "
                    "must be greater than zero."
                )

            understanding_router_timeout_seconds = (
                float(
                    os.getenv(
                        "UNDERSTANDING_ROUTER_TIMEOUT",
                        "2",
                    )
                )
            )

            if (
                understanding_router_timeout_seconds
                <= 0
            ):
                raise RuntimeError(
                    "UNDERSTANDING_ROUTER_TIMEOUT "
                    "must be greater than zero."
                )    
            # ================================================
            # SEMANTIC ROUTER
            #
            # Important:
            # This may initialize the embedding
            # model/tokenizer.
            # ================================================
            step_started = (
                time.perf_counter()
            )

            if capability_router is None:

                capability_router = (
                    SemanticCapabilityRouter()
                )

            semantic_router_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # TOOL PLANNER
            # ================================================

            step_started = (
                time.perf_counter()
            )

            if planner is None:

                if planner_model is None:

                    raise RuntimeError(
                        "planner_model is required "
                        "when no planner is provided."
                    )

                tool_planner = (
                    ToolPlanner(
                        model=planner_model,
                    )
                )

            else:

                tool_planner = (
                    planner
                )

            tool_planner_init_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # UNDERSTANDING ORCHESTRATOR
            # ================================================

            step_started = (
                time.perf_counter()
            )

            understanding_allowed_capabilities = (
                allowed_understanding_capabilities(
                    tenant_context
                )
            )

            understanding = (
                    UnderstandingOrchestrator(
                    router=capability_router,
                    planner=tool_planner,
                    top_k=understanding_top_k,
                    total_timeout_seconds=(
                        understanding_timeout_seconds
                    ),
                    router_timeout_seconds=(
                        understanding_router_timeout_seconds
                    ),
                    allowed_capabilities=(
                        understanding_allowed_capabilities
                    ),
                )
            )

            orchestrator_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # READ AGENT
            # ================================================

            step_started = (
                time.perf_counter()
            )

            agent = (
                MedMindReadAgent(
                    model=model,
                    tools=read_tools,
                    tenant_context=
                        tenant_context,
                )
            )

            read_agent_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # DETERMINISTIC WORKFLOWS
            # ================================================

            step_started = (
                time.perf_counter()
            )

            booking_workflow = (
                BookingWorkflow(
                    tools=tool_executor
                )
            )

            cancel_workflow = (
                CancelWorkflow(
                    tools=tool_executor
                )
            )

            reschedule_workflow = (
                RescheduleWorkflow(
                    tools=tool_executor
                )
            )

            workflows_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # MEMORY + STATE
            # ================================================

            step_started = (
                time.perf_counter()
            )

            memory = (
                ConversationMemory(
                    recent_message_limit=12
                )
            )

            state_store = (
                InMemoryStateStore()
            )

            memory_state_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # SERVICE OBJECT
            # ================================================

            step_started = (
                time.perf_counter()
            )

            service = cls(
                tenant_id=(
                    resolved_tenant_id
                ),

                agent=(
                    agent
                ),

                nlu=(
                    nlu
                ),

                diagnostic_agent_client=(
                    diagnostic_agent_client
                ),

                understanding=(
                    understanding
                ),

                booking_workflow=(
                    booking_workflow
                ),

                tools=
                    tool_executor,

                cancel_workflow=(
                    cancel_workflow
                ),

                reschedule_workflow=(
                    reschedule_workflow
                ),

                state_store=(
                    state_store
                ),

                memory=(
                    memory
                ),

                tenant_context=tenant_context,

                mcp_resources=(
                    mcp_resources
                ),

                response_verbalizer=(
                    response_verbalizer
                ),
            )

            service_object_ms = (
                time.perf_counter()
                - step_started
            ) * 1000

            # ================================================
            # TOTAL
            # ================================================

            total_ms = (
                time.perf_counter()
                - create_started
            ) * 1000

            logger.info(
                "medmind_service_create_timing "
                "dotenv_ms=%.2f "
                "config_ms=%.2f "
                "mcp_client_ms=%.2f "
                "mcp_get_tools_ms=%.2f "
                "read_tools_ms=%.2f "
                "tool_executor_ms=%.2f "
                "model_init_ms=%.2f "
                "legacy_nlu_ms=%.2f "
                "semantic_router_ms=%.2f "
                "tool_planner_init_ms=%.2f "
                "orchestrator_ms=%.2f "
                "read_agent_ms=%.2f "
                "workflows_ms=%.2f "
                "memory_state_ms=%.2f "
                "service_object_ms=%.2f "
                "tool_count=%s "
                "read_tool_count=%s "
                "total_ms=%.2f",
                dotenv_ms,
                config_ms,
                mcp_client_ms,
                mcp_get_tools_ms,
                read_tools_ms,
                tool_executor_ms,
                model_init_ms,
                legacy_nlu_ms,
                semantic_router_ms,
                tool_planner_init_ms,
                orchestrator_ms,
                read_agent_ms,
                workflows_ms,
                memory_state_ms,
                service_object_ms,
                len(
                    all_tools
                ),
                len(
                    read_tools
                ),
                total_ms,
            )

            # ================================================
            # RESOURCE OWNERSHIP TRANSFER
            #
            # From this point onward, MedMindService.close()
            # is responsible for closing the MCP session.
            # ================================================

            mcp_resources_transferred = (
                True
            )

            return service

        finally:

            # ================================================
            # FAILURE CLEANUP
            #
            # If anything failed after the persistent MCP
            # session was opened but before ownership was
            # transferred to the MedMindService instance,
            # close the entire stack immediately.
            # ================================================

            if not mcp_resources_transferred:

                await (
                    mcp_resources
                    .aclose()
                )

                logger.warning(
                    "medmind_service_create_cleanup "
                    "mcp_resources_closed=True"
                )

    # ========================================================
    # UNDERSTANDING CLARIFICATION
    # ========================================================

    @staticmethod
    def _understanding_clarification_reply(
        language: str,
        *,
        state=None,
    ) -> str:

        # ========================================================
        # Voice booking: service-specific clarification
        # ========================================================

        if (
            state is not None
            and getattr(state, "channel", None) == "voice"
            and getattr(state, "operation_type", None)
                == "book_appointment"
            and getattr(state, "stage", None)
                == "awaiting_service"
        ):

            if language == "en":
                return (
                    "Could you tell me the service you want, "
                    "or what you'd like treated?"
                )

            return (
                "ممكن توضّحلي أكتر؟ "
                "قولي الخدمة اللي عايزها، "
                "أو المشكلة اللي عايز تعالجها."
            )

        # ========================================================
        # Existing behavior for all other cases
        # ========================================================

        if language == "en":

            return (
                "Could you clarify what you'd like to do? "
                "For example, you can book an appointment, "
                "view your appointments, cancel one, "
                "reschedule one, or check available times."
            )

        return (
            "ممكن توضّح تقصد إيه بالضبط؟ "
            "لو بخصوص الحجز، ممكن تقول عايز تحجز، "
            "تعرض حجوزاتك، تلغي حجز، تغيّر ميعاد، "
            "ولا تشوف المواعيد المتاحة."
        )

    async def _handle_available_slots_read(
        self,
        *,
        state,
        nlu: NLUResult,
        language: str,
        channel: ConversationChannel,
    ) -> tuple[str, str]:

        context = resolve_effective_context(
            state=state,
            nlu=nlu,
        )

        date_text = context.date_text
        doctor_id = context.doctor_id
        doctor_name = context.doctor_name
        specialty_id = context.specialty_id
        specialty_name = context.specialty_name

        if (
            self._explicit_doctor_changed(
                state=state,
                nlu=nlu,
            )
            and
            not nlu.entities.specialty_name
        ):

            # A newly named doctor must not be constrained by a
            # stale specialty inherited from the previous doctor.
            # Resolve the doctor broadly, then trust the doctor's
            # backend specialty snapshot.
            specialty_id = None
            specialty_name = None

        # ========================================================
        # DATE REQUIRED
        # ========================================================

        if not date_text:

            if language == "en":
                return (
                    "Which day would you like to check availability for?",
                    "ask_slots_date",
                )

            return (
                "تحبي تعرفي المواعيد المتاحة ليوم إيه؟",
                "ask_slots_date",
            )

        resolved_date = resolve_date(
            date_text
        )

        if resolved_date is None:

            if language == "en":
                return (
                    "I couldn't understand that date. "
                    "You can say tomorrow or give me a specific date.",
                    "invalid_slots_date",
                )

            return (
                "مش قادر أحدد التاريخ ده. "
                "ممكن تقولي مثلاً بكرة أو تاريخ معين.",
                "invalid_slots_date",
            )

        slot_date = resolved_date.isoformat()

        # A read availability date is useful for a following:
        # "احجزلي الساعة 2".
        state.conversation_date_text = slot_date

        # ========================================================
        # SPECIALTY NAME -> TRUSTED SPECIALTY
        # ========================================================

        if (
            specialty_name
            and
            not specialty_id
        ):

            specialties_result = await self.tools.call(
                "list_specialties"
            )

            specialties_result = (
                self._ensure_list_result(
                    specialties_result
                )
            )

            apply_tool_observation(
                state=state,
                tool_name="list_specialties",
                data=specialties_result,
            )

            specialty = self._find_specialty_for_read(
                specialties=specialties_result,
                specialty_name=specialty_name,
            )

            if specialty is None:

                if language == "en":
                    return (
                        "I couldn't find that specialty.",
                        "slots_specialty_not_found",
                    )

                return (
                    "مش لاقي التخصص ده حالياً.",
                    "slots_specialty_not_found",
                )

            specialty_id = str(
                specialty.get("id")
            )

            specialty_name = (
                specialty.get("name_en")
                if language == "en"
                else specialty.get("name_ar")
            ) or (
                specialty.get("name_ar")
                or specialty.get("name_en")
            )

            self._remember_specialty_for_read(
                state=state,
                specialty_id=specialty_id,
                specialty_name=specialty_name,
            )

        # ========================================================
        # SPECIALTY WITHOUT DOCTOR
        #
        # Do not silently claim that provider-wide slots are
        # specialty-specific. Resolve the specialty doctors.
        # ========================================================

        if (
            not doctor_id
            and
            not doctor_name
            and
            specialty_id
        ):

            doctors_result = await self.tools.call(
                "list_doctors",
                specialty_id=specialty_id,
                limit=100,
            )

            apply_tool_observation(
                state=state,
                tool_name="list_doctors",
                data=doctors_result,
            )

            doctors = list(
                state.recent_doctors
            )

            if not doctors:

                if language == "en":
                    return (
                        f"There are no doctors available for "
                        f"{specialty_name or 'that specialty'}.",
                        "slots_no_doctors",
                    )

                return (
                    f"مفيش دكاترة متاحين في تخصص "
                    f"{specialty_name or 'ده'} حالياً.",
                    "slots_no_doctors",
                )

            if len(doctors) == 1:

                doctor = doctors[0]

                (
                    doctor_id,
                    doctor_name,
                ) = self._remember_doctor_for_read(
                    state=state,
                    doctor=doctor,
                    language=language,
                )

            else:

                doctor_names = [
                    self._doctor_display_name(
                        doctor,
                        language,
                    )
                    for doctor in doctors
                ]

                doctor_names = [
                    name
                    for name in doctor_names
                    if name
                ]

                if language == "en":
                    return (
                        "Which doctor do you mean? "
                        + ", ".join(
                            doctor_names
                        )
                        + ".",
                        "ask_slots_doctor",
                    )

                return (
                    "تقصدي أنهي دكتور؟ "
                    + "، ".join(
                        doctor_names
                    )
                    + ".",
                    "ask_slots_doctor",
                )

        # ========================================================
        # DOCTOR NAME -> TRUSTED DOCTOR ID
        # ========================================================

        if (
            not doctor_id
            and
            doctor_name
        ):

            doctor_arguments = {
                "limit": 100,
            }

            if specialty_id:
                doctor_arguments[
                    "specialty_id"
                ] = specialty_id

            doctors_result = (
                self._ensure_list_result(
                    doctors_result
                )
            )

            apply_tool_observation(
                state=state,
                tool_name="list_doctors",
                data=doctors_result,
            )

            apply_tool_observation(
                state=state,
                tool_name="list_doctors",
                data=doctors_result,
            )

            doctor = self._find_doctor_for_read(
                state=state,
                doctor_name=doctor_name,
            )

            if doctor is None:

                doctor_names = [
                    self._doctor_display_name(
                        item,
                        language,
                    )
                    for item in state.recent_doctors
                ]

                doctor_names = [
                    name
                    for name in doctor_names
                    if name
                ]

                if language == "en":

                    if doctor_names:
                        return (
                            "I couldn't match that doctor. "
                            "Available doctors are: "
                            + ", ".join(
                                doctor_names
                            )
                            + ".",
                            "slots_doctor_not_found",
                        )

                    return (
                        "I couldn't find that doctor.",
                        "slots_doctor_not_found",
                    )

                if doctor_names:
                    return (
                        "مش لاقي الدكتور ده. "
                        "الدكاترة المتاحين: "
                        + "، ".join(
                            doctor_names
                        )
                        + ".",
                        "slots_doctor_not_found",
                    )

                return (
                    "مش لاقي الدكتور ده حالياً.",
                    "slots_doctor_not_found",
                )

            (
                doctor_id,
                doctor_name,
            ) = self._remember_doctor_for_read(
                state=state,
                doctor=doctor,
                language=language,
            )

        elif doctor_id:

            state.conversation_doctor_id = (
                doctor_id
            )

            if doctor_name:
                state.conversation_doctor_name = (
                    doctor_name
                )

        # ========================================================
        # TRUSTED BACKEND LOOKUP
        # ========================================================

        arguments = {
            "slot_date": slot_date,
            "limit": 100,
        }

        if doctor_id:
            arguments[
                "doctor_id"
            ] = doctor_id

        slots_result = await self.tools.call(
            "list_available_slots",
            **arguments,
        )

        apply_tool_observation(
            state=state,
            tool_name="list_available_slots",
            data=slots_result,
        )

        available_slots = [
            slot
            for slot in state.recent_slots
            if (
                getattr(
                    slot,
                    "status",
                    "available",
                )
                == "available"
            )
        ]

        if not available_slots:

            if language == "en":
                return (
                    f"There are no available appointments on {slot_date}.",
                    "no_available_slots",
                )

            return (
                f"مفيش مواعيد متاحة يوم {slot_date}.",
                "no_available_slots",
            )

        unique_times = []
        seen_times = set()

        for slot in available_slots:

            time_value = (
                slot.start_time[:5]
            )

            if (
                not time_value
                or
                time_value in seen_times
            ):
                continue

            seen_times.add(
                time_value
            )

            unique_times.append(
                time_value
            )

        unique_times.sort()

        times_text = "، ".join(
            unique_times
        )

        normalized_date_text = (
            date_text
            .strip()
            .lower()
        )

        tomorrow_expressions = {
            "بكرة",
            "بكره",
            "غدا",
            "غداً",
            "tomorrow",
        }

        is_tomorrow = (
            normalized_date_text
            in tomorrow_expressions
        )

        if language == "en":

            if is_tomorrow:
                reply = (
                    "The available appointments tomorrow are: "
                    f"{times_text}."
                )
            else:
                reply = (
                    f"The available appointments on {slot_date} are: "
                    f"{times_text}."
                )

        else:

            if is_tomorrow:
                reply = (
                    f"المواعيد المتاحة بكرة هي: {times_text}."
                )
            else:
                reply = (
                    f"المواعيد المتاحة يوم {slot_date} هي: {times_text}."
                )

        return (
            reply,
            "available_slots",
        )

    @staticmethod
    def _ensure_list_result(
        value,
    ) -> list:

        if value is None:
            return []

        if isinstance(
            value,
            list,
        ):
            return value

        if isinstance(
            value,
            dict,
        ):

            # MCP may unwrap a one-item array
            # into a single dictionary.
            return [
                value
            ]

        return []
    # ============================================================
    # DOCTOR LOOKUP HELPERS
    # ============================================================

    @staticmethod
    def _normalize_doctor_lookup_name(
        value: str | None,
    ) -> str:

        if not value:
            return ""

        normalized = (
            value
            .strip()
            .casefold()
            .replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
        )

        tokens = (
            normalized.split()
        )

        doctor_titles = {
            "د",
            "د.",
            "دكتور",
            "دكتوره",
            "الدكتور",
            "الدكتوره",
            "dr",
            "dr.",
            "doctor",
        }

        while (
            tokens
            and
            tokens[0]
            in doctor_titles
        ):

            tokens.pop(0)

        return " ".join(
            tokens
        )

    @classmethod
    def _explicit_doctor_changed(
        cls,
        *,
        state,
        nlu: NLUResult,
    ) -> bool:

        current = (
            nlu.entities.doctor_name
        )

        if not current:
            return False

        current_normalized = (
            cls._normalize_doctor_lookup_name(
                current
            )
        )

        if not current_normalized:
            return False

        previous_names = [
            state.doctor_name,
            state.conversation_doctor_name,
        ]

        previous_names = [
            name
            for name in previous_names
            if name
        ]

        if not previous_names:
            return False

        return all(
            current_normalized
            !=
            cls._normalize_doctor_lookup_name(
                previous
            )
            for previous in previous_names
        )


    @staticmethod
    def _normalize_specialty_lookup_name(
        value: str | None,
    ) -> str:

        if not value:
            return ""

        normalized = unicodedata.normalize(
            "NFKD",
            value,
        )

        # Remove Arabic diacritics.
        normalized = "".join(
            char
            for char in normalized
            if not unicodedata.combining(
                char
            )
        )

        normalized = (
            normalized
            .strip()
            .casefold()
            .replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
            .replace("ـ", "")
        )

        # Remove punctuation such as ? ؟ , .
        normalized = re.sub(
            r"[^\w\s]",
            " ",
            normalized,
        )

        normalized = re.sub(
            r"\s+",
            " ",
            normalized,
        ).strip()

        return normalized


    @classmethod
    def _find_specialty_for_read(
        cls,
        *,
        specialties,
        specialty_name: str,
    ):

        query = (
            cls
            ._normalize_specialty_lookup_name(
                specialty_name
            )
        )

        if not query:
            return None

        # ========================================================
        # EXACT MATCH
        # ========================================================

        for specialty in specialties:

            if not isinstance(
                specialty,
                dict,
            ):
                continue

            candidates = [
                specialty.get(
                    "name_ar"
                ),
                specialty.get(
                    "name_en"
                ),
                specialty.get(
                    "code"
                ),
            ]

            for candidate in candidates:

                if (
                    query
                    ==
                    cls
                    ._normalize_specialty_lookup_name(
                        candidate
                    )
                ):

                    return specialty

        # ========================================================
        # UNIQUE PARTIAL MATCH
        # ========================================================

        matches = []

        for specialty in specialties:

            if not isinstance(
                specialty,
                dict,
            ):
                continue

            candidates = [
                specialty.get(
                    "name_ar"
                ),
                specialty.get(
                    "name_en"
                ),
                specialty.get(
                    "code"
                ),
            ]

            matched = False

            query_tokens = set(
                query.split()
            )

            for candidate in candidates:

                candidate_normalized = (
                    cls
                    ._normalize_specialty_lookup_name(
                        candidate
                    )
                )

                if not candidate_normalized:
                    continue

                candidate_tokens = set(
                    candidate_normalized.split()
                )

                # Direct partial match.
                if (
                    query in candidate_normalized
                    or
                    candidate_normalized in query
                ):

                    matched = True
                    break

                if (
                    query_tokens
                    and
                    candidate_tokens
                    and
                    (
                        query_tokens
                        & candidate_tokens
                    )
                ):

                    matched = True
                    break

            if matched:

                matches.append(
                    specialty
                )

        if len(matches) == 1:

            return matches[0]

        return None

    @classmethod
    def _find_doctor_for_read(
        cls,
        *,
        state,
        doctor_name: str,
    ):

        query = (
            cls
            ._normalize_doctor_lookup_name(
                doctor_name
            )
        )

        if not query:

            return None

        # ========================================================
        # EXACT MATCH
        # ========================================================

        for doctor in (
            state.recent_doctors
        ):

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
            ]

            for candidate in candidates:

                if (
                    query
                    ==
                    cls
                    ._normalize_doctor_lookup_name(
                        candidate
                    )
                ):

                    return doctor

        # ========================================================
        # UNIQUE PARTIAL MATCH
        # ========================================================

        matches = []

        for doctor in (
            state.recent_doctors
        ):

            candidates = [
                doctor.full_name_ar,
                doctor.full_name_en,
            ]

            for candidate in candidates:

                candidate_normalized = (
                    cls
                    ._normalize_doctor_lookup_name(
                        candidate
                    )
                )

                if (
                    candidate_normalized
                    and
                    (
                        query
                        in candidate_normalized
                        or
                        candidate_normalized
                        in query
                    )
                ):

                    matches.append(
                        doctor
                    )

                    break

        if len(matches) == 1:

            return matches[0]

        return None

    @staticmethod
    def _normalize_service_lookup_name(
        value: str | None,
    ) -> str:

        if not value:
            return ""

        text = unicodedata.normalize(
            "NFKD",
            str(value),
        )

        text = "".join(
            char
            for char in text
            if not unicodedata.combining(char)
        )

        text = (
            text
            .strip()
            .casefold()
            .replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ى", "ي")
            .replace("ة", "ه")
            .replace("ـ", "")
        )

        text = re.sub(
            r"[^\w\u0600-\u06ff]+",
            " ",
            text,
        )

        words = []

        for word in text.split():

            if word.startswith("ال") and len(word) > 3:
                word = word[2:]

            if word:
                words.append(word)

        return " ".join(words)

    @classmethod
    def _find_service_for_read(
        cls,
        *,
        state,
        service_name: str,
    ):

        query = cls._normalize_service_lookup_name(
            service_name
        )

        if not query:
            return None

        ignored_tokens = {
            "سعر",
            "اسعار",
            "بكام",
            "كام",
            "تكلفه",
            "ثمن",
            "هو",
            "هي",
            "طب",
            "طيب",
            "عايز",
            "عايزه",
            "اعرف",
            "الخدمه",
            "خدمه",
        }

        query_tokens = {
            token
            for token in query.split()
            if token and token not in ignored_tokens
        }

        matches = []

        for service in state.recent_services:

            candidates = [
                getattr(service, "name_ar", None),
                getattr(service, "name_en", None),
                getattr(service, "code", None),
                getattr(service, "voice_label_ar", None),
                getattr(service, "voice_label_en", None),
            ]

            best_score = 0

            for candidate in candidates:

                candidate_normalized = (
                    cls._normalize_service_lookup_name(
                        candidate
                    )
                )

                if not candidate_normalized:
                    continue

                if query == candidate_normalized:
                    best_score = max(best_score, 100)

                elif query in candidate_normalized:
                    best_score = max(best_score, 90)

                elif candidate_normalized in query:
                    best_score = max(best_score, 85)

                candidate_tokens = set(
                    candidate_normalized.split()
                )

                overlap = 0

                for query_token in query_tokens:
                    for candidate_token in candidate_tokens:
                        if (
                            query_token == candidate_token
                            or query_token in candidate_token
                            or candidate_token in query_token
                        ):
                            overlap += 1

                if overlap:
                    best_score = max(
                        best_score,
                        overlap * 10,
                    )

            if best_score > 0:
                matches.append(
                    (
                        best_score,
                        service,
                    )
                )

        matches.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if not matches:
            return None

        if (
            len(matches) > 1
            and
            matches[0][0] == matches[1][0]
        ):
            return None

        return matches[0][1]
    
    @staticmethod
    def _doctor_display_name(
        doctor,
        language: str,
    ) -> str | None:

        if language == "en":
            return (
                getattr(
                    doctor,
                    "full_name_en",
                    None,
                )
                or
                getattr(
                    doctor,
                    "full_name_ar",
                    None,
                )
            )

        return (
            getattr(
                doctor,
                "full_name_ar",
                None,
            )
            or
            getattr(
                doctor,
                "full_name_en",
                None,
            )
        )


    @staticmethod
    def _service_display_name(
        service,
        language: str,
    ) -> str | None:

        if language == "en":
            return (
                getattr(
                    service,
                    "name_en",
                    None,
                )
                or
                getattr(
                    service,
                    "name_ar",
                    None,
                )
            )

        return (
            getattr(
                service,
                "name_ar",
                None,
            )
            or
            getattr(
                service,
                "name_en",
                None,
            )
        )


    @staticmethod
    def _remember_specialty_for_read(
        *,
        state,
        specialty_id: str | None,
        specialty_name: str | None,
    ) -> None:

        if not specialty_id and not specialty_name:
            return

        previous_specialty_id = (
            state.conversation_specialty_id
            or
            state.specialty_id
        )

        specialty_changed = (
            previous_specialty_id is not None
            and
            specialty_id is not None
            and
            str(
                previous_specialty_id
            )
            != str(
                specialty_id
            )
        )

        if specialty_changed:

            state.doctor_id = None
            state.doctor_name = None

            state.service_id = None
            state.service_name = None

            state.conversation_doctor_id = None
            state.conversation_doctor_name = None

            state.conversation_service_id = None
            state.conversation_service_name = None

            state.recent_doctors = []
            state.recent_services = []

        if specialty_id:
            state.specialty_id = str(
                specialty_id
            )

            state.conversation_specialty_id = str(
                specialty_id
            )

        if specialty_name:
            state.specialty_name = (
                specialty_name
            )

            state.conversation_specialty_name = (
                specialty_name
            )


    @classmethod
    def _remember_doctor_for_read(
        cls,
        *,
        state,
        doctor,
        language: str,
    ) -> tuple[str, str | None]:

        doctor_id = str(
            doctor.id
        )

        doctor_name = cls._doctor_display_name(
            doctor,
            language,
        )

        previous_doctor_id = (
            state.conversation_doctor_id
            or
            state.doctor_id
        )

        doctor_changed = (
            previous_doctor_id is not None
            and
            str(
                previous_doctor_id
            )
            != doctor_id
        )

        if doctor_changed:

            state.service_id = None
            state.service_name = None

            state.conversation_service_id = None
            state.conversation_service_name = None

            state.recent_services = []

        state.doctor_id = doctor_id
        state.doctor_name = doctor_name

        state.conversation_doctor_id = (
            doctor_id
        )

        state.conversation_doctor_name = (
            doctor_name
        )

        specialty_id = getattr(
            doctor,
            "specialty_id",
            None,
        )

        specialty_name = (
            getattr(
                doctor,
                "specialty_name_en",
                None,
            )
            if language == "en"
            else
            getattr(
                doctor,
                "specialty_name_ar",
                None,
            )
        ) or (
            getattr(
                doctor,
                "specialty_name_ar",
                None,
            )
            or
            getattr(
                doctor,
                "specialty_name_en",
                None,
            )
        )

        if specialty_id or specialty_name:

            cls._remember_specialty_for_read(
                state=state,
                specialty_id=(
                    str(
                        specialty_id
                    )
                    if specialty_id
                    else None
                ),
                specialty_name=specialty_name,
            )

            # _remember_specialty_for_read only invalidates the
            # old doctor when the SPECIALTY changed. Re-assert
            # this freshly resolved doctor afterwards.
            state.doctor_id = doctor_id
            state.doctor_name = doctor_name
            state.conversation_doctor_id = doctor_id
            state.conversation_doctor_name = doctor_name

        return (
            doctor_id,
            doctor_name,
        )


    @classmethod
    def _remember_service_for_read(
        cls,
        *,
        state,
        service,
        language: str,
    ) -> tuple[str, str | None]:

        service_id = str(
            service.id
        )

        service_name = cls._service_display_name(
            service,
            language,
        )

        state.service_id = service_id
        state.service_name = service_name

        state.conversation_service_id = (
            service_id
        )

        state.conversation_service_name = (
            service_name
        )

        return (
            service_id,
            service_name,
        )

    @staticmethod
    def _ensure_list_result(
        value,
    ) -> list:

        if value is None:
            return []

        if isinstance(
            value,
            list,
        ):
            return value

        if isinstance(
            value,
            dict,
        ):

            # MCP may unwrap a one-item array
            # into a single dictionary.
            return [
                value
            ]

        return []

    async def _handle_doctor_read(
        self,
        *,
        state,
        nlu: NLUResult,
        language: str,
        channel: ConversationChannel,
    ) -> tuple[str, str]:

        context = resolve_effective_context(
            state=state,
            nlu=nlu,
        )

        specialty_id = context.specialty_id
        specialty_name = context.specialty_name

        doctor_id = context.doctor_id
        doctor_name = context.doctor_name

        if (
            self._explicit_doctor_changed(
                state=state,
                nlu=nlu,
            )
            and
            not nlu.entities.specialty_name
        ):

            specialty_id = None
            specialty_name = None

        # ========================================================
        # OPTIONAL SPECIALTY RESOLUTION
        # ========================================================

        if (
            specialty_name
            and
            not specialty_id
        ):

            specialties_result = await self.tools.call(
                "list_specialties"
            )
            
            specialties_result = (
                self._ensure_list_result(
                    specialties_result
                )
            )

            apply_tool_observation(
                state=state,
                tool_name="list_specialties",
                data=specialties_result,
            )

            specialty = self._find_specialty_for_read(
                specialties=specialties_result,
                specialty_name=specialty_name,
            )

            if specialty is None:

                if language == "en":
                    return (
                        "I couldn't find that specialty.",
                        "doctor_specialty_not_found",
                    )

                return (
                    "مش لاقي التخصص ده حالياً.",
                    "doctor_specialty_not_found",
                )

            specialty_id = str(
                specialty.get("id")
            )

            specialty_name = (
                specialty.get("name_en")
                if language == "en"
                else specialty.get("name_ar")
            ) or (
                specialty.get("name_ar")
                or specialty.get("name_en")
            )

            self._remember_specialty_for_read(
                state=state,
                specialty_id=specialty_id,
                specialty_name=specialty_name,
            )

        # ========================================================
        # EXPLICIT DOCTOR -> TRUSTED DOCTOR DETAILS
        # ========================================================

        if doctor_name:

            doctor = None

            if doctor_id:

                for candidate in state.recent_doctors:

                    if str(
                        candidate.id
                    ) == str(
                        doctor_id
                    ):
                        doctor = candidate
                        break

            if doctor is None:

                arguments = {
                    "limit": 100,
                }

                if specialty_id:
                    arguments[
                        "specialty_id"
                    ] = specialty_id

                doctors_result = await self.tools.call(
                    "list_doctors",
                    **arguments,
                )

                apply_tool_observation(
                    state=state,
                    tool_name="list_doctors",
                    data=doctors_result,
                )

                doctor = self._find_doctor_for_read(
                    state=state,
                    doctor_name=doctor_name,
                )

            if doctor is None:

                if language == "en":
                    return (
                        "I couldn't find that doctor.",
                        "doctor_not_found",
                    )

                return (
                    "مش لاقي الدكتور ده حالياً.",
                    "doctor_not_found",
                )

            (
                doctor_id,
                doctor_name,
            ) = self._remember_doctor_for_read(
                state=state,
                doctor=doctor,
                language=language,
            )

            specialty_label = (
                getattr(
                    doctor,
                    "specialty_name_en",
                    None,
                )
                if language == "en"
                else
                getattr(
                    doctor,
                    "specialty_name_ar",
                    None,
                )
            ) or (
                getattr(
                    doctor,
                    "specialty_name_ar",
                    None,
                )
                or
                getattr(
                    doctor,
                    "specialty_name_en",
                    None,
                )
            )

            fee = getattr(
                doctor,
                "consultation_fee",
                None,
            )

            experience = getattr(
                doctor,
                "experience_years",
                None,
            )

            details = []

            if specialty_label:

                if language == "en":
                    details.append(
                        f"specialty: {specialty_label}"
                    )
                else:
                    details.append(
                        f"التخصص {specialty_label}"
                    )

            if fee:

                if language == "en":
                    details.append(
                        f"consultation fee: {fee}"
                    )
                else:
                    details.append(
                        f"سعر الكشف {fee}"
                    )

            if experience is not None:

                if language == "en":
                    details.append(
                        f"{experience} years of experience"
                    )
                else:
                    details.append(
                        f"خبرة {experience} سنة"
                    )

            if language == "en":

                if details:
                    reply = (
                        f"{doctor_name}: "
                        + ", ".join(
                            details
                        )
                        + "."
                    )
                else:
                    reply = (
                        f"{doctor_name} is available."
                    )

            else:

                if details:
                    reply = (
                        f"{doctor_name}: "
                        + "، ".join(
                            details
                        )
                        + "."
                    )
                else:
                    reply = (
                        f"{doctor_name} متاح."
                    )

            return (
                reply,
                "doctor_details",
            )

        # ========================================================
        # LIST DOCTORS
        # ========================================================

        arguments = {
            "limit": 100,
        }

        if specialty_id:
            arguments[
                "specialty_id"
            ] = specialty_id

        doctors_result = await self.tools.call(
            "list_doctors",
            **arguments,
        )

        apply_tool_observation(
            state=state,
            tool_name="list_doctors",
            data=doctors_result,
        )

        doctors = list(
            state.recent_doctors
        )

        if not doctors:

            if language == "en":

                if specialty_name:
                    return (
                        f"There are no doctors available for {specialty_name}.",
                        "no_doctors",
                    )

                return (
                    "There are no doctors available at the moment.",
                    "no_doctors",
                )

            if specialty_name:
                return (
                    f"مفيش دكاترة متاحين في تخصص {specialty_name} حالياً.",
                    "no_doctors",
                )

            return (
                "مفيش دكاترة متاحين حالياً.",
                "no_doctors",
            )

        display_limit = (
            6
            if channel == "voice"
            else 20
        )

        doctor_names = [
            self._doctor_display_name(
                doctor,
                language,
            )
            for doctor in doctors[
                :display_limit
            ]
        ]

        doctor_names = [
            name
            for name in doctor_names
            if name
        ]

        has_more = (
            len(doctors)
            > display_limit
        )

        if language == "en":

            prefix = (
                f"Doctors available for {specialty_name}: "
                if specialty_name
                else
                "Available doctors: "
            )

            reply = (
                prefix
                + ", ".join(
                    doctor_names
                )
                + "."
            )

            if has_more:
                reply += (
                    " Tell me the specialty and I can narrow the list."
                )

        else:

            prefix = (
                f"الدكاترة المتاحين في تخصص {specialty_name}: "
                if specialty_name
                else
                "الدكاترة المتاحين: "
            )

            reply = (
                prefix
                + "، ".join(
                    doctor_names
                )
                + "."
            )

            if has_more:
                reply += (
                    " لو تقولي التخصص أقدر أحددلك القائمة أكتر."
                )

        return (
            reply,
            "doctor_list",
        )

    async def _handle_service_read(
        self,
        *,
        state,
        nlu: NLUResult,
        language: str,
        channel: ConversationChannel,
        user_message: str = "",
    ) -> tuple[str, str]:

        context = resolve_effective_context(
            state=state,
            nlu=nlu,
        )

        specialty_id = context.specialty_id
        specialty_name = context.specialty_name

        doctor_id = context.doctor_id
        doctor_name = context.doctor_name

        service_name = context.service_name

        message_text = (
            user_message
            or
            ""
        )

        normalized_message = (
            self._normalize_service_lookup_name(
                message_text
            )
        )

        asks_price = any(
            word in normalized_message
            for word in [
                "سعر",
                "اسعار",
                "أسعار",
                "بكام",
                "كام",
                "تكلفة",
                "price",
                "prices",
                "cost",
                "fee",
            ]
        )

        asks_consultation = any(
            word in normalized_message
            for word in [
                "كشف",
                "استشارة",
                "consultation",
                "consult",
                "visit",
            ]
        )

        if (
            self._explicit_doctor_changed(
                state=state,
                nlu=nlu,
            )
            and
            not nlu.entities.specialty_name
        ):

            specialty_id = None
            specialty_name = None

        # ========================================================
        # OPTIONAL SPECIALTY RESOLUTION
        # ========================================================

        if (
            specialty_name
            and
            not specialty_id
        ):

            specialties_result = await self.tools.call(
                "list_specialties"
            )

            specialties_result = (
                self._ensure_list_result(
                    specialties_result
                )
            )

            apply_tool_observation(
                state=state,
                tool_name="list_specialties",
                data=specialties_result,
            )

            specialty = self._find_specialty_for_read(
                specialties=specialties_result,
                specialty_name=specialty_name,
            )

            if specialty is None:

                if language == "en":
                    return (
                        "I couldn't find that specialty.",
                        "service_specialty_not_found",
                    )

                return (
                    "مش لاقي التخصص ده حالياً.",
                    "service_specialty_not_found",
                )

            specialty_id = str(
                specialty.get("id")
            )

            specialty_name = (
                specialty.get("name_en")
                if language == "en"
                else specialty.get("name_ar")
            ) or (
                specialty.get("name_ar")
                or specialty.get("name_en")
            )

            self._remember_specialty_for_read(
                state=state,
                specialty_id=specialty_id,
                specialty_name=specialty_name,
            )

        # ========================================================
        # DOCTOR RESOLUTION
        # ========================================================

        if (
            not doctor_id
            and
            doctor_name
        ):

            arguments = {
                "limit": 100,
            }

            if specialty_id:
                arguments[
                    "specialty_id"
                ] = specialty_id

            doctors_result = await self.tools.call(
                "list_doctors",
                **arguments,
            )

            apply_tool_observation(
                state=state,
                tool_name="list_doctors",
                data=doctors_result,
            )

            doctor = self._find_doctor_for_read(
                state=state,
                doctor_name=doctor_name,
            )

            if doctor is None:

                if language == "en":
                    return (
                        "I couldn't find that doctor.",
                        "service_doctor_not_found",
                    )

                return (
                    "مش لاقي الدكتور ده حالياً.",
                    "service_doctor_not_found",
                )

            (
                doctor_id,
                doctor_name,
            ) = self._remember_doctor_for_read(
                state=state,
                doctor=doctor,
                language=language,
            )

        if (
            not doctor_id
            and
            not specialty_id
            and
            not service_name
            and
            not asks_price
        ):

            if language == "en":
                return (
                    "Which doctor's services would you like to know?",
                    "ask_service_doctor",
                )

            return (
                "تحبي تعرفي خدمات أنهي دكتور؟",
                "ask_service_doctor",
            )

        # ========================================================
        # TRUSTED SERVICES FOR DOCTOR
        # ========================================================

        service_arguments = {}

        if doctor_id:
            service_arguments[
                "doctor_id"
            ] = doctor_id

        elif specialty_id:
            service_arguments[
                "specialty_id"
            ] = specialty_id

        services_result = await self.tools.call(
            "list_services",
            **service_arguments,
        )

        apply_tool_observation(
            state=state,
            tool_name="list_services",
            data=services_result,
        )

        services = list(
            state.recent_services
        )

        if not services:

            if language == "en":
                return (
                    f"There are no services registered for "
                    f"{doctor_name or 'that doctor'}.",
                    "no_services",
                )

            return (
                f"مفيش خدمات مسجلة لـ"
                f"{doctor_name or 'الدكتور ده'} حالياً.",
                "no_services",
            )

        if (
            asks_price
            and
            not service_name
        ):

            priced_services = [
                service
                for service in services
                if getattr(
                    service,
                    "price",
                    None,
                )
            ]

            if not priced_services:

                if language == "en":
                    return (
                        "I found the services, but I don't have registered prices for them right now.",
                        "service_prices_missing",
                    )

                return (
                    "الخدمات موجودة، بس الأسعار مش مسجلة عندي حالياً.",
                    "service_prices_missing",
                )

            mentioned_service = None

            message_tokens = {
                token
                for token in normalized_message.split()
                if token not in {
                    "سعر",
                    "اسعار",
                    "أسعار",
                    "بكام",
                    "كام",
                    "تكلفة",
                    "price",
                    "prices",
                    "cost",
                    "fee",
                    "هو",
                    "هي",
                    "ايه",
                    "كم",
                }
            }

            scored_services = []

            for service in priced_services:

                candidates = [
                    getattr(service, "code", None),
                    getattr(service, "name_ar", None),
                    getattr(service, "name_en", None),
                    getattr(service, "voice_label_ar", None),
                    getattr(service, "voice_label_en", None),
                ]

                best_score = 0

                for candidate in candidates:

                    candidate_normalized = (
                        self._normalize_service_lookup_name(
                            candidate
                        )
                    )

                    if not candidate_normalized:
                        continue

                    if candidate_normalized in normalized_message:
                        best_score = max(best_score, 100)

                    candidate_tokens = set(
                        candidate_normalized.split()
                    )

                    overlap_score = 0

                    for message_token in message_tokens:
                        for candidate_token in candidate_tokens:
                            if (
                                message_token == candidate_token
                                or message_token in candidate_token
                                or candidate_token in message_token
                            ):
                                overlap_score += 1

                    best_score = max(
                        best_score,
                        overlap_score,
                    )

                if best_score > 0:
                    scored_services.append(
                        (
                            best_score,
                            service,
                        )
                    )

            scored_services.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            if (
                scored_services
                and
                (
                    len(scored_services) == 1
                    or scored_services[0][0] > scored_services[1][0]
                )
            ):
                mentioned_service = scored_services[0][1]

            if mentioned_service is not None:

                name = (
                    getattr(
                        mentioned_service,
                        "voice_label_ar" if language != "en" else "voice_label_en",
                        None,
                    )
                    or
                    self._service_display_name(
                        mentioned_service,
                        language,
                    )
                    or
                    getattr(
                        mentioned_service,
                        "code",
                        None,
                    )
                    or
                    "service"
                )

                price = str(
                    getattr(
                        mentioned_service,
                        "price",
                        "",
                    )
                ).strip()

                if price.endswith(".00"):
                    price = price[:-3]

                if language == "en":
                    return (
                        f"{name} price is {price}.",
                        "service_price",
                    )

                return (
                    f"{name} سعرها {price} جنيه.",
                    "service_price",
                )    

            if asks_consultation:

                consultation_matches = []

                for service in priced_services:

                    candidates = [
                        getattr(service, "code", None),
                        getattr(service, "name_ar", None),
                        getattr(service, "name_en", None),
                    ]

                    normalized_candidates = [
                        self._normalize_service_lookup_name(
                            candidate
                        )
                        for candidate in candidates
                        if candidate
                    ]

                    if any(
                        (
                            "كشف" in candidate
                            or
                            "استشارة" in candidate
                            or
                            "consult" in candidate
                            or
                            "consultation" in candidate
                        )
                        for candidate in normalized_candidates
                    ):
                        consultation_matches.append(
                            service
                        )

                if consultation_matches:
                    priced_services = consultation_matches

            display_services = (
                priced_services[:5]
                if channel == "voice"
                else priced_services[:10]
            )

            rendered = []

            for service in display_services:

                name = (
                    self._service_display_name(
                        service,
                        language,
                    )
                    or
                    getattr(
                        service,
                        "code",
                        None,
                    )
                    or
                    "service"
                )

                price = str(
                    getattr(
                        service,
                        "price",
                        "",
                    )
                ).strip()

                if price.endswith(".00"):
                    price = price[:-3]

                if language == "en":
                    rendered.append(
                        f"{name}: {price}"
                    )
                else:
                    rendered.append(
                        f"{name}: {price} جنيه"
                    )

            has_more_prices = (
                len(priced_services)
                >
                len(display_services)
            )

            if language == "en":

                reply = (
                    "Service prices are: "
                    + ", ".join(rendered)
                )

                if has_more_prices:
                    reply += ", and other services."

                return (
                    reply + ".",
                    "service_prices",
                )

            reply = (
                "أسعار الخدمات: "
                + "، ".join(rendered)
            )

            if has_more_prices:
                reply += "، وفي خدمات تانية."

            return (
                reply + ".",
                "service_prices",
            )

        # ========================================================
        # EXPLICIT SERVICE DETAILS
        # ========================================================

        if service_name:

            service = self._find_service_for_read(
                state=state,
                service_name=service_name,
            )

            if service is None:

                available_names = [
                    self._service_display_name(
                        item,
                        language,
                    )
                    for item in services
                ]

                available_names = [
                    name
                    for name in available_names
                    if name
                ]

                if language == "en":
                    return (
                        "I couldn't match that service. "
                        "Available services are: "
                        + ", ".join(
                            available_names
                        )
                        + ".",
                        "service_not_found",
                    )

                return (
                    "مش لاقي الخدمة دي. "
                    "الخدمات المتاحة: "
                    + "، ".join(
                        available_names
                    )
                    + ".",
                    "service_not_found",
                )

            (
                _service_id,
                canonical_service_name,
            ) = self._remember_service_for_read(
                state=state,
                service=service,
                language=language,
            )

            price = getattr(
                service,
                "price",
                None,
            )

            service_type = getattr(
                service,
                "service_type",
                None,
            )

            price_text = (
                str(price).strip()
                if price is not None
                else ""
            )

            if price_text.endswith(".00"):
                price_text = price_text[:-3]

            service_type_text = (
                str(service_type).strip()
                if service_type is not None
                else ""
            )

            service_type_labels_ar = {
                "consultation": "كشف أو استشارة",
                "procedure": "إجراء طبي",
                "test": "تحليل أو فحص",
                "package": "باقة",
            }

            service_type_label_ar = (
                service_type_labels_ar.get(
                    service_type_text.casefold(),
                    service_type_text,
                )
            )

            if (
                channel == "voice"
                and self.response_verbalizer is not None
            ):

                voice_service_name = (
                    getattr(
                        service,
                        "voice_label_ar"
                        if language != "en"
                        else "voice_label_en",
                        None,
                    )
                    or canonical_service_name
                )

                voice_service_type = (
                    service_type_label_ar
                    if language != "en"
                    else service_type_text
                )

                verbalized_reply = await (
                    self.response_verbalizer
                    .verbalize_service_details(
                        service_name=voice_service_name,
                        price_text=price_text,
                        service_type=voice_service_type,
                        language=language,
                    )
                )

                if verbalized_reply:
                    return (
                        verbalized_reply,
                        "service_details",
                    )

            if language == "en":

                parts = []

                if price_text:
                    parts.append(
                        f"price: {price_text}"
                    )

                if service_type_text:
                    parts.append(
                        f"type: {service_type_text}"
                    )

                if parts:
                    reply = (
                        f"{canonical_service_name}: "
                        + ", ".join(
                            parts
                        )
                        + "."
                    )
                else:
                    reply = (
                        f"{canonical_service_name} is available "
                        f"with {doctor_name or 'the selected doctor'}."
                    )

            else:

                parts = []

                if price_text:
                    parts.append(
                        f"السعر {price_text} جنيه"
                    )

                if service_type_label_ar:
                    parts.append(
                        f"النوع {service_type_label_ar}"
                    )

                if parts:
                    reply = (
                        f"{canonical_service_name}: "
                        + "، ".join(
                            parts
                        )
                        + "."
                    )
                else:
                    reply = (
                        f"{canonical_service_name} متاحة مع "
                        f"{doctor_name or 'الدكتور المختار'}."
                    )

            return (
                reply,
                "service_details",
            )

        # ========================================================
        # LIST SERVICES
        # ========================================================

        if channel == "voice":

            featured_services = [
                service
                for service in services
                if getattr(
                    service,
                    "voice_featured_rank",
                    None,
                ) is not None
            ]

            featured_services.sort(
                key=lambda service: getattr(
                    service,
                    "voice_featured_rank",
                    0,
                )
            )

            if featured_services:
                voice_services = (
                    featured_services[:5]
                )
            else:
                voice_services = (
                    services[:5]
                )

            # ====================================================
            # DETERMINISTIC FALLBACK LABELS
            # ====================================================

            rendered_services = []

            for service in voice_services:

                if language == "en":

                    name = (
                        getattr(
                            service,
                            "voice_label_en",
                            None,
                        )
                        or
                        self._service_display_name(
                            service,
                            language,
                        )
                    )

                else:

                    name = (
                        getattr(
                            service,
                            "voice_label_ar",
                            None,
                        )
                        or
                        self._service_display_name(
                            service,
                            language,
                        )
                    )

                if name:
                    rendered_services.append(
                        name
                    )

            has_more = (
                len(services)
                >
                len(voice_services)
            )

            # ====================================================
            # SAFE DETERMINISTIC FALLBACK
            # ====================================================

            if language == "en":

                fallback_reply = (
                    "We offer "
                    + ", ".join(
                        rendered_services
                    )
                )

                if has_more:
                    fallback_reply += (
                        ", and other services."
                    )
                else:
                    fallback_reply += "."

            else:

                fallback_reply = (
                    "عندنا "
                    + "، ".join(
                        rendered_services
                    )
                )

                if has_more:
                    fallback_reply += (
                        "، وخدمات تانية."
                    )
                else:
                    fallback_reply += "."

            reply = fallback_reply

            # ====================================================
            # NATURAL VOICE VERBALIZATION
            #
            # Give the LLM the canonical trusted service names,
            # not shortened presentation labels.
            # ====================================================

            if (
                self.response_verbalizer
                is not None
            ):

                trusted_service_names = [
                    self._service_display_name(
                        service,
                        language,
                    )
                    for service in voice_services
                ]

                trusted_service_names = [
                    name
                    for name in trusted_service_names
                    if name
                ]

                verbalized_reply = await (
                    self.response_verbalizer
                    .verbalize_services(
                        service_names=(
                            trusted_service_names
                        ),
                        language=language,
                        has_more=has_more,
                    )
                )

                if verbalized_reply:
                    reply = (
                        verbalized_reply
                    )

        # ========================================================
        # NON-VOICE SERVICE LIST
        # ========================================================

        else:

            rendered_services = []

            for service in services[:20]:

                name = self._service_display_name(
                    service,
                    language,
                )

                if not name:
                    continue

                price = getattr(
                    service,
                    "price",
                    None,
                )

                if price:
                    rendered_services.append(
                        f"{name} ({price})"
                    )
                else:
                    rendered_services.append(
                        name
                    )

            if language == "en":

                reply = (
                    f"Services available with "
                    f"{doctor_name or 'the selected doctor'}: "
                    + ", ".join(
                        rendered_services
                    )
                    + "."
                )

            else:

                reply = (
                    f"الخدمات المتاحة مع "
                    f"{doctor_name or 'الدكتور المختار'}: "
                    + "، ".join(
                        rendered_services
                    )
                    + "."
                )

        return (
            reply,
            "service_list",
        )


    async def _handle_working_hours_read(
        self,
        *,
        state,
        nlu: NLUResult,
        language: str,
    ) -> tuple[str, str]:

        context = (
            resolve_effective_context(
                state=state,
                nlu=nlu,
            )
        )

        doctor_id = (
            context.doctor_id
        )

        doctor_name = (
            context.doctor_name
        )

        specialty_id = (
            context.specialty_id
        )

        specialty_name = (
            context.specialty_name
        )

        if (
            self._explicit_doctor_changed(
                state=state,
                nlu=nlu,
            )
            and
            not nlu.entities.specialty_name
        ):

            specialty_id = None
            specialty_name = None

        if (
            not doctor_id
            and
            not doctor_name
            and
            specialty_name
        ):

            # ====================================================
            # RESOLVE SPECIALTY NAME → TRUSTED ID
            # ====================================================

            if not specialty_id:

                specialties_result = await (
                    self.tools.call(
                        "list_specialties"
                    )
                )

                specialties_result = (
                    self._ensure_list_result(
                        specialties_result
                    )
                )

                apply_tool_observation(
                    state=state,
                    tool_name=
                        "list_specialties",
                    data=
                        specialties_result,
                )

                specialty = (
                    self._find_specialty_for_read(
                        specialties=
                            specialties_result,

                        specialty_name=
                            specialty_name,
                    )
                )

                # =================================================
                # SPECIALTY NOT FOUND
                # =================================================

                if specialty is None:

                    names = []

                    for item in (
                        specialties_result
                    ):

                        if not isinstance(
                            item,
                            dict,
                        ):
                            continue

                        if language == "en":

                            name = (
                                item.get(
                                    "name_en"
                                )
                                or
                                item.get(
                                    "name_ar"
                                )
                            )

                        else:

                            name = (
                                item.get(
                                    "name_ar"
                                )
                                or
                                item.get(
                                    "name_en"
                                )
                            )

                        if name:

                            names.append(
                                name
                            )

                    if language == "en":

                        return (
                            "I couldn't find that specialty. "
                            "Available specialties are: "
                            + ", ".join(
                                names
                            )
                            + ".",
                            "working_hours_specialty_not_found",
                        )

                    return (
                        "مش لاقي التخصص ده. "
                        "التخصصات المتاحة: "
                        + "، ".join(
                            names
                        )
                        + ".",
                        "working_hours_specialty_not_found",
                    )

                specialty_id = (
                    specialty.get(
                        "id"
                    )
                )

                if language == "en":

                    specialty_name = (
                        specialty.get(
                            "name_en"
                        )
                        or
                        specialty.get(
                            "name_ar"
                        )
                    )

                else:

                    specialty_name = (
                        specialty.get(
                            "name_ar"
                        )
                        or
                        specialty.get(
                            "name_en"
                        )
                    )

            # ====================================================
            # TRUSTED SPECIALTY
            #
            # Changing specialty invalidates old doctor/service.
            # ====================================================

            specialty_changed = (
                state.specialty_id
                is not None
                and
                str(
                    state.specialty_id
                )
                !=
                str(
                    specialty_id
                )
            )

            if specialty_changed:

                state.doctor_id = None
                state.doctor_name = None

                state.service_id = None
                state.service_name = None

                state.recent_doctors = []
                state.recent_services = []

            state.specialty_id = (
                specialty_id
            )

            state.specialty_name = (
                specialty_name
            )

            # ====================================================
            # LOAD DOCTORS FOR THIS SPECIALTY
            # ====================================================

            doctors_result = await (
                self.tools.call(
                    "list_doctors",

                    specialty_id=
                        specialty_id,
                )
            )

            apply_tool_observation(
                state=state,
                tool_name=
                    "list_doctors",
                data=
                    doctors_result,
            )

            doctors = (
                state.recent_doctors
            )

            # ====================================================
            # NO DOCTORS
            # ====================================================

            if not doctors:

                if language == "en":

                    return (
                        f"There are no doctors available "
                        f"for {specialty_name} at the moment.",
                        "no_working_hours_doctors",
                    )

                return (
                    f"مفيش دكاترة متاحين في "
                    f"تخصص {specialty_name} حالياً.",
                    "no_working_hours_doctors",
                )

            # ====================================================
            # EXACTLY ONE DOCTOR
            #
            # No clarification needed.
            # ====================================================

            if len(doctors) == 1:

                doctor = (
                    doctors[0]
                )

                doctor_id = (
                    doctor.id
                )

                if language == "en":

                    doctor_name = (
                        doctor.full_name_en
                        or
                        doctor.full_name_ar
                    )

                else:

                    doctor_name = (
                        doctor.full_name_ar
                        or
                        doctor.full_name_en
                    )

                state.doctor_id = (
                    doctor_id
                )

                state.doctor_name = (
                    doctor_name
                )

            # ====================================================
            # MULTIPLE DOCTORS
            #
            # Ask ONLY for the missing doctor.
            # ====================================================

            else:

                doctor_names = []

                for doctor in doctors:

                    if language == "en":

                        name = (
                            doctor.full_name_en
                            or
                            doctor.full_name_ar
                        )

                    else:

                        name = (
                            doctor.full_name_ar
                            or
                            doctor.full_name_en
                        )

                    if name:

                        doctor_names.append(
                            name
                        )

                if language == "en":

                    return (
                        f"There is more than one doctor "
                        f"in {specialty_name}: "
                        + ", ".join(
                            doctor_names
                        )
                        + ". Which doctor do you mean?",
                        "ask_working_hours_doctor",
                    )

                return (
                    f"في أكتر من دكتور في تخصص "
                    f"{specialty_name}: "
                    + "، ".join(
                        doctor_names
                    )
                    + ". تقصدي أنهي دكتور؟",
                    "ask_working_hours_doctor",
                )


        # ========================================================
        # DOCTOR STILL UNKNOWN
        #
        # No doctor and no usable specialty.
        # ========================================================

        if (
            not doctor_id
            and
            not doctor_name
        ):

            if language == "en":

                return (
                    "Which doctor's working hours "
                    "would you like to know?",
                    "ask_working_hours_doctor",
                )

            return (
                "مواعيد أنهي دكتور "
                "تحبي تعرفيها؟",
                "ask_working_hours_doctor",
            )
        
        if (
            not doctor_id
            and
            doctor_name
        ):

            doctor_arguments = {
                "limit":
                    100,
            }

            if specialty_id:

                doctor_arguments[
                    "specialty_id"
                ] = (
                    specialty_id
                )

            doctors_result = await (
                self.tools.call(
                    "list_doctors",
                    **doctor_arguments,
                )
            )

            apply_tool_observation(
                state=state,
                tool_name=
                    "list_doctors",
                data=
                    doctors_result,
            )

            doctor = (
                self._find_doctor_for_read(
                    state=state,
                    doctor_name=
                        doctor_name,
                )
            )

            # ====================================================
            # DOCTOR NOT FOUND / AMBIGUOUS
            # ====================================================

            if doctor is None:

                doctor_names = []

                for item in (
                    state.recent_doctors
                ):

                    if language == "en":

                        name = (
                            item.full_name_en
                            or
                            item.full_name_ar
                        )

                    else:

                        name = (
                            item.full_name_ar
                            or
                            item.full_name_en
                        )

                    if name:

                        doctor_names.append(
                            name
                        )

                if language == "en":

                    if doctor_names:

                        return (
                            "I couldn't match that doctor. "
                            "Available doctors are: "
                            + ", ".join(
                                doctor_names
                            )
                            + ".",
                            "working_hours_doctor_not_found",
                        )

                    return (
                        "I couldn't find that doctor.",
                        "working_hours_doctor_not_found",
                    )

                if doctor_names:

                    return (
                        "مش لاقي الدكتور ده. "
                        "الدكاترة المتاحين: "
                        + "، ".join(
                            doctor_names
                        )
                        + ".",
                        "working_hours_doctor_not_found",
                    )

                return (
                    "مش لاقي الدكتور ده حالياً.",
                    "working_hours_doctor_not_found",
                )
            
            doctor_id = (
                doctor.id
            )

            if language == "en":

                doctor_name = (
                    doctor.full_name_en
                    or
                    doctor.full_name_ar
                )

            else:

                doctor_name = (
                    doctor.full_name_ar
                    or
                    doctor.full_name_en
                )

            state.doctor_id = (
                doctor_id
            )

            state.doctor_name = (
                doctor_name
            )

        # ========================================================
        # SAFETY
        # ========================================================

        if not doctor_id:

            if language == "en":

                return (
                    "Which doctor's working hours "
                    "would you like to know?",
                    "ask_working_hours_doctor",
                )

            return (
                "مواعيد أنهي دكتور "
                "تحبي تعرفيها؟",
                "ask_working_hours_doctor",
            )

        working_hours_result = await (
            self.tools.call(
                "get_working_hours",

                doctor_id=
                    doctor_id,
            )
        )

        working_hours_result = (
            self._ensure_list_result(
                working_hours_result
            )
        )

        date_text = (
            context.date_text
        )

        requested_weekday = None
        requested_date = None

        if date_text:

            requested_date = (
                resolve_date(
                    date_text
                )
            )

            if requested_date is not None:

                requested_weekday = (
                    requested_date.weekday()
                )

        # ========================================================
        # NORMALIZE / DEDUPLICATE
        # ========================================================

        schedules = []

        seen = set()

        for item in (
            working_hours_result
        ):

            if not isinstance(
                item,
                dict,
            ):

                continue

            day_of_week = (
                item.get(
                    "day_of_week"
                )
            )

            start_time = (
                item.get(
                    "start_time"
                )
            )

            end_time = (
                item.get(
                    "end_time"
                )
            )

            if (
                day_of_week is None
                or
                not start_time
                or
                not end_time
            ):

                continue

            try:

                day_of_week = int(
                    day_of_week
                )

            except (
                TypeError,
                ValueError,
            ):

                continue

            if (
                requested_weekday
                is not None
                and
                day_of_week
                != requested_weekday
            ):

                continue

            start_time = (
                str(
                    start_time
                )[:5]
            )

            end_time = (
                str(
                    end_time
                )[:5]
            )

            key = (
                day_of_week,
                start_time,
                end_time,
            )

            if key in seen:

                continue

            seen.add(
                key
            )

            schedules.append(
                key
            )

        # ========================================================
        # NO WORKING HOURS
        # ========================================================

        if not schedules:

            if language == "en":

                if requested_date is not None:

                    return (
                        f"{doctor_name} has no registered "
                        f"working hours on "
                        f"{requested_date.isoformat()}.",
                        "no_working_hours",
                    )

                return (
                    f"{doctor_name} has no registered "
                    f"working hours at the moment.",
                    "no_working_hours",
                )

            if requested_date is not None:

                return (
                    f"مفيش مواعيد شغل مسجلة لـ"
                    f"{doctor_name} يوم "
                    f"{requested_date.isoformat()}.",
                    "no_working_hours",
                )

            return (
                f"مفيش مواعيد شغل مسجلة لـ"
                f"{doctor_name} حالياً.",
                "no_working_hours",
            )

        # ========================================================
        # DAY NAMES
        # ========================================================

        days_ar = {
            0: "الاثنين",
            1: "الثلاثاء",
            2: "الأربعاء",
            3: "الخميس",
            4: "الجمعة",
            5: "السبت",
            6: "الأحد",
        }

        days_en = {
            0: "Monday",
            1: "Tuesday",
            2: "Wednesday",
            3: "Thursday",
            4: "Friday",
            5: "Saturday",
            6: "Sunday",
        }

        day_order = {
            6: 0,
            0: 1,
            1: 2,
            2: 3,
            3: 4,
            4: 5,
            5: 6,
        }

        schedules.sort(
            key=lambda item: (
                day_order.get(
                    item[0],
                    99,
                ),
                item[1],
                item[2],
            )
        )

        # ========================================================
        # BUILD RESPONSE
        # ========================================================

        parts = []

        for (
            day_of_week,
            start_time,
            end_time,
        ) in schedules:

            if language == "en":

                day_name = (
                    days_en.get(
                        day_of_week,
                        str(
                            day_of_week
                        ),
                    )
                )

                parts.append(
                    f"{day_name} from "
                    f"{start_time} to "
                    f"{end_time}"
                )

            else:

                day_name = (
                    days_ar.get(
                        day_of_week,
                        str(
                            day_of_week
                        ),
                    )
                )

                parts.append(
                    f"{day_name} من "
                    f"{start_time} لحد "
                    f"{end_time}"
                )

        if language == "en":

            if requested_date is not None:

                reply = (
                    f"{doctor_name}'s working hours "
                    f"on {requested_date.isoformat()} are: "
                    + ", ".join(
                        parts
                    )
                    + "."
                )

            else:

                reply = (
                    f"{doctor_name}'s working hours are: "
                    + ", ".join(
                        parts
                    )
                    + "."
                )

        else:

            if requested_date is not None:

                reply = (
                    f"مواعيد {doctor_name} يوم "
                    f"{requested_date.isoformat()} هي: "
                    + "، ".join(
                        parts
                    )
                    + "."
                )

            else:

                reply = (
                    f"مواعيد {doctor_name} هي: "
                    + "، ".join(
                        parts
                    )
                    + "."
                )

        return (
            reply,
            "working_hours",
        )
    # ========================================================
    # UNDERSTANDING CONTEXT
    # ========================================================

    @staticmethod

    def _active_capability_from_state(
        state,
    ) -> str | None:

        # ========================================================
        # 1. ACTIVE WRITE WORKFLOW
        #
        # An in-progress booking/cancel/reschedule always has
        # priority over old conversational read context.
        # ========================================================

        active_stage = (
            state.awaiting_confirmation
            or
            state.stage == "new"
            or
            state.stage.startswith(
                "awaiting_"
            )
        )

        operation_capabilities = {
            "book_appointment":
                "appointment.create",

            "cancel_appointment":
                "appointment.cancel",

            "reschedule_appointment":
                "appointment.reschedule",
        }

        if active_stage:

            operation_capability = (
                operation_capabilities
                .get(
                    state.operation_type
                )
            )

            if operation_capability:

                return (
                    operation_capability
                )

        return (
            state
            .conversation_focus_capability
        )

    @classmethod
    def _build_understanding_context(
        cls,
        state,
    ) -> dict:

        context = dict(
            state.safe_llm_context()
        )

        active_capability = (
            cls._active_capability_from_state(
                state
            )
        )

        active_operation_context = (
            state.operation_type
            in {
                "book_appointment",
                "cancel_appointment",
                "reschedule_appointment",
            }
            and
            (
                state.awaiting_confirmation
                or
                state.stage == "new"
                or
                state.stage.startswith(
                    "awaiting_"
                )
            )
        )

        pending = (
            state.pending_operation_entities
            if active_operation_context
            else {}
        )

        specialty_name = (
            pending.get(
                "specialty_name"
            )
            or
            state.specialty_name
            or
            state.conversation_specialty_name
        )

        doctor_name = (
            pending.get(
                "doctor_name"
            )
            or
            state.doctor_name
            or
            state.conversation_doctor_name
        )

        service_name = (
            pending.get(
                "service_name"
            )
            or
            state.service_name
            or
            state.conversation_service_name
        )

        # ----------------------------------------------------
        # Schedule context
        #
        # For reschedule, never expose the CURRENT appointment
        # date/time as if they were the requested NEW values.
        # ----------------------------------------------------

        if (
            state.operation_type
            == "reschedule_appointment"
        ):

            date_text = (
                state.new_slot_date
                or
                pending.get(
                    "date_text"
                )
            )

            time_text = (
                state.new_slot_time
                or
                pending.get(
                    "time_text"
                )
            )

        else:

            date_text = (
                pending.get(
                    "date_text"
                )
                or
                state.slot_date
            )

            time_text = (
                pending.get(
                    "time_text"
                )
                or
                state.slot_time
            )

            if (
                not date_text
                and
                state.conversation_focus_capability
                in {
                    "provider.get_slots",
                    "provider.get_working_hours",
                }
            ):

                date_text = (
                    state.conversation_date_text
                )

        collected_arguments = {
            "specialty_name":
                specialty_name,

            "doctor_name":
                doctor_name,

            "service_name":
                service_name,

            "date_text":
                date_text,

            "time_text":
                time_text,

            "appointment_reference":
                state.appointment_reference,
        }

        collected_arguments = {
            key: value
            for key, value
            in collected_arguments.items()
            if value is not None
        }

        offered_doctors = []

        for doctor in (
            state.recent_doctors
        ):

            name = (
                doctor.full_name_ar
                or
                doctor.full_name_en
            )

            if name:
                offered_doctors.append(
                    name
                )

        offered_services = []

        for service in (
            state.recent_services
        ):

            name = (
                service.name_ar
                or
                service.name_en
            )

            if name:
                offered_services.append(
                    name
                )

        offered_specialties = []

        for specialty in (
            state.recent_specialties
        ):

            name = (
                specialty.name_ar
                or
                specialty.name_en
            )

            if name:
                offered_specialties.append(
                    name
                )

        offered_slots = []

        for slot in (
            state.recent_slots
        ):

            if slot.start_time:
                offered_slots.append(
                    slot.start_time[:5]
                )

        context.update(
            {
                "active_capability":
                    active_capability,

                "pending_confirmation":
                    state.awaiting_confirmation,

                "collected_arguments":
                    collected_arguments,

                "offered_doctors":
                    offered_doctors,

                "offered_services":
                    offered_services,

                "offered_specialties":
                    offered_specialties,

                "offered_slots":
                    offered_slots,
            }
        )

        return context

    # ========================================================
    # SIDE-QUESTION ROUTING
    # ========================================================

    @staticmethod
    def _has_active_write_workflow(
        state,
    ) -> bool:

        if (
            state.operation_type
            not in ACTIVE_WRITE_OPERATIONS
        ):

            return False

        return (
            state.awaiting_confirmation
            or
            state.stage == "new"
            or
            state.stage.startswith(
                "awaiting_"
            )
        )


    @classmethod
    def _is_side_question(
        cls,
        *,
        state,
        nlu: NLUResult,
        selected_capability: str | None,
    ) -> bool:

        if not cls._has_active_write_workflow(
            state
        ):

            return False

        if (
            nlu.operation_type
            in ACTIVE_WRITE_OPERATIONS
        ):

            return False

        if nlu.intent in {
            "book_appointment",
            "cancel_appointment",
            "reschedule_appointment",
        }:

            return False

        # --------------------------------------------------------
        # Current request is informational.
        # --------------------------------------------------------

        if (
            selected_capability
            in INFORMATIONAL_CAPABILITIES
        ):

            return True

        if (
            nlu.intent
            in INFORMATIONAL_INTENTS
        ):

            return True

        return False


    @staticmethod
    def _create_side_read_state(
        state,
    ):

        return state.model_copy(
            deep=True
        )


    @staticmethod
    def _merge_side_read_context(
        *,
        target,
        source,
    ) -> None:

        for field_name in (
            SIDE_READ_CONTEXT_FIELDS
        ):

            setattr(
                target,
                field_name,
                getattr(
                    source,
                    field_name,
                ),
            )

    # ========================================================
    # WORKFLOW ROUTER
    # ========================================================

    def _select_workflow(
        self,
        *,
        state,
        nlu: NLUResult,
    ):

        """
        Deterministic routing.

        Priority:

        1. Explicit NEW write operation
        -> switch workflow.

        2. Informational / side question
        -> answer it without cancelling the
            active write workflow.

        3. Contextual value for active operation
        -> continue active workflow.

        4. Otherwise
        -> read path / read agent.
        """

        # ========================================================
        # CURRENT MESSAGE OPERATION
        # ========================================================

        requested_operation = (
            nlu.operation_type
        )

        if requested_operation is None:

            intent_to_operation = {
                "book_appointment":
                    "book_appointment",

                "cancel_appointment":
                    "cancel_appointment",

                "reschedule_appointment":
                    "reschedule_appointment",
            }

            requested_operation = (
                intent_to_operation.get(
                    nlu.intent
                )
            )

        if (
            requested_operation
            == "book_appointment"
        ):

            return (
                self.booking_workflow
            )

        if (
            requested_operation
            == "cancel_appointment"
        ):

            return (
                self.cancel_workflow
            )

        if (
            requested_operation
            == "reschedule_appointment"
        ):

            return (
                self.reschedule_workflow
            )

        informational_intents = {
            "ask_available_slots",
            "ask_working_hours",
            "ask_doctor",
            "ask_service",
            "ask_provider",
            "search_appointments",
            "lookup_appointment",
            "greeting",
            "help",
        }

        informational_operations = {
            "search_appointments",
            "lookup_appointment",
        }

        if (
            nlu.intent
            in informational_intents
            or
            requested_operation
            in informational_operations
        ):
            return None

        active_stage = (
            state.awaiting_confirmation

            or

            state.stage == "new"

            or

            state.stage.startswith(
                "awaiting_"
            )
        )

        if not active_stage:

            return None

        if (
            state.operation_type
            == "book_appointment"
        ):

            return (
                self.booking_workflow
            )

        if (
            state.operation_type
            == "cancel_appointment"
        ):

            return (
                self.cancel_workflow
            )

        if (
            state.operation_type
            == "reschedule_appointment"
        ):

            return (
                self.reschedule_workflow
            )

        # ========================================================
        # 4. NO ACTIVE WORKFLOW
        # ========================================================

        return None


    @staticmethod
    def _looks_like_medical_education_question(
        *,
        message: str,
        history: list[Any] | None = None,
    ) -> bool:

        text = (
            str(message or "")
            .lower()
            .strip()
        )

        if not text:
            return False

        exclude_terms = (
            "احجز موعد",
            "احجزي موعد",
            "عايز احجز",
            "عايزة احجز",
            "ممكن احجز",
            "احجزلي",
            "احجزيلي",
            "حجزلي",
            "الغاء",
            "إلغاء",
            "غير ميعاد",
            "غيرلي",
            "reschedule",
            "cancel",
            "book an appointment",
            "schedule an appointment",
            "cancel appointment",
            "reschedule appointment",
            "analyze",
            "حلل",
            "اشعة",
            "أشعة",
            "تحليل الصورة",
            "upload",
        )

        if any(
            term in text
            for term in exclude_terms
        ):
            return False

        question_terms = (
            "يعني",
            "ايه دخل",
            "إيه دخل",
            "مش فاهمة",
            "مش فاهمه",
            "مش فاهم",
            "وظيفة",
            "فايدة",
            "دور",
            "يعني ايه",
            "يعني إيه",
            "ما معنى",
            "ايه معنى",
            "اشرح",
            "شرح",
            "what is",
            "what are",
            "what do",
            "what does",
            "why does",
            "explain",
            "meaning of",
            "does this mean",
            "what does that mean",
            "is it",
            "could",
            "معناه ايه",
            "معناها ايه",
            "فايدته",
            "فايدتها",
            "وظيفته",
            "وظيفتها",
            "بتعمل ايه",
            "بيعمل ايه",
            "هل ده خطر",
            "هل دا خطر",
            "خطير",
            "خطيرة",
            "أقلق",
            "مقلق",
            "what does it do",
            "what is its function",
            "is that dangerous",
            "latest",
            "newest",
            "recent research",
            "guideline",
            "guidelines",
            "recommendation",
            "recommendations",
            "أحدث",
            "احدث",
            "آخر توصية",
            "اخر توصية",
            "توصيات",
            "إرشادات",
            "ارشادات",
        )

        medical_terms = (
            "cbc",
            "صورة الدم",
            "هيموجلوبين",
            "hemoglobin",
            "vitamin d",
            "فيتامين د",
            "25-oh",
            "25(oh)d",
            "ferritin",
            "الفيريتين",
            "iron",
            "الحديد",
            "tibc",
            "transferrin",
            "vitamin b12",
            "فيتامين ب12",
            "cobalamin",
            "folate",
            "folic acid",
            "حمض الفوليك",
            "الفولات",
            "reticulocyte",
            "الخلايا الشبكية",
            "hb",
            "anemia",
            "انيميا",
            "فقر الدم",
            "hba1c",
            "a1c",
            "سكر تراكمي",
            "السكر التراكمي",
            "diabetes",
            "سكري",
            "السكري",
            "ضغط",
            "blood pressure",
            "hypertension",
            "pneumonia",
            "التهاب رئوي",
            "wbc",
            "white blood cell",
            "كرات الدم البيضاء",
            "rbc",
            "red blood cell",
            "كرات الدم الحمراء",
            "العدلات",
            "neutrophil",
            "lymphocytes",
            "lymphocyte",
            "الليمفاوية",
            "monocytes",
            "eosinophils",
            "basophils",
            "platelet",
            "الصفائح",
            "rdw",
            "التحليل",
            "النتيجة",
            "fever",
            "حمى",
            "حرارة",
            "cough",
            "كحة",
            "سعال",
            "common cold",
            "نزلة برد",
            "برد",
            "chest pain",
            "ألم الصدر",
            "shortness of breath",
            "ضيق التنفس",
        )

        has_question_style = any(
            term in text
            for term in question_terms
        )

        has_medical_term = any(
            term in text
            for term in medical_terms
        )

        previous_assistant_text = " ".join(
            str(item.content)
            for item in (history or [])[-30:]
            if getattr(item, "role", None) == "assistant"
        ).lower()
        has_recent_diagnostic_context = any(
            term in previous_assistant_text
            for term in (
                "تقرير صورة الدم",
                "تقرير التحاليل",
                "القيم التالية خارج",
                "حددت الصورة على إنها",
                "identified this image",
                "diagnostic",
                "cbc",
                "قراءة مبدئية من ai",
                "درجة مستقلة",
                "درجة النموذج",
                "الموديل حلل",
                "الموديل حلّل",
                "أشعة الصدر",
                "chest x-ray",
                "screening output",
                "consolidation",
                "pleural_effusion",
                "atelectasis",
            )
        )
        has_follow_up_cue = any(
            term in text
            for term in (
                "معناه",
                "معناها",
                "يعني",
                "فايدته",
                "فايدتها",
                "وظيفة",
                "دور",
                "وظيفته",
                "وظيفتها",
                "بتعمل ايه",
                "بيعمل ايه",
                "خطر",
                "خطير",
                "خطيرة",
                "أقلق",
                "مقلق",
                "اعمل ايه",
                "أعمل ايه",
                "سبب",
                "يأثر",
                "ممكن يكون",
                "مرتبط",
                "why",
                "cause",
                "could that",
                "does this mean",
                "what does that mean",
                "what do",
                "what are",
                "is it",
                "ممكن",
                "هل دا",
                "هل ده",
                "latest",
                "newest",
                "recent research",
                "أحدث",
                "احدث",
                "آخر توصية",
                "اخر توصية",
                "توصيات",
                "إرشادات",
                "ارشادات",
                "what does it do",
                "is that dangerous",
                "عندي برد",
                "عندى برد",
                "وقت التحليل",
                "وقت ما عملت",
                "ساعة ما عملت",
                "عملت التحليل",
                "عملت التحاليل",
                "عمري",
                "عمرى",
                "مش فاهمة",
                "مش فاهمه",
                "مش فاهم",
                "مش فاهمه الموضوع",
                "ايه دخل",
                "إيه دخل",
                "دكتور",
                "طبيب",
                "اروح لمين",
                "أروح لمين",
                "اختصاص",
                "تخصص",
                "متابعة",
            )
        )

        is_answering_diagnostic_context_question = (
            has_recent_diagnostic_context
            and any(
                cue in text
                for cue in (
                    "كان عندي",
                    "انا عندي",
                    "أنا عندي",
                    "عندي برد",
                    "عندى برد",
                    "وقت ما عملت",
                    "ساعة ما عملت",
                    "عمري",
                    "عمرى",
                    "كنت عندي",
                    "كان عنده",
                    "كانت عندي",
                    "اخدت",
                    "أخدت",
                    "باخد",
                    "بتناول",
                    "باستخدم",
                    "عندي حرارة",
                    "حرارتي",
                    "سخونية",
                    "دور برد",
                    "نزلة برد",
                    "عدوى",
                    "مفيش حرارة",
                    "معنديش حرارة",
                    "ايوه",
                    "أيوه",
                    "لا،",
                    "لا ",
                    "yes,",
                    "no,",
                    "i had",
                    "i was taking",
                    "i take",
                )
            )
        )

        return (
            (
                has_question_style
                and (
                    has_medical_term
                    or (
                        has_recent_diagnostic_context
                        and has_follow_up_cue
                    )
                )
            )
            or is_answering_diagnostic_context_question
        )    

    # ========================================================
    # CHAT
    # ========================================================

    async def chat(
        self,
        *,
        session_id: str,
        message: str,
        channel: ConversationChannel,
        diagnostic_mode: str | None = None,
        attachment_ids: list[str] | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        trusted_attachments: (
            list[TrustedDiagnosticAttachment]
            | None
        ) = None,
    ) -> dict:

        chat_started_at = (
            time.perf_counter()
        )

        state_ms = 0.0
        language_ms = 0.0
        history_ms = 0.0
        nlu_ms = 0.0
        workflow_select_ms = 0.0
        workflow_ms = 0.0
        agent_ms = 0.0
        rag_ms = 0.0
        memory_ms = 0.0
        state_save_ms = 0.0

        trusted_attachments = (
            trusted_attachments
            or []
        )
        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        state = await (
            self.state_store
            .get_or_create(
                session_id=session_id,
                tenant_id=self.tenant_id,
                channel=channel,
            )
        )

        state_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # ----------------------------------------------------
        # Language
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        language = (
            resolve_conversation_language(
                text=message,
                previous_language=(
                    state.language
                ),
            )
        )

        state.language = (
            language
        )

        language_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # ----------------------------------------------------
        # Previous messages BEFORE current message
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        history = await (
            self.memory
            .get_recent(
                session_id
            )
        )
        session_history = await (
            self.memory
            .get_all(
                session_id
            )
        )
        client_context = [
            item
            for item in (conversation_context or [])
            if (
                item.get("role") in {"user", "assistant"}
                and str(item.get("content") or "").strip()
            )
        ][-24:]
        if client_context:
            # The browser keeps the visible transcript for the lifetime of
            # its tab. It can restore conversational context after Uvicorn's
            # reload process clears the in-memory store. Treat it only as
            # conversation context; workflow state and tool authorization
            # still come from the server.
            session_history = [
                ChatMessage(
                    role=item["role"],
                    content=str(item["content"]).strip()[:5000],
                )
                for item in client_context
            ]

        history_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        section_started_at = (
            time.perf_counter()
        )

        direct_reply = None
        direct_route = None

        selected_capability = None

        selected_arguments: dict[
            str,
            str,
        ] = {}

        understanding_status = (
            "unknown"
        )

        understanding_attempts = 0

        understanding_broad = False

        legacy_fallback_used = False

        greeting_reply = (
            _greeting_reply(
                message
            )
        )

        understanding_context = (
            self
            ._build_understanding_context(
                state
            )
        )

        trusted_time_fast_path = False

        if (
            state.stage
            == "awaiting_time"
            and
            state.operation_type
            in ACTIVE_WRITE_OPERATIONS
        ):

            time_candidates = (
                resolve_time_reply_candidates(
                    message
                )
            )

            offered_times = {
                slot.start_time[:5]

                for slot
                in state.recent_slots

                if getattr(
                    slot,
                    "start_time",
                    None,
                )
            }

            matching_times = [
                candidate

                for candidate
                in time_candidates

                if candidate
                in offered_times
            ]

            if len(matching_times) == 1:

                resolved_time = (
                    matching_times[0]
                )

                nlu_result = (
                    NLUResult(
                        intent="provide_time",
                        operation_type=None,

                        entities={
                            "time_text":
                                resolved_time,
                        },

                        confirmation="unknown",
                        confidence=1.0,
                    )
                )

                understanding_status = (
                    "trusted_time_fast_path"
                )

                trusted_time_fast_path = (
                    True
                )
        if diagnostic_mode == "auto_image":
            nlu_result = NLUResult(
                intent="unknown",
                operation_type=None,
                confirmation="unknown",
                confidence=1.0,
            )

            if len(trusted_attachments) == 0:
                direct_reply = (
                    "ارفعي صورة واحدة علشان أقدر أحدد نوعها وأحللها."
                    if language == "ar"
                    else "Please upload one image so I can identify and analyze it."
                )
                direct_route = "diagnostics_image_attachment_required"
                understanding_status = "diagnostic_image_attachment_required"

            elif len(trusted_attachments) > 1:
                direct_reply = (
                    "ابعتي صورة واحدة في كل مرة علشان أحدد نوعها بدقة."
                    if language == "ar"
                    else "Please send one image at a time so I can identify it accurately."
                )
                direct_route = "diagnostics_image_single_attachment_required"
                understanding_status = "diagnostic_image_multiple_attachments"

            else:
                allowed = getattr(
                    self.understanding,
                    "allowed_capabilities",
                    None,
                )
                diagnostic_capabilities = {
                    "diagnostics.pathology.analyze",
                    "diagnostics.radiology.analyze",
                }

                if (
                    allowed is not None
                    and not diagnostic_capabilities.intersection(allowed)
                ):
                    direct_reply = (
                        "الجهة الحالية غير مفعّل لها تحليل الصور الطبية. استخدمي Tenant ID لجهة مختبر أو مستشفى مفعّل لها التحليل."
                        if language == "ar"
                        else "Image analysis is not enabled for this provider. Use a lab or hospital tenant with diagnostics enabled."
                    )
                    direct_route = "diagnostics_image_not_enabled"
                    understanding_status = "diagnostic_image_not_enabled"

                elif self.diagnostic_agent_client is None:
                    raise RuntimeError(
                        "DiagnosticAgentClient is not configured."
                    )

                else:
                    attachment = trusted_attachments[0]
                    image_type = await self.diagnostic_agent_client.classify_image(
                        image_bytes=attachment.data,
                        filename=attachment.original_filename,
                        content_type=attachment.content_type,
                    )
                    logger.info(
                        "diagnostic_image_classified category=%s confidence=%.3f",
                        image_type.category,
                        image_type.confidence,
                    )

                    if image_type.confidence < 0.72:
                        direct_reply = (
                            "مش قادر أحدد نوع الصورة بثقة كافية. هل هي صورة تحليل، أشعة صدر، رنين للمخ، ولا مقطعية للكلى؟"
                            if language == "ar"
                            else "I couldn't identify the image confidently. Is it a lab report, chest X-ray, brain MRI, or kidney CT?"
                        )
                        direct_route = "diagnostics_image_clarification"
                        understanding_status = "diagnostic_image_uncertain"

                    elif image_type.category == "pathology":
                        selected_capability = "diagnostics.pathology.analyze"
                        selected_arguments = {}
                        understanding_status = "diagnostic_image_auto_classified"

                    elif image_type.category in {
                        "chest_xray",
                        "brain_mri",
                        "kidney_ct",
                    }:
                        selected_capability = "diagnostics.radiology.analyze"
                        selected_arguments = {
                            "modality": image_type.category,
                        }
                        understanding_status = "diagnostic_image_auto_classified"

                    else:
                        direct_reply = (
                            "الصورة مش من الأنواع المدعومة حاليًا. ارفعي تقرير تحليل أو أشعة صدر أو رنين للمخ أو مقطعية للكلى."
                            if language == "ar"
                            else "This image type isn't supported yet. Upload a lab report, chest X-ray, brain MRI, or kidney CT."
                        )
                        direct_route = "diagnostics_image_unsupported"
                        understanding_status = "diagnostic_image_unsupported"

        elif greeting_reply is not None:

            nlu_result = NLUResult(
                intent="greeting",
                operation_type=None,
                confirmation="unknown",
                confidence=1.0,
            )

            direct_reply = (
                greeting_reply
            )

            understanding_status = (
                "local_greeting"
            )

        elif trusted_time_fast_path:

            logger.info(
                "medmind_trusted_time_fast_path "
                "stage=%s "
                "operation_type=%s",
                state.stage,
                state.operation_type,
            )

        else:

            try:

                understanding_result = await (
                    self.understanding
                    .understand(
                        message=message,
                        context=(
                            understanding_context
                        ),
                    )
                )

                understanding_status = (
                    understanding_result
                    .status
                )

                understanding_attempts = (
                    understanding_result
                    .attempts
                )

                understanding_broad = (
                    understanding_result
                    .used_broad_candidates
                )

                # ================================================
                # SELECTED
                # ================================================

                if (
                    understanding_result.status
                    == "selected"
                ):
                    selected_capability = (
                        understanding_result
                        .capability
                    )

                    selected_arguments = dict(
                        understanding_result.arguments
                        or {}
                    )

                    if (
                        selected_capability
                        in DIAGNOSTIC_CAPABILITIES
                    ):
                        nlu_result = NLUResult(
                            intent="unknown",
                            operation_type=None,
                            confirmation="unknown",
                            confidence=1.0,
                        )

                    else:
                        nlu_result = (
                            adapt_understanding_to_nlu(
                                result=(
                                    understanding_result
                                ),
                                state=state,
                            )
                        )

                # ================================================
                # NEEDS CLARIFICATION
                #
                # Do NOT spend another large LLM call here.
                # ================================================

                elif (
                    understanding_result.status
                    == "ambiguous"
                ):

                    # ====================================================
                    # CONTEXTUAL TIME FALLBACK
                    #
                    # If an active workflow is waiting for a time and
                    # general Understanding could not interpret a short
                    # reply, reuse the existing deterministic resolver.
                    # ====================================================

                    contextual_time_handled = False

                    if (
                        state.stage
                        == "awaiting_time"
                        and
                        state.operation_type
                        in ACTIVE_WRITE_OPERATIONS
                    ):

                        time_candidates = (
                            resolve_time_candidates(
                                message
                            )
                        )

                        offered_times = {
                            slot.start_time[:5]
                            for slot in state.recent_slots
                            if slot.start_time
                        }

                        matching_times = [
                            candidate
                            for candidate in time_candidates
                            if candidate in offered_times
                        ]

                        if matching_times:

                            nlu_result = (
                                NLUResult(
                                    intent="provide_time",
                                    operation_type=None,
                                    entities={
                                        "time_text":
                                            message,
                                    },
                                    confirmation="unknown",
                                    confidence=1.0,
                                )
                            )

                            understanding_status = (
                                "contextual_time_resolver"
                            )

                            contextual_time_handled = True

                    if not contextual_time_handled:

                        nlu_result = (
                            NLUResult(
                                intent="unknown",
                                operation_type=None,
                                confirmation="unknown",
                                confidence=0.0,
                            )
                        )

                        direct_reply = (
                            self._understanding_clarification_reply(
                                language,
                                state=state,
                            )
                        )

                # ================================================
                # UNDERSTANDING TIMEOUT
                # ================================================

                elif (
                    understanding_result.status
                    == "fallback_required"
                    and
                    understanding_result.reason
                    == "understanding_timeout"
                ):

                    logger.warning(
                        "medmind_understanding_degraded "
                        "reason=understanding_timeout "
                        "legacy_fallback=False"
                    )

                    nlu_result = (
                        NLUResult(
                            intent="unknown",
                            operation_type=None,
                            confirmation="unknown",
                            confidence=0.0,
                        )
                    )

                    direct_reply = (
                        self._understanding_clarification_reply(
                            language,
                            state=state,
                        )
                    )

                # ================================================
                # STRONG FALLBACK
                # ================================================

                else:

                    legacy_fallback_used = (
                        True
                    )

                    nlu_result = await (
                        self.nlu
                        .understand(
                            message=message,

                            language=language,

                            state=state,

                history=session_history,
                        )
                    )

            except Exception:

                logger.exception(
                    "medmind_understanding_failed "
                    "using_degraded_clarification"
                )

                understanding_status = (
                    "error"
                )

                nlu_result = (
                    NLUResult(
                        intent="unknown",
                        operation_type=None,
                        confirmation="unknown",
                        confidence=0.0,
                    )
                )

                direct_reply = (
                    self._understanding_clarification_reply(
                        language,
                        state=state,
                    )
                )

        nlu_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # A follow-up about a previously analyzed report is a conversation
        # turn, not a request to run the image analyzer again. Diagnostic
        # capabilities require a fresh attachment, so route these turns to
        # the medical education path with the recent report in chat history.
        if (
            not trusted_attachments
            and not (
                state.stage.startswith("awaiting_")
                and state.operation_type in ACTIVE_WRITE_OPERATIONS
            )
            and self._looks_like_medical_education_question(
                message=message,
                history=session_history,
            )
        ):
            selected_capability = None
            selected_arguments = {}
            direct_reply = None
            direct_route = None
            nlu_result = NLUResult(
                intent="unknown",
                operation_type=None,
                confirmation="unknown",
                confidence=1.0,
            )
            understanding_status = "diagnostic_follow_up"

        # ----------------------------------------------------
        # Deterministic workflow selection
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        side_question = False
        side_read_state = None


        if direct_reply is not None:

            workflow = None

        else:

            side_question = (
                self._is_side_question(
                    state=state,
                    nlu=nlu_result,
                    selected_capability=(
                        selected_capability
                    ),
                )
            )

            if side_question:

                # Run the informational request on an isolated
                # copy so it cannot damage the active workflow.
                side_read_state = (
                    self._create_side_read_state(
                        state
                    )
                )

                workflow = None

                logger.info(
                    "medmind_side_question_detected "
                    "active_operation=%s "
                    "stage=%s "
                    "capability=%s "
                    "intent=%s",
                    state.operation_type,
                    state.stage,
                    selected_capability,
                    nlu_result.intent,
                )

            else:

                workflow = (
                    self
                    ._select_workflow(
                        state=state,
                        nlu=nlu_result,
                    )
                )

        workflow_select_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # Default response metadata.

        tool_calls = []
        response_type = None
        route = "read_agent"

        diagnostic_result = None

        # ====================================================
        # DIRECT UNDERSTANDING CLARIFICATION
        # ====================================================

        if direct_reply is not None:

            reply = (
                direct_reply
            )

            route = direct_route or "understanding_clarification"

            response_type = (
                "clarification"
            )

        # ====================================================
        # WRITE WORKFLOW
        # ====================================================

        elif workflow is not None:

            section_started_at = (
                time.perf_counter()
            )

            workflow_result = await (
                workflow
                .handle(
                    state=state,
                    nlu=nlu_result,
                    user_message=message,
                )
            )

            workflow_ms = (
                (
                    time.perf_counter()
                    - section_started_at
                )
                * 1000
            )

            # The router selected the workflow deliberately.
            # Normally handled=True.
            #
            # If a workflow still says handled=False,
            # safely fall back to the read agent.

            if workflow_result.handled:

                reply = (
                    workflow_result.reply
                )

                response_type = (
                    workflow_result
                    .response_type
                )

                route = (
                    state.operation_type
                    or
                    "workflow"
                )

            else:

                agent_started_at = (
                    time.perf_counter()
                )

                agent_result = await (
                    self.agent
                    .run(
                        user_message=(
                            message
                        ),

                        language=(
                            language
                        ),

                        history=(
                            history
                        ),

                        state=(
                            state
                        ),
                    )
                )

                agent_ms += (
                    (
                        time.perf_counter()
                        - agent_started_at
                    )
                    * 1000
                )

                reply = (
                    agent_result.reply
                )

                tool_calls = (
                    agent_result.tool_calls
                )

                for observation in (
                    agent_result
                    .tool_observations
                ):

                    apply_tool_observation(
                        state=state,

                        tool_name=(
                            observation.name
                        ),

                        data=(
                            observation.data
                        ),
                    )

        else:

            # ====================================================
            # ISOLATED READ STATE
            # ====================================================

            read_state = (
                side_read_state
                if side_read_state is not None
                else state
            )

            # ========================================================
            # V2 READ ROUTE
            #
            # Prefer Understanding capability.
            # Fall back to legacy NLU intent during migration.
            # ========================================================

            read_route = resolve_read_route(
                selected_capability=(
                    selected_capability
                ),
                intent=(
                    nlu_result.intent
                ),
            )

            safety_result = (
                self.diagnostic_safety_guard
                .check_text(
                    message=message,
                    language=language,
                )
            )

            # ========================================================
            # DIAGNOSTIC SAFETY GUARD
            # ========================================================

            if (
                selected_capability
                in DIAGNOSTIC_CAPABILITIES
            ):

                if safety_result.blocked:

                    reply = (
                        safety_result
                        .message_to_patient
                    )

                    response_type = (
                        "diagnostic_safety"
                    )

                    route = (
                        "diagnostics_safety_guard"
                    )

                    diagnostic_result = {
                        "kind":
                            "diagnostic_safety",

                        "urgency":
                            (
                                safety_result
                                .urgency
                                .value
                            ),

                        "triggered_rules":
                            list(
                                safety_result
                                .triggered_rules
                            ),

                        "confirmation_field":
                            (
                                safety_result
                                .confirmation_field
                            ),
                    }

                    workflow_ms = 0.0

            # ========================================================
            # DETERMINISTIC RADIOLOGY EXECUTION
            # ========================================================

            if (
                response_type
                == "diagnostic_safety"
            ):
                pass

            elif (
                selected_capability
                == "diagnostics.radiology.analyze"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                # ----------------------------------------------------
                # Exactly one trusted attachment is required.
                #
                # Do not guess which image to analyze.
                # ----------------------------------------------------

                if len(
                    trusted_attachments
                ) == 0:

                    if language == "en":
                        reply = (
                            "Please upload one radiology image "
                            "for analysis."
                        )
                    else:
                        reply = (
                            "من فضلك ارفع صورة الأشعة "
                            "اللي عايز تحللها."
                        )

                    response_type = (
                        "clarification"
                    )

                    route = (
                        "diagnostics_radiology_"
                        "attachment_required"
                    )

                elif len(
                    trusted_attachments
                ) > 1:

                    if language == "en":
                        reply = (
                            "Please send one radiology image "
                            "at a time."
                        )
                    else:
                        reply = (
                            "من فضلك ابعت صورة أشعة واحدة "
                            "في كل مرة."
                        )

                    response_type = (
                        "clarification"
                    )

                    route = (
                        "diagnostics_radiology_"
                        "single_attachment_required"
                    )

                else:

                    modality = str(
                        selected_arguments.get(
                            "modality"
                        )
                        or ""
                    ).strip()

                    # ------------------------------------------------
                    # Defensive guard.
                    #
                    # The Understanding validator should already
                    # prevent this state, but execution must also
                    # fail closed.
                    # ------------------------------------------------

                    if not modality:

                        if language == "en":
                            reply = (
                                "Please specify the type of "
                                "radiology image: chest X-ray, "
                                "brain MRI, or kidney CT."
                            )
                        else:
                            reply = (
                                "من فضلك حدد نوع الأشعة: "
                                "أشعة صدر، رنين مغناطيسي للمخ، "
                                "أو أشعة مقطعية للكلى."
                            )

                        response_type = (
                            "clarification"
                        )

                        route = (
                            "diagnostics_radiology_"
                            "modality_required"
                        )

                    elif (
                        self.diagnostic_agent_client
                        is None
                    ):

                        raise RuntimeError(
                            "DiagnosticAgentClient "
                            "is not configured."
                        )

                    else:

                        attachment = (
                            trusted_attachments[0]
                        )

                        radiology_result = await (
                            self.diagnostic_agent_client
                            .analyze_radiology(
                                image_bytes=(
                                    attachment.data
                                ),
                                filename=(
                                    attachment
                                    .original_filename
                                ),
                                content_type=(
                                    attachment
                                    .content_type
                                ),
                                modality=modality,
                            )
                        )


                        diagnostic_result = {
                            "kind":
                                "radiology",

                            "schema_version":
                                "1.0",

                            "attachment_id":
                                attachment.attachment_id,

                            "modality":
                                radiology_result.modality,

                            "classification":
                                radiology_result.classification,

                            "probabilities":
                                dict(
                                    radiology_result.probabilities
                                ),

                            "confidence":
                                radiology_result.confidence,

                            "score_semantics":
                                radiology_result.score_semantics,

                            "inference_latency_ms":
                                radiology_result.inference_latency_ms,

                            "model_name":
                                radiology_result.model_name,

                            "model_version":
                                radiology_result.model_version,

                            "limitations":
                                list(
                                    radiology_result.limitations
                                ),
                        }

                        # ------------------------------------------------
                        # IMPORTANT:
                        #
                        # Do not expose the classification yet.
                        #
                        # Persistence + safe clinical explanation will
                        # be added in the next steps.
                        # ------------------------------------------------

                        reply = (
                            self.diagnostic_explanation_service
                            .explain_radiology(
                                result=diagnostic_result,
                                language=language,
                            )
                        )
                        if diagnostic_mode == "auto_image":
                            detected_type = {
                                "chest_xray": "أشعة صدر",
                                "brain_mri": "رنين مغناطيسي للمخ",
                                "kidney_ct": "أشعة مقطعية على الكلى",
                            }.get(modality, modality)
                            detected_prefix = (
                                f"حددت الصورة على إنها {detected_type}.\n\n"
                                if language == "ar"
                                else f"I identified this image as {modality.replace('_', ' ')}.\n\n"
                            )
                            reply = detected_prefix + reply

                        response_type = (
                            "diagnostic_radiology"
                        )

                        route = (
                            "diagnostics_radiology"
                        )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )


            # ========================================================
            # DETERMINISTIC PATHOLOGY EXECUTION
            # ========================================================

            elif (
                    selected_capability
                    == "diagnostics.pathology.analyze"
                ):

                    section_started_at = (
                        time.perf_counter()
                    )

                    # ----------------------------------------------------
                    # Exactly one trusted lab-report attachment.
                    # ----------------------------------------------------

                    if len(
                        trusted_attachments
                    ) == 0:

                        if language == "en":
                            reply = (
                                "Please upload one laboratory "
                                "report for analysis."
                            )
                        else:
                            reply = (
                                "من فضلك ارفع صورة تحليل واحدة "
                                "علشان أقدر أحللها."
                            )

                        response_type = (
                            "clarification"
                        )

                        route = (
                            "diagnostics_pathology_"
                            "attachment_required"
                        )

                    elif len(
                        trusted_attachments
                    ) > 1:

                        if language == "en":
                            reply = (
                                "Please send one laboratory "
                                "report at a time."
                            )
                        else:
                            reply = (
                                "من فضلك ابعت صورة تحليل واحدة "
                                "في كل مرة."
                            )

                        response_type = (
                            "clarification"
                        )

                        route = (
                            "diagnostics_pathology_"
                            "single_attachment_required"
                        )

                    elif (
                        self.diagnostic_agent_client
                        is None
                    ):

                        raise RuntimeError(
                            "DiagnosticAgentClient "
                            "is not configured."
                        )

                    else:

                        attachment = (
                            trusted_attachments[0]
                        )

                        pathology_result = await (
                            self.diagnostic_agent_client
                            .analyze_pathology(
                                image_bytes=(
                                    attachment.data
                                ),
                                filename=(
                                    attachment
                                    .original_filename
                                ),
                                content_type=(
                                    attachment
                                    .content_type
                                ),
                            )
                        )

                        diagnostic_result = {
                            "kind":
                                "pathology",

                            "schema_version":
                                pathology_result
                                .schema_version,

                            "attachment_id":
                                attachment
                                .attachment_id,

                            "document_type":
                                pathology_result
                                .document_type,

                            "unreadable_fields":
                                list(
                                    pathology_result
                                    .unreadable_fields
                                ),

                            "results": [
                                item.model_dump(
                                    mode="json"
                                )
                                for item
                                in pathology_result.results
                            ],
                        }

                        # Do not expose medical interpretation yet.
                        # Persistence + safe explanation comes next.

                        reply = (
                            self.diagnostic_explanation_service
                            .explain_pathology(
                                result=diagnostic_result,
                                language=language,
                            )
                        )
                        if diagnostic_mode == "auto_image":
                            detected_prefix = (
                                "حددت الصورة على إنها تقرير تحاليل.\n\n"
                                if language == "ar"
                                else "I identified this image as a laboratory report.\n\n"
                            )
                            reply = detected_prefix + reply
                        response_type = (
                            "diagnostic_pathology"
                        )

                        route = (
                            "diagnostics_pathology"
                        )

                    workflow_ms = (
                        (
                            time.perf_counter()
                            - section_started_at
                        )
                        * 1000
                    )    

            # ====================================================
            # DETERMINISTIC AVAILABLE-SLOTS READ
            # ====================================================

            elif (
                read_route
                == "available_slots"
            ):
                section_started_at = (
                    time.perf_counter()
                )

                (
                    reply,
                    response_type,
                ) = await (
                    self._handle_available_slots_read(
                        state=read_state,
                        nlu=nlu_result,
                        language=language,
                        channel=channel,
                    )
                )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                route = (
                    "available_slots_read"
                )

            # ====================================================
            # DETERMINISTIC WORKING-HOURS READ
            # ====================================================

            elif (
                read_route
                == "working_hours"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                (
                    reply,
                    response_type,
                ) = await (
                    self._handle_working_hours_read(
                        state=read_state,
                        nlu=nlu_result,
                        language=language,
                    )
                )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                route = (
                    "working_hours_read"
                )

            # ====================================================
            # DETERMINISTIC SPECIALTY READ
            # ====================================================

            elif (
                read_route
                == "specialty"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                specialties_result = await (
                    self.tools.call(
                        "list_specialties"
                    )
                )

                specialties_result = (
                    self._ensure_list_result(
                        specialties_result
                    )
                )

                apply_tool_observation(
                    state=read_state,
                    tool_name="list_specialties",
                    data=specialties_result,
                )

                specialties = list(
                    read_state.recent_specialties
                )

                display_limit = (
                    6
                    if channel == "voice"
                    else 20
                )

                names = []

                for specialty in specialties[
                    :display_limit
                ]:

                    name = (
                        specialty.name_en
                        if language == "en"
                        else specialty.name_ar
                    ) or (
                        specialty.name_ar
                        or specialty.name_en
                    )

                    if name:
                        names.append(name)

                if not names:

                    if language == "en":
                        reply = (
                            "There are no specialties "
                            "available at the moment."
                        )
                    else:
                        reply = (
                            "مفيش تخصصات متاحة حالياً."
                        )

                    response_type = (
                        "no_specialties"
                    )

                else:

                    has_more = (
                        len(specialties)
                        > display_limit
                    )

                    if language == "en":

                        reply = (
                            "Available specialties: "
                            + ", ".join(names)
                            + "."
                        )

                        if has_more:
                            reply += (
                                " There are more specialties "
                                "available."
                            )

                    else:

                        reply = (
                            "التخصصات المتاحة: "
                            + "، ".join(names)
                            + "."
                        )

                        if has_more:
                            reply += (
                                " وفي تخصصات تانية متاحة."
                            )

                    response_type = (
                        "specialty_list"
                    )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                route = (
                    "specialty_read"
                )    

            # ====================================================
            # DETERMINISTIC DOCTOR READ
            # ====================================================

            elif (
                read_route
                == "doctor"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                (
                    reply,
                    response_type,
                ) = await (
                    self._handle_doctor_read(
                        state=read_state,
                        nlu=nlu_result,
                        language=language,
                        channel=channel,
                    )
                )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                route = (
                    "doctor_read"
                )

            # ====================================================
            # DETERMINISTIC SERVICE READ
            # ====================================================

            elif (
                read_route
                == "service"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                (
                    reply,
                    response_type,
                ) = await (
                    self._handle_service_read(
                        state=read_state,
                        nlu=nlu_result,
                        language=language,
                        channel=channel,
                        user_message=message,
                    )
                )

                workflow_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                route = (
                    "service_read"
                )


            # ====================================================
            # MEDICAL EDUCATION AGENT
            # ====================================================

            elif (
                not trusted_attachments
                and
                self._looks_like_medical_education_question(
                    message=message,
                    history=session_history,
                )
            ):

                section_started_at = (
                    time.perf_counter()
                )

                prior_diagnostic_context = "\n".join(
                    str(item.content).strip()
                    for item in (session_history or [])[-30:]
                    if (
                        getattr(item, "role", None) == "assistant"
                        and any(
                            marker in str(item.content).lower()
                            for marker in (
                                "تقرير صورة الدم",
                                "تقرير التحاليل",
                                "القيم التالية خارج",
                                "حددت الصورة على إنها",
                                "identified this image",
                                "cbc",
                                "قراءة مبدئية من ai",
                                "درجة مستقلة",
                                "درجة النموذج",
                                "الموديل حلل",
                                "الموديل حلّل",
                                "أشعة الصدر",
                                "chest x-ray",
                                "screening output",
                                "consolidation",
                                "pleural_effusion",
                                "atelectasis",
                            )
                        )
                    )
                )[-1800:]
                education_query = message
                if prior_diagnostic_context:
                    education_query += (
                        "\n\nالسياق السابق في المحادثة: "
                        + prior_diagnostic_context
                    )
                recent_conversation_context = "\n".join(
                    f"{getattr(item, 'role', 'unknown')}: "
                    f"{str(getattr(item, 'content', '')).strip()}"
                    for item in (session_history or [])[-24:]
                    if str(getattr(item, "content", "")).strip()
                )[-3500:]
                if recent_conversation_context:
                    education_query += (
                        "\n\nالرسائل الأخيرة ذات الصلة من نفس الجلسة "
                        "(للحفاظ على السياق فقط):\n"
                        + recent_conversation_context
                    )

                education_result = (
                    self.medical_education_agent
                    .answer(
                        query=education_query,
                        language=language,
                    )
                )

                evidence_topic = (
                    self.medical_evidence_retriever
                    .topic_for(education_query)
                )
                freshness_requested = (
                    self.medical_evidence_retriever
                    .requests_recent_evidence(message)
                )
                guideline_requested = (
                    self.medical_evidence_retriever
                    .requests_guideline(message)
                )
                external_sources: list[ExternalMedicalSource] = []
                if (
                    evidence_topic
                    and (
                        education_result.status
                        == MedicalEducationStatus.UNSUPPORTED
                        or freshness_requested
                    )
                ):
                    external_sources = await (
                        self.medical_evidence_retriever
                        .search(
                            topic=evidence_topic,
                            include_literature=freshness_requested,
                            guidelines_only=guideline_requested,
                        )
                    )

                sources_for_answer = external_sources
                if guideline_requested:
                    sources_for_answer = [
                        source
                        for source in external_sources
                        if source.source_type
                        == "PubMed-indexed guideline"
                    ]
                elif freshness_requested:
                    sources_for_answer = [
                        source
                        for source in external_sources
                        if source.source_type
                        == "research article abstract"
                    ]

                education_contexts = list(
                    education_result.context_used
                )
                education_source_names = [
                    source.source_file
                    for source in education_result.sources
                ]
                for source in sources_for_answer:
                    education_contexts.append(
                        f"Source: {source.publisher}. "
                        f"Source type: {source.source_type}. "
                        f"Title: {source.title}. "
                        f"Published: {source.published or 'not specified'}.\n"
                        f"Content: {source.summary}"
                    )
                    education_source_names.append(
                        f"{source.publisher}: {source.title}"
                    )

                rag_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                llm_reply = None

                if (
                    self.response_verbalizer
                    is not None
                    and
                    hasattr(
                        self.response_verbalizer,
                        "verbalize_medical_education",
                    )
                    and
                    education_contexts
                    and (
                        not freshness_requested
                        or sources_for_answer
                    )
                ):

                    verbalizer_started_at = (
                        time.perf_counter()
                    )

                    llm_reply = await (
                        self.response_verbalizer
                        .verbalize_medical_education(
                            question=education_query,

                            contexts=education_contexts,

                            source_names=education_source_names,

                            language=language,
                        )
                    )

                    agent_ms = (
                        (
                            time.perf_counter()
                            - verbalizer_started_at
                        )
                        * 1000
                    )

                if llm_reply:
                    reply = llm_reply
                elif (
                    sources_for_answer
                    and education_result.status
                    == MedicalEducationStatus.UNSUPPORTED
                ):
                    reply = (
                        "لقيت مرجعًا طبيًا مناسبًا، لكن تعذّر تلخيصه بأمان الآن. "
                        "راجعي الروابط في الأسفل."
                        if language == "ar"
                        else "I found relevant medical references, but could not summarize them safely right now. Please review the links below."
                    )
                else:
                    reply = education_result.reply

                if freshness_requested and not sources_for_answer:
                    freshness_notice = (
                        "\n\nماقدرتش أتحقق من مرجع حديث الآن؛ الإجابة أعلاه من المكتبة المحلية فقط."
                        if language == "ar"
                        else "\n\nI could not verify a current external reference; the answer above uses the local knowledge base only."
                    )
                    reply += freshness_notice

                if sources_for_answer and (
                    llm_reply
                    or education_result.status
                    == MedicalEducationStatus.UNSUPPORTED
                ):
                    source_heading = (
                        "\n\nمراجع خارجية (للاطلاع):"
                        if language == "ar"
                        else "\n\nExternal references:"
                    )
                    source_heading += (
                        f" — {self.medical_evidence_retriever.retrieved_date()}"
                    )
                    source_lines = []
                    for source in sources_for_answer:
                        publication_date = (
                            f" — {source.published}"
                            if source.published
                            else ""
                        )
                        source_lines.append(
                            f"• {source.title}{publication_date}\n"
                            f"  {'Source type' if language == 'en' else 'نوع المصدر'}: {source.source_type}\n"
                            f"  {source.publisher}\n"
                            f"  {source.url}"
                        )
                    reply += source_heading + "\n" + "\n".join(source_lines)

                route = (
                    "medical_education"
                )

                response_type = (
                    "medical_education"
                    if (
                        education_result.status
                        == MedicalEducationStatus.ANSWERED
                    )
                    else
                    "medical_education_unsupported"
                )    

            # ====================================================
            # PROVIDER KNOWLEDGE
            # ====================================================

            elif (
                read_route
                == "knowledge"
            ):

                section_started_at = (
                    time.perf_counter()
                )

                rag_result = await (
                    answer_provider_knowledge(
                        tenant_id=
                            self.tenant_id,

                        query=
                            message,

                        language=
                            language,
                    )
                )

                rag_ms = (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                reply = (
                    rag_result.answer
                )

                route = (
                    "provider_rag"
                )

                response_type = (
                    "rag_answer"
                    if rag_result.supported
                    else
                    "rag_unsupported"
                )

            # ====================================================
            # READ AGENT
            # ====================================================

            else:

                section_started_at = (
                    time.perf_counter()
                )

                agent_result = await (
                    self.agent
                    .run(
                        user_message=(
                            message
                        ),

                        language=(
                            language
                        ),

                        history=(
                            history
                        ),

                        state=(
                            read_state
                        ),
                    )
                )

                agent_ms += (
                    (
                        time.perf_counter()
                        - section_started_at
                    )
                    * 1000
                )

                reply = (
                    agent_result.reply
                )

                tool_calls = (
                    agent_result.tool_calls
                )

                for observation in (
                    agent_result
                    .tool_observations
                ):

                    apply_tool_observation(
                        state=read_state,

                        tool_name=(
                            observation.name
                        ),

                        data=(
                            observation.data
                        ),
                    )
        
        # ========================================================
        # SIDE-QUESTION RESTORE
        # ========================================================

        if (
            side_question
            and
            side_read_state is not None
        ):

            self._merge_side_read_context(
                target=state,
                source=side_read_state,
            )

            logger.info(
                "medmind_side_question_completed "
                "active_operation=%s "
                "preserved_stage=%s "
                "capability=%s",
                state.operation_type,
                state.stage,
                selected_capability,
            )
       

        if direct_reply is None:

            persistent_focus_capability = (
                selected_capability
            )

            if persistent_focus_capability in {
                "appointment.create",
                "appointment.cancel",
                "appointment.reschedule",
            }:

                persistent_focus_capability = (
                    None
                )

            remember_conversation_focus(
                state=state,
                nlu=nlu_result,
                capability=(
                    persistent_focus_capability
                ),
            )
        # ----------------------------------------------------
        # Save conversation
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        await (
            self.memory
            .add_user_message(
                session_id=session_id,
                content=message,
            )
        )

        await (
            self.memory
            .add_assistant_message(
                session_id=session_id,
                content=reply,
            )
        )

        memory_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # ----------------------------------------------------
        # Save state
        # ----------------------------------------------------

        section_started_at = (
            time.perf_counter()
        )

        await (
            self.state_store
            .save(
                state
            )
        )

        state_save_ms = (
            (
                time.perf_counter()
                - section_started_at
            )
            * 1000
        )

        # ----------------------------------------------------
        # Response timing
        # ----------------------------------------------------

        total_ms = (
            (
                time.perf_counter()
                - chat_started_at
            )
            * 1000
        )

        logger.info(
            "medmind_chat_timing "
            "stage=%s "
            "intent=%s "
            "route=%s "
            "understanding_status=%s "
            "understanding_attempts=%s "
            "understanding_broad=%s "
            "legacy_fallback=%s "
            "state_ms=%.2f "
            "language_ms=%.2f "
            "history_ms=%.2f "
            "nlu_ms=%.2f "
            "workflow_select_ms=%.2f "
            "workflow_ms=%.2f "
            "agent_ms=%.2f "
            "rag_ms=%.2f "
            "memory_ms=%.2f "
            "state_save_ms=%.2f "
            "total_ms=%.2f",
            state.stage,
            nlu_result.intent,
            route,
            understanding_status,
            understanding_attempts,
            understanding_broad,
            legacy_fallback_used,
            state_ms,
            language_ms,
            history_ms,
            nlu_ms,
            workflow_select_ms,
            workflow_ms,
            agent_ms,
            rag_ms,
            memory_ms,
            state_save_ms,
            total_ms,
        )

        return {
            "session_id":
                session_id,

            "language":
                state.language,

            "reply":
                reply,

            "intent":
                nlu_result.intent,

            "route":
                route,

            "response_type":
                response_type,

            "tool_calls":
                tool_calls,

            "diagnostic_result":
                diagnostic_result,    

            "state":
                state.safe_llm_context(),
        }

    # ========================================================
    # DEBUG HELPERS
    # ========================================================

    async def get_history(
        self,
        session_id: str,
    ):

        return await (
            self.memory
            .get_all(
                session_id
            )
        )

    async def get_state(
        self,
        session_id: str,
    ):

        return await (
            self.state_store
            .get(
                session_id
            )
        )
