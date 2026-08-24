from __future__ import annotations

import os

from dataclasses import (
    dataclass,
)

from dotenv import (
    load_dotenv,
)

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langchain_openai import (
    ChatOpenAI,
)

from rag.retriever import (
    retrieve_chunks,
)


from pydantic import (
    BaseModel,
    Field,
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
        model: ChatOpenAI,
        minimum_score: float = 0.35,
    ) -> None:

        self.model = model

        self.minimum_score = (
            minimum_score
        )

    async def answer(
        self,
        *,
        tenant_id: str,
        query: str,
        language: str,
        limit: int = 3,
    ) -> RAGAnswer:

        results = retrieve_chunks(
            tenant_id=
                tenant_id,

            query=
                query,

            limit=
                limit,
        )

        relevant = [
            item
            for item in results
            if item["score"]
            >= self.minimum_score
        ]

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

            context_blocks.append(
                (
                    f"[SOURCE {index}]\n"
                    f"Title: {item['title']}\n"
                    f"Content:\n"
                    f"{item['content']}"
                )
            )

        context = (
            "\n\n".join(
                context_blocks
            )
        )

        if language == "en":

            language_instruction = (
                "Answer in natural English."
            )

        else:

            language_instruction = (
                "Answer in natural Egyptian Arabic. "
                "Do not translate mechanically. "
                "Keep names, numbers, medical terms, "
                "and important factual details accurate."
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

- Keep the answer concise and useful.
"""

        user_prompt = f"""
User question:

{query}

Retrieved context:

{context}
"""

        structured_model = (
            self.model.with_structured_output(
                GroundedResponse,
                method="json_schema",
                strict=True,
            )
        )

        result = await (
            structured_model.ainvoke(
                [
                    SystemMessage(
                        content=system_prompt,
                    ),
                    HumanMessage(
                        content=user_prompt,
                    ),
                ]
            )
        )

        valid_indexes = list(
            dict.fromkeys(
                index
                for index in result.source_indexes
                if 1 <= index <= len(relevant)
            )
        )

        # No directly supporting source
        # means the answer is unsupported.
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

    model = ChatOpenAI(
        model=os.getenv(
            "OPENAI_MODEL",
            "gpt-4.1",
        ),

        temperature=0,
    )

    return RAGService(
        model=
            model,
    )