from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
)
from src.diagnostics.pathology_processor import (
    PathologyProcessorResult,
    PathologyValueTrace,
)


class PathologyPersistenceContractError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class PathologyPersistenceResult:
    schema_version: str

    document_type: str | None

    unreadable_fields: list[str]

    results: list[dict]


class PathologyPersistenceContractBuilder:
    """
    Converts trusted deterministic pathology output
    into a JSON-safe persistence contract.

    Responsibilities:
    - preserve original report result order
    - preserve raw extracted values
    - preserve normalized names/panels
    - preserve analyzer-produced flags
    - do NOT normalize again
    - do NOT recalculate flags
    - do NOT diagnose
    """

    SCHEMA_VERSION = "1.0"

    def build(
        self,
        *,
        report: ExtractedLabReport,
        processing: PathologyProcessorResult,
    ) -> PathologyPersistenceResult:

        # ----------------------------------------------------
        # Group traces by raw name while preserving the order
        # in which each trace appeared.
        #
        # deque is important because the same raw test name
        # may appear more than once in a report.
        # ----------------------------------------------------

        traces_by_raw_name: dict[
            str,
            deque[PathologyValueTrace],
        ] = defaultdict(deque)

        for trace in processing.value_traces:

            traces_by_raw_name[
                trace.raw_name
            ].append(
                trace
            )

        persistence_results: list[dict] = []

        # ----------------------------------------------------
        # report.results is the source of truth for original
        # report ordering.
        # ----------------------------------------------------

        for (
            result_index,
            extracted,
        ) in enumerate(
            report.results
        ):

            matching_traces = (
                traces_by_raw_name.get(
                    extracted.raw_name
                )
            )

            if not matching_traces:

                raise (
                    PathologyPersistenceContractError(
                        "Missing pathology trace for "
                        f"extracted result: "
                        f"{extracted.raw_name}"
                    )
                )

            trace = matching_traces.popleft()

            persistence_results.append(
                {
                    "result_index": (
                        result_index
                    ),
                    "panel": trace.panel,
                    "raw_name": (
                        trace.raw_name
                    ),
                    "canonical_name": (
                        trace.canonical_name
                    ),
                    "value": trace.value,
                    "unit": trace.unit,
                    "reference_min": (
                        trace.reference_min
                    ),
                    "reference_max": (
                        trace.reference_max
                    ),
                    "reference_text": (
                        trace.reference_text
                    ),
                    "flag": trace.flag,
                    "mapping_status": (
                        trace.mapping_status
                    ),
                }
            )

        # ----------------------------------------------------
        # Every trace must have been consumed exactly once.
        # Extra traces would indicate a processor/contract bug.
        # ----------------------------------------------------

        remaining = [
            trace
            for queue
            in traces_by_raw_name.values()
            for trace in queue
        ]

        if remaining:

            raise PathologyPersistenceContractError(
                "Pathology processing produced "
                "unmatched persistence traces."
            )

        return PathologyPersistenceResult(
            schema_version=(
                self.SCHEMA_VERSION
            ),
            document_type=(
                report.document_type
            ),
            unreadable_fields=list(
                report.unreadable_fields
            ),
            results=persistence_results,
        )