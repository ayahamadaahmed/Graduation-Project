from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from dataclasses import dataclass

from dotenv import load_dotenv

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langchain_openai import (
    ChatOpenAI,
)

from pydantic import (
    BaseModel,
    Field,
)

from rag.retriever import (
    retrieve_chunks,
)


logger = logging.getLogger("uvicorn.error")


RAG_DEFAULT_LIMIT = int(
    os.getenv(
        "RAG_DEFAULT_LIMIT",
        "2",
    )
)


RAG_CONTEXT_CHARS = int(
    os.getenv(
        "RAG_CONTEXT_CHARS",
        "700",
    )
)


class GroundedResponse(
    BaseModel
):

    answer: str = Field(
        description=(
            "The grounded answer to the user. "
            "If the retrieved context does not contain "
            "enough information, clearly say that the "
            "information is not available."
        )
    )

    source_indexes: list[int] = Field(
        description=(
            "The 1-based SOURCE numbers that directly "
            "contain the facts used in the answer. "
            "Return an empty list only when the retrieved "
            "context does not support an answer."
        )
    )


def _message_content_to_text(
    content: object,
) -> str:

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("content")
                )

                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))

        return "\n".join(parts)

    return str(content)


def _parse_grounded_response(
    content: object,
) -> GroundedResponse:

    text = (
        _message_content_to_text(
            content
        )
        .strip()
    )

    if text.startswith("```"):
        lines = (
            text
            .splitlines()
        )

        if (
            lines
            and lines[0].startswith("```")
        ):
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        text = (
            "\n"
            .join(lines)
            .strip()
        )

    start = (
        text
        .find("{")
    )

    end = (
        text
        .rfind("}")
    )

    if (
        start != -1
        and end != -1
        and end > start
    ):
        text = text[
            start:end + 1
        ]

    data = json.loads(
        text
    )

    return GroundedResponse.model_validate(
        data
    )


@dataclass
class RAGAnswer:

    answer: str

    supported: bool

    sources: list[str]

    retrieved_chunks: list[dict]


class RAGService:

    def __init__(
        self,
        *,
        primary_model: ChatOpenAI,
        fallback_model: ChatOpenAI | None = None,
        primary_model_name: str = "unknown",
        fallback_model_name: str | None = None,
        primary_timeout_seconds: float = 3.0,
        fallback_timeout_seconds: float = 8.0,
        minimum_score: float = 0.35,
    ) -> None:

        self.primary_model = (
            primary_model
        )

        self.fallback_model = (
            fallback_model
        )

        self.primary_model_name = (
            primary_model_name
        )

        self.fallback_model_name = (
            fallback_model_name
        )

        self.primary_timeout_seconds = (
            primary_timeout_seconds
        )

        self.fallback_timeout_seconds = (
            fallback_timeout_seconds
        )

        self.minimum_score = (
            minimum_score
        )

    async def answer(
        self,
        *,
        tenant_id: str,
        query: str,
        language: str,
        limit: int = RAG_DEFAULT_LIMIT,
    ) -> RAGAnswer:

        total_started = (
            time.perf_counter()
        )

        retrieval_started = (
            time.perf_counter()
        )

        results = retrieve_chunks(
            tenant_id=tenant_id,
            query=query,
            limit=limit,
        )

        retrieval_ms = (
            time.perf_counter()
            - retrieval_started
        ) * 1000

        relevant = [
            item
            for item in results
            if item["score"] >= self.minimum_score
        ]

        logger.info(
            "rag_retrieval_timing "
            "tenant_id=%s "
            "retrieval_ms=%.2f "
            "retrieved_count=%d "
            "relevant_count=%d",
            tenant_id,
            retrieval_ms,
            len(results),
            len(relevant),
        )

        if not relevant:

            if language == "en":

                answer = (
                    "I couldn't find reliable information "
                    "about that in this provider's "
                    "knowledge base."
                )

            else:

                answer = (
                    "ملقتش معلومة موثوقة عن الموضوع ده "
                    "في معلومات المكان المتاحة عندي."
                )

            return RAGAnswer(
                answer=answer,
                supported=False,
                sources=[],
                retrieved_chunks=[],
            )

        context_blocks = []

        for index, item in enumerate(
            relevant,
            start=1,
        ):

            raw_content = str(
                item.get("content")
                or ""
            ).strip()

            if len(raw_content) > RAG_CONTEXT_CHARS:
                content = (
                    raw_content[:RAG_CONTEXT_CHARS]
                    .rstrip()
                    + "..."
                )
            else:
                content = raw_content

            context_blocks.append(
                (
                    f"[SOURCE {index}]\n"
                    f"Title: {item.get('title') or ''}\n"
                    f"Content:\n"
                    f"{content}"
                )
            )

        context = (
            "\n\n"
            .join(
                context_blocks
            )
        )

        if language == "en":

            language_instruction = (
                "Answer in natural English."
            )

        else:

            language_instruction = (
                "Answer in natural spoken Egyptian Arabic, "
                "as a polite clinic receptionist would speak on WhatsApp or voice. "
                "Use simple everyday wording, not formal Arabic. "
                "Do not sound like you are reading from a document. "
                "Do not say phrases like: according to the source, based on the context, "
                "the retrieved information says, or the knowledge base says. "
                "Paraphrase the facts naturally while keeping names, numbers, "
                "medical terms, prices, policies, and important details accurate."
            )

        system_prompt = f"""
You are the knowledge assistant for a healthcare provider.

Use ONLY the provided retrieved context.

Rules:
- Do not use outside knowledge.
- Do not invent missing information.
- If the context does not support the answer, say that the information is not available.
- Do not claim policies, prices, hours, services, or medical instructions unless they appear in the context.
- {language_instruction}
- Retrieval similarity alone does not mean the question is answered.
- source_indexes must contain ONLY the SOURCE numbers that directly support the answer.
- If the retrieved context directly answers the question, return the supporting SOURCE numbers.
- If the requested information is absent, return source_indexes=[] and clearly say that the information is not available.
- Return ONLY valid JSON with this exact shape: {{"answer": "...", "source_indexes": [1]}}.
- Do not wrap the JSON in markdown.
- Keep the answer concise and useful.

- The value of "answer" must be the final user-facing reply only.
- Do not mention SOURCE numbers in the answer.
- Do not quote the context unless the exact wording is needed.
- For Arabic replies, use Egyptian Arabic like: "أيوه"، "ممكن"، "مش متاح"، "تقدري"، "حضرتك".
- For voice/chat, prefer 1 to 2 short sentences.
- If the answer is about a policy or service, make it conversational and direct.
"""

        user_prompt = f"""
User question:

{query}

Retrieved context:

{context}
"""

        generation_started = (
            time.perf_counter()
        )

        used_model_name = (
            self.primary_model_name
        )

        fallback_used = False

        try:

            primary_response = await asyncio.wait_for(
                self.primary_model.ainvoke(
                    [
                        SystemMessage(
                            content=system_prompt,
                        ),
                        HumanMessage(
                            content=user_prompt,
                        ),
                    ]
                ),
                timeout=self.primary_timeout_seconds,
            )

            result = _parse_grounded_response(
                primary_response.content
            )

        except Exception as exc:

            if self.fallback_model is None:

                logger.warning(
                    "rag_primary_failed_no_fallback "
                    "primary_model=%s "
                    "error_type=%s "
                    "error_message=%s",
                    self.primary_model_name,
                    type(exc).__name__,
                    str(exc)[:1500],
                )

                if language == "en":

                    answer = (
                        "I couldn't answer that from the "
                        "provider knowledge base right now."
                    )

                else:

                    answer = (
                        "مش قادر أجاوب من معلومات المكان "
                        "حالياً."
                    )

                return RAGAnswer(
                    answer=answer,
                    supported=False,
                    sources=[],
                    retrieved_chunks=relevant,
                )

            logger.warning(
                "rag_primary_failed "
                "primary_model=%s "
                "fallback_model=%s "
                "error_type=%s "
                "error_message=%s",
                self.primary_model_name,
                self.fallback_model_name,
                type(exc).__name__,
                str(exc)[:1500],
            )
            fallback_used = True

            used_model_name = (
                self.fallback_model_name
                or "fallback"
            )

            try:

                structured_model = (
                    self.fallback_model
                    .with_structured_output(
                        GroundedResponse,
                        method="json_schema",
                        strict=True,
                    )
                )

                result = await asyncio.wait_for(
                    structured_model.ainvoke(
                        [
                            SystemMessage(
                                content=system_prompt,
                            ),
                            HumanMessage(
                                content=user_prompt,
                            ),
                        ]
                    ),
                    timeout=self.fallback_timeout_seconds,
                )

            except Exception as fallback_exc:

                logger.warning(
                    "rag_fallback_failed "
                    "primary_model=%s "
                    "fallback_model=%s "
                    "error_type=%s",
                    self.primary_model_name,
                    self.fallback_model_name,
                    type(fallback_exc).__name__,
                )

                if language == "en":

                    answer = (
                        "I couldn't answer that from the "
                        "provider knowledge base right now."
                    )

                else:

                    answer = (
                        "مش قادر أجاوب من معلومات المكان "
                        "حالياً."
                    )

                return RAGAnswer(
                    answer=answer,
                    supported=False,
                    sources=[],
                    retrieved_chunks=relevant,
                )

        generation_ms = (
            time.perf_counter()
            - generation_started
        ) * 1000

        total_ms = (
            time.perf_counter()
            - total_started
        ) * 1000

        logger.info(
            "rag_generation_timing "
            "tenant_id=%s "
            "model=%s "
            "fallback_used=%s "
            "generation_ms=%.2f "
            "total_ms=%.2f "
            "retrieved_count=%d "
            "relevant_count=%d",
            tenant_id,
            used_model_name,
            fallback_used,
            generation_ms,
            total_ms,
            len(results),
            len(relevant),
        )

        valid_indexes = list(
            dict.fromkeys(
                index
                for index in result.source_indexes
                if 1 <= index <= len(relevant)
            )
        )

        if not valid_indexes:

            if language == "en":

                fallback_answer = (
                    "I couldn't find that information "
                    "in this provider's knowledge base."
                )

            else:

                fallback_answer = (
                    "المعلومة دي مش متوفرة "
                    "في معلومات المكان اللي عندي."
                )

            return RAGAnswer(
                answer=fallback_answer,
                supported=False,
                sources=[],
                retrieved_chunks=relevant,
            )

        supporting_chunks = [
            relevant[index - 1]
            for index in valid_indexes
        ]

        sources = list(
            dict.fromkeys(
                item["source_url"]
                for item in supporting_chunks
                if item.get("source_url")
            )
        )

        return RAGAnswer(
            answer=result.answer.strip(),
            supported=True,
            sources=sources,
            retrieved_chunks=supporting_chunks,
        )

def create_rag_service() -> RAGService:

    load_dotenv()

    primary_model_name = os.getenv(
        "RAG_PRIMARY_MODEL",
        os.getenv(
            "QWEN_PLANNER_MODEL",
            os.getenv(
                "PLANNER_MODEL",
                "qwen/qwen3.8-27b",
            ),
        ),
    )

    fallback_model_name = (
        os.getenv(
            "RAG_FALLBACK_MODEL",
            "gpt-4.1",
        )
        .strip()
    )

    qwen_base_url = (
        os.getenv(
            "RAG_PRIMARY_BASE_URL",
            os.getenv(
                "QWEN_BASE_URL",
                "https://api.groq.com/openai/v1",
            ),
        )
        .strip()
    )

    qwen_api_key = (
        os.getenv(
            "RAG_PRIMARY_API_KEY",
            os.getenv(
                "GROQ_API_KEY",
                "",
            ),
        )
        .strip()
    )

    primary_timeout_seconds = float(
        os.getenv(
            "RAG_PRIMARY_TIMEOUT_SECONDS",
            "3",
        )
    )

    fallback_timeout_seconds = float(
        os.getenv(
            "RAG_FALLBACK_TIMEOUT_SECONDS",
            "8",
        )
    )

    primary_model = ChatOpenAI(
        model=primary_model_name,
        openai_api_base=qwen_base_url,
        openai_api_key=qwen_api_key,
        temperature=0,
        timeout=primary_timeout_seconds,
    )

    fallback_model = None

    if fallback_model_name:

        fallback_model = ChatOpenAI(
            model=fallback_model_name,
            temperature=0,
            timeout=fallback_timeout_seconds,
        )

    logger.info(
        "rag_service_created "
        "primary_model=%s "
        "primary_base_url=%s "
        "primary_api_key_present=%s "
        "fallback_model=%s "
        "primary_timeout_seconds=%.2f "
        "fallback_timeout_seconds=%.2f",
        primary_model_name,
        qwen_base_url,
        bool(qwen_api_key),
        fallback_model_name or None,
        primary_timeout_seconds,
        fallback_timeout_seconds,
    )

    return RAGService(
        primary_model=primary_model,
        fallback_model=fallback_model,
        primary_model_name=primary_model_name,
        fallback_model_name=(
            fallback_model_name
            or None
        ),
        primary_timeout_seconds=primary_timeout_seconds,
        fallback_timeout_seconds=fallback_timeout_seconds,
    )