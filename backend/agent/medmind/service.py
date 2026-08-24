from __future__ import annotations

import os

from dotenv import (
    load_dotenv,
)

from langchain_openai import (
    ChatOpenAI,
)

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
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

from medmind.language import (
    resolve_conversation_language,
)

from medmind.memory.conversation import (
    ConversationMemory,
)

from medmind.state.store import (
    InMemoryStateStore,
)

from medmind.state.updater import (
    apply_tool_observation,
)

from medmind.understanding.llm import (
    LLMNLU,
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

from medmind.rag_gateway import (
    answer_provider_knowledge,
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
        booking_workflow: BookingWorkflow,
        cancel_workflow: CancelWorkflow,
        reschedule_workflow: RescheduleWorkflow,
        state_store: InMemoryStateStore,
        memory: ConversationMemory,
    ) -> None:

        self.tenant_id = (
            tenant_id
        )

        self.agent = (
            agent
        )

        self.nlu = (
            nlu
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

    # ========================================================
    # FACTORY
    # ========================================================

    @classmethod
    async def create(
        cls,
        *,
        tenant_id: str | None = None,
    ) -> "MedMindService":

        load_dotenv(
            override=True
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

        # ----------------------------------------------------
        # MCP
        #
        # all_tools:
        #     used by deterministic workflows through
        #     MCPToolExecutor.
        #
        # read_tools:
        #     only safe read tools are exposed to the
        #     LLM read agent.
        # ----------------------------------------------------

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
                    }
                }
            )
        )

        all_tools = await (
            client.get_tools()
        )

        read_tools = (
            select_read_tools(
                all_tools
            )
        )

        tool_executor = (
            MCPToolExecutor(
                all_tools
            )
        )

        # ----------------------------------------------------
        # Shared LLM
        # ----------------------------------------------------

        model = ChatOpenAI(
            model=model_name,
            temperature=0,
            timeout=60,
        )

        # ----------------------------------------------------
        # NLU
        # ----------------------------------------------------

        nlu = (
            LLMNLU(
                model=model
            )
        )

        # ----------------------------------------------------
        # Read Agent
        #
        # Important:
        # It receives only read tools.
        # ----------------------------------------------------

        agent = (
            MedMindReadAgent(
                model=model,
                tools=read_tools,
            )
        )

        # ----------------------------------------------------
        # Deterministic write workflows
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Memory + State
        # ----------------------------------------------------

        memory = (
            ConversationMemory(
                recent_message_limit=12
            )
        )

        state_store = (
            InMemoryStateStore()
        )

        return cls(
            tenant_id=
                resolved_tenant_id,

            agent=
                agent,

            nlu=
                nlu,

            booking_workflow=
                booking_workflow,

            cancel_workflow=
                cancel_workflow,

            reschedule_workflow=
                reschedule_workflow,

            state_store=
                state_store,

            memory=
                memory,
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

        1. A new explicit operation from the current
           user message.

        2. Continue an already-active workflow.

        3. Otherwise use the read agent.

        This allows a user to switch operations, for example:

            booking -> cancel

        without the previous workflow trapping the session.
        """

        # ----------------------------------------------------
        # 1. Explicit operation in current message
        # ----------------------------------------------------

        requested_operation = (
            nlu.operation_type
        )

        # Defensive mapping in case an operation intent
        # is present while operation_type is null.
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

        # ----------------------------------------------------
        # 2. Continue active workflow
        #
        # Only active conversational stages continue routing.
        #
        # Terminal stages such as:
        #
        # booking_completed
        # cancel_completed
        # cancel_declined
        # reschedule_completed
        # reschedule_declined
        #
        # should NOT trap future unrelated messages.
        # ----------------------------------------------------

        active_stage = (
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

        # ----------------------------------------------------
        # 3. No deterministic workflow
        # ----------------------------------------------------

        return None

    # ========================================================
    # CHAT
    # ========================================================

    async def chat(
        self,
        *,
        session_id: str,
        message: str,
    ) -> dict:

        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        state = await (
            self.state_store
            .get_or_create(
                session_id=
                    session_id,

                tenant_id=
                    self.tenant_id,
            )
        )

        # ----------------------------------------------------
        # Language
        # ----------------------------------------------------

        language = (
            resolve_conversation_language(
                text=message,
                previous_language=
                    state.language,
            )
        )

        state.language = (
            language
        )

        # ----------------------------------------------------
        # Previous messages BEFORE current message
        # ----------------------------------------------------

        history = await (
            self.memory.get_recent(
                session_id
            )
        )

        # ----------------------------------------------------
        # NLU
        # ----------------------------------------------------

        nlu_result = await (
            self.nlu.understand(
                message=
                    message,

                language=
                    language,

                state=
                    state,

                history=
                    history,
            )
        )

        # ----------------------------------------------------
        # Deterministic workflow selection
        # ----------------------------------------------------

        workflow = (
            self._select_workflow(
                state=state,
                nlu=nlu_result,
            )
        )

        # Default response metadata.
        tool_calls = []
        response_type = None
        route = "read_agent"

        # ====================================================
        # WRITE WORKFLOW
        # ====================================================

        if workflow is not None:

            workflow_result = await (
                workflow.handle(
                    state=state,
                    nlu=nlu_result,
                    user_message=message,
                )
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
                    workflow_result.response_type
                )

                route = (
                    state.operation_type
                    or
                    "workflow"
                )

            else:

                agent_result = await (
                    self.agent.run(
                        user_message=
                            message,

                        language=
                            language,

                        history=
                            history,

                        state=
                            state,
                    )
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

                        tool_name=
                            observation.name,

                        data=
                            observation.data,
                    )

        # ====================================================
        # READ AGENT
        # ====================================================

        # ====================================================
        # PROVIDER KNOWLEDGE RAG
        # ====================================================

        else:

            if (
                nlu_result.intent
                == "ask_provider"
            ):

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

            else:

                # ============================================
                # READ AGENT
                # ============================================

                agent_result = await (
                    self.agent.run(
                        user_message=
                            message,

                        language=
                            language,

                        history=
                            history,

                        state=
                            state,
                    )
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

                        tool_name=
                            observation.name,

                        data=
                            observation.data,
                    )

        # ----------------------------------------------------
        # Save conversation
        # ----------------------------------------------------

        await (
            self.memory
            .add_user_message(
                session_id=
                    session_id,

                content=
                    message,
            )
        )

        await (
            self.memory
            .add_assistant_message(
                session_id=
                    session_id,

                content=
                    reply,
            )
        )

        # ----------------------------------------------------
        # Save state
        # ----------------------------------------------------

        await (
            self.state_store.save(
                state
            )
        )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

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
            self.memory.get_all(
                session_id
            )
        )

    async def get_state(
        self,
        session_id: str,
    ):

        return await (
            self.state_store.get(
                session_id
            )
        )
