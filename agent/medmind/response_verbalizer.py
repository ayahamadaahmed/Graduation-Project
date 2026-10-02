from __future__ import annotations

import asyncio
import logging
import time

from groq import AsyncGroq


logger = logging.getLogger(
    "uvicorn.error"
)


class QwenResponseVerbalizer:
    """
    Convert trusted structured provider facts into
    short natural spoken responses.

    This component MUST NOT retrieve data or make
    medical decisions. It only verbalizes facts
    supplied by the caller.
    """

    def __init__(
        self,
        *,
        client: AsyncGroq,
        model: str,
        service_tier: str,
        timeout_seconds: float = 0.8,
        max_tokens: int = 100,
    ) -> None:

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero."
            )

        if max_tokens <= 0:
            raise ValueError(
                "max_tokens must be greater than zero."
            )

        self.client = client
        self.model = model
        self.service_tier = service_tier
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens

    async def verbalize_services(
        self,
        *,
        service_names: list[str],
        language: str,
        has_more: bool,
    ) -> str | None:

        names = [
            name.strip()
            for name in service_names
            if isinstance(name, str)
            and name.strip()
        ]

        if not names:
            return None

        language_name = (
            "English"
            if language == "en"
            else "Egyptian Arabic"
        )

        services_text = "\n".join(
            f"- {name}"
            for name in names
        )

        prompt = f"""
Create ONE short, natural spoken response for a healthcare
receptionist in {language_name}.

Trusted services:
{services_text}

Other services exist: {"yes" if has_more else "no"}

Rules:
- Use only the trusted services above as medical facts.
- Speak naturally like a receptionist in a phone conversation.
- Do not use a fixed sentence template.
- You may connect or grammatically rephrase service labels,
  but the medical meaning must remain exactly the same.
- Do NOT add descriptive words or qualifiers that are not supplied,
  such as comprehensive, advanced, specialized, complete, or premium.
- Do not invent, remove, merge, or upgrade any service.
- Mention every supplied service.
- Never change screening, examination, consultation, or evaluation
  into treatment.
- Do not use the word treatment unless the supplied service itself
  explicitly includes treatment.
- Do not diagnose or give medical advice.
- Do not start with a greeting.
- If other services exist, mention that naturally.
- Keep it to one concise spoken sentence.
- Return only the spoken response.
""".strip()

        started = time.perf_counter()

        try:

            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,

                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You only verbalize trusted "
                                "provider facts. Never add or "
                                "change medical meaning."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],

                    reasoning_effort="none",
                    service_tier=self.service_tier,
                    temperature=0.3,

                    max_completion_tokens=(
                        self.max_tokens
                    ),
                ),

                timeout=self.timeout_seconds,
            )

        except Exception as exc:

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            logger.warning(
                "response_verbalizer_failed "
                "elapsed_ms=%.2f "
                "error_type=%s",
                elapsed_ms,
                type(exc).__name__,
            )

            return None

        elapsed_ms = (
            time.perf_counter()
            - started
        ) * 1000

        content = (
            response
            .choices[0]
            .message
            .content
        )

        if not content:
            return None

        reply = " ".join(
            content.split()
        ).strip()

        if (
            not reply
            or len(reply) > 320
        ):
            return None

        logger.info(
            "response_verbalizer_timing "
            "model=%s "
            "elapsed_ms=%.2f",
            self.model,
            elapsed_ms,
        )

        return reply


    async def verbalize_service_details(
        self,
        *,
        service_name: str,
        price_text: str | None,
        service_type: str | None,
        language: str,
    ) -> str | None:

        clean_service_name = (
            service_name or ""
        ).strip()

        clean_price = (
            price_text or ""
        ).strip()

        clean_service_type = (
            service_type or ""
        ).strip()

        if not clean_service_name:
            return None

        language_name = (
            "English"
            if language == "en"
            else "Egyptian Arabic"
        )

        prompt = f"""
Create ONE short, natural spoken response for a healthcare
receptionist in {language_name}.

Trusted facts:
- Service name: {clean_service_name}
- Price: {clean_price}
- Service type: {clean_service_type}

Rules:
- Use only the trusted facts above.
- Do not invent any medical, booking, discount, or timing information.
- Do not diagnose or give medical advice.
- If a price exists, mention the exact number: {clean_price}
- Keep the price from the facts unchanged.
- Speak naturally like a phone receptionist.
- Do not use a fixed template.
- Vary the wording naturally.
- Keep it to one short sentence.
- Do not start with a greeting.
- Return only the spoken response.
""".strip()

        started = time.perf_counter()

        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You only verbalize trusted provider "
                                "facts. Never add or change prices, "
                                "medical meaning, or availability."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    reasoning_effort="none",
                    service_tier=self.service_tier,
                    temperature=0.6,
                    max_completion_tokens=(
                        self.max_tokens
                    ),
                ),
                timeout=self.timeout_seconds,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            logger.warning(
                "service_details_verbalizer_failed "
                "elapsed_ms=%.2f "
                "error_type=%s",
                elapsed_ms,
                type(exc).__name__,
            )

            return None

        content = (
            response
            .choices[0]
            .message
            .content
        )

        if not content:
            return None

        reply = " ".join(
            content.split()
        ).strip()

        if (
            not reply
            or len(reply) > 220
        ):
            return None

        if (
            clean_price
            and clean_price not in reply
        ):
            return None

        return reply