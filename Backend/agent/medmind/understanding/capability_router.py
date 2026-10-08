from __future__ import annotations

import logging
import os
import time

from dataclasses import dataclass

import torch

from sentence_transformers import (
    SentenceTransformer,
    util,
)

from medmind.understanding.capabilities import (
    CAPABILITIES,
    CapabilityDefinition,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "uvicorn.error"
)


# ============================================================
# MODEL
# ============================================================

DEFAULT_MODEL_NAME = (
    "Omartificial-Intelligence-Space/"
    "GATE-AraBert-v1"
)


# ============================================================
# RESULT TYPES
# ============================================================

@dataclass(frozen=True)
class CapabilityMatch:

    name: str

    domain: str

    score: float

    matched_text: str


@dataclass(frozen=True)
class _CapabilityAnchor:

    capability: CapabilityDefinition

    text: str


# ============================================================
# SEMANTIC CAPABILITY ROUTER
# ============================================================

class SemanticCapabilityRouter:

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
    ) -> None:

        router_started = (
            time.perf_counter()
        )

        step_started = (
            time.perf_counter()
        )

        requested_device = (
            device
        )

        if requested_device is None:

            requested_device = (
                os.getenv(
                    "SEMANTIC_ROUTER_DEVICE",
                    "auto",
                )
                .strip()
                .lower()
            )

        if requested_device == "auto":

            resolved_device = (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )

        elif requested_device == "cpu":

            resolved_device = (
                "cpu"
            )

        elif requested_device == "cuda":

            if not torch.cuda.is_available():

                logger.warning(
                    "semantic_router_cuda_unavailable "
                    "falling_back_to_cpu=True"
                )

                resolved_device = (
                    "cpu"
                )

            else:

                resolved_device = (
                    "cuda"
                )

        else:

            raise ValueError(
                "SEMANTIC_ROUTER_DEVICE must be "
                "'auto', 'cpu', or 'cuda'."
            )

        device_resolution_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        self.device = (
            resolved_device
        )

        device = (
            resolved_device
        )

        self.model_name = model_name

        # ====================================================
        # SENTENCE TRANSFORMER MODEL LOAD
        #
        # This includes model/tokenizer/config initialization.
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        self.model = (
            SentenceTransformer(
                model_name,
                device=device,
            )
        )

        model_load_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # BUILD SEMANTIC ANCHORS
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        self._anchors = (
            self._build_anchors()
        )

        anchor_build_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        if not self._anchors:

            raise RuntimeError(
                "No capability anchors were created."
            )

        # ====================================================
        # PREPARE ANCHOR TEXT
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        anchor_texts = [
            anchor.text
            for anchor in self._anchors
        ]

        anchor_prepare_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # ENCODE CAPABILITY ANCHORS
        #
        # Done once per router instance.
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        self._anchor_embeddings = (
            self.model.encode(
                anchor_texts,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )

        anchor_encode_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # TOTAL
        # ====================================================

        total_ms = (
            time.perf_counter()
            - router_started
        ) * 1000

        logger.info(
            "semantic_router_init_timing "
            "device=%s "
            "device_resolution_ms=%.2f "
            "model_load_ms=%.2f "
            "anchor_count=%s "
            "anchor_build_ms=%.2f "
            "anchor_prepare_ms=%.2f "
            "anchor_encode_ms=%.2f "
            "total_ms=%.2f",
            self.device,
            device_resolution_ms,
            model_load_ms,
            len(self._anchors),
            anchor_build_ms,
            anchor_prepare_ms,
            anchor_encode_ms,
            total_ms,
        )

    # ========================================================
    # BUILD SEMANTIC ANCHORS
    # ========================================================

    def _build_anchors(
        self,
    ) -> list[_CapabilityAnchor]:

        anchors: list[
            _CapabilityAnchor
        ] = []

        for capability in CAPABILITIES:

            # -----------------------------------------------
            # Arabic description
            # -----------------------------------------------

            description_ar = (
                capability
                .description_ar
                .strip()
            )

            if description_ar:

                anchors.append(
                    _CapabilityAnchor(
                        capability=capability,
                        text=description_ar,
                    )
                )

            # -----------------------------------------------
            # Arabic examples
            # -----------------------------------------------

            for example in (
                capability.examples_ar
            ):

                cleaned = (
                    example.strip()
                )

                if not cleaned:
                    continue

                anchors.append(
                    _CapabilityAnchor(
                        capability=capability,
                        text=cleaned,
                    )
                )

            # -----------------------------------------------
            # English description
            # -----------------------------------------------

            description_en = (
                capability
                .description_en
                .strip()
            )

            if description_en:

                anchors.append(
                    _CapabilityAnchor(
                        capability=capability,
                        text=description_en,
                    )
                )

            # -----------------------------------------------
            # English examples
            # -----------------------------------------------

            for example in (
                capability.examples_en
            ):

                cleaned = (
                    example.strip()
                )

                if not cleaned:
                    continue

                anchors.append(
                    _CapabilityAnchor(
                        capability=capability,
                        text=cleaned,
                    )
                )

        return anchors

    # ========================================================
    # ROUTE
    # ========================================================

    def route(
        self,
        message: str,
        *,
        top_k: int = 5,
        allowed_capabilities: (
            set[str]
            | frozenset[str]
            | None
        ) = None,
    ) -> list[CapabilityMatch]:

        route_started = (
            time.perf_counter()
        )

        cleaned_message = (
            message.strip()
        )

        if not cleaned_message:
            return []

        if top_k <= 0:

            raise ValueError(
                "top_k must be greater than zero."
            )

        # ====================================================
        # ENCODE CURRENT MESSAGE
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        query_embedding = (
            self.model.encode(
                cleaned_message,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )

        query_encode_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # COSINE SIMILARITY
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        similarities = (
            util.cos_sim(
                query_embedding,
                self._anchor_embeddings,
            )[0]
        )

        cosine_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # BEST ANCHOR PER CAPABILITY
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        best_by_capability: dict[
            str,
            CapabilityMatch,
        ] = {}

        for index, similarity in enumerate(
            similarities
        ):

            anchor = (
                self._anchors[index]
            )

            capability = (
                anchor.capability
            )

            if (
                allowed_capabilities is not None
                and capability.name
                not in allowed_capabilities
            ):
                continue

            score = float(
                similarity.item()
            )

            current = (
                best_by_capability.get(
                    capability.name
                )
            )

            if (
                current is None
                or score > current.score
            ):

                best_by_capability[
                    capability.name
                ] = CapabilityMatch(
                    name=capability.name,
                    domain=capability.domain,
                    score=score,
                    matched_text=anchor.text,
                )

        reduce_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # SORT / TOP-K
        # ====================================================

        step_started = (
            time.perf_counter()
        )

        ranked = sorted(
            best_by_capability.values(),
            key=lambda item: item.score,
            reverse=True,
        )

        effective_top_k = min(
            top_k,
            len(ranked),
        )

        result = ranked[
            :effective_top_k
        ]

        rank_ms = (
            time.perf_counter()
            - step_started
        ) * 1000

        # ====================================================
        # ROUTE TOTAL
        #
        # No message text or matched anchor text is logged.
        # ====================================================

        total_ms = (
            time.perf_counter()
            - route_started
        ) * 1000

        logger.info(
            "semantic_router_route_timing "
            "router_id=%s "
            "model_id=%s "
            "device=%s "
            "query_encode_ms=%.2f "
            "cosine_ms=%.2f "
            "reduce_ms=%.2f "
            "rank_ms=%.2f "
            "anchor_count=%s "
            "result_count=%s "
            "total_ms=%.2f",
            id(self),
            id(self.model),
            self.device,
            query_encode_ms,
            cosine_ms,
            reduce_ms,
            rank_ms,
            len(self._anchor_embeddings),
            len(result),
            total_ms,
        )

        return result