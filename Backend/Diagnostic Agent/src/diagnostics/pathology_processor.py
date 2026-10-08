from __future__ import annotations

from dataclasses import dataclass, field

from src.diagnostics.cbc_engine import (
    CBCAnalysisResult,
    CBCAnalyzer,
)
from src.diagnostics.cbc_normalizer import (
    normalize_cbc_results,
)

from src.diagnostics.glycemic_engine import (
    GlycemicAnalysisResult,
    GlycemicAnalyzer,
)
from src.diagnostics.glycemic_normalizer import (
    normalize_glycemic_results,
)

from src.diagnostics.liver_engine import (
    LiverAnalysisResult,
    LiverAnalyzer,
)
from src.diagnostics.liver_normalizer import (
    normalize_liver_results,
)

from src.diagnostics.lipid_engine import (
    LipidAnalysisResult,
    LipidAnalyzer,
)
from src.diagnostics.lipid_normalizer import (
    normalize_lipid_results,
)

from src.diagnostics.renal_engine import (
    RenalAnalysisResult,
    RenalAnalyzer,
)
from src.diagnostics.renal_normalizer import (
    normalize_renal_results,
)

from src.diagnostics.lab_image_extractor import (
    ExtractedLabReport,
)
from src.diagnostics.lab_types import (
    LabValue,
)

@dataclass(frozen=True)
class PathologyValueTrace:
    raw_name: str
    panel: str | None
    canonical_name: str | None
    value: float | None
    unit: str | None
    reference_min: float | None
    reference_max: float | None
    reference_text: str | None

    # low / normal / high / unknown
    flag: str

    # mapped / unreadable / unmapped
    mapping_status: str

@dataclass
class PathologyProcessorResult:
    cbc: CBCAnalysisResult | None = None
    glycemic: GlycemicAnalysisResult | None = None
    renal: RenalAnalysisResult | None = None
    liver: LiverAnalysisResult | None = None
    lipid: LipidAnalysisResult | None = None

    detected_panels: list[str] = field(
        default_factory=list
    )

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    unmapped_tests: list[str] = field(
        default_factory=list
    )

    value_traces: list[
        PathologyValueTrace
    ] = field(
        default_factory=list
    )


class PathologyProcessor:
    """
    Deterministic pathology orchestration layer.

    Responsibilities:
    - accept one structured lab report
    - detect which analyzers are relevant
    - send each recognized test to the correct analyzer
    - preserve unreadable/unmapped tests

    This is NOT the conversational Pathology Agent.
    """

    def __init__(self):
        self.cbc_analyzer = CBCAnalyzer()
        self.glycemic_analyzer = GlycemicAnalyzer()
        self.renal_analyzer = RenalAnalyzer()
        self.liver_analyzer = LiverAnalyzer()
        self.lipid_analyzer = LipidAnalyzer()

    def process(
        self,
        report: ExtractedLabReport,
    ) -> PathologyProcessorResult:

        result = PathologyProcessorResult()

        recognized_raw_names: set[str] = set()

        cbc_values = normalize_cbc_results(
            report.results
        )
        glycemic_values = normalize_glycemic_results(
            report.results
        )
        renal_values = normalize_renal_results(
            report.results
        )
        liver_values = normalize_liver_results(
            report.results
        )
        lipid_values = normalize_lipid_results(
            report.results
        )

        groups = [
            (
                "cbc",
                cbc_values,
                self.cbc_analyzer,
            ),
            (
                "glycemic",
                glycemic_values,
                self.glycemic_analyzer,
            ),
            (
                "renal",
                renal_values,
                self.renal_analyzer,
            ),
            (
                "liver",
                liver_values,
                self.liver_analyzer,
            ),
            (
                "lipid",
                lipid_values,
                self.lipid_analyzer,
            ),
        ]

        for (
            panel_name,
            normalized_values,
            analyzer,
        ) in groups:

            if not normalized_values:
                continue

            analyzer_values: list[LabValue] = []

            readable_items = []

            for item in normalized_values:

                recognized_raw_names.add(
                    item.raw_name
                )

                if item.value is None:

                    result.value_traces.append(
                        PathologyValueTrace(
                            raw_name=item.raw_name,
                            panel=panel_name,
                            canonical_name=item.name,
                            value=None,
                            unit=item.unit,
                            reference_min=(
                                item.reference_min
                            ),
                            reference_max=(
                                item.reference_max
                            ),
                            reference_text=(
                                item.reference_text
                            ),
                            flag="unknown",
                            mapping_status="unreadable",
                        )
                    )

                    result.skipped_unreadable.append(
                        item.raw_name
                    )

                    continue

                readable_items.append(
                    item
                )

                analyzer_values.append(
                    LabValue(
                        name=item.name,
                        value=item.value,
                        unit=item.unit or "",
                        reference_min=(
                            item.reference_min
                        ),
                        reference_max=(
                            item.reference_max
                        ),
                    )
                )

            if not analyzer_values:
                continue

            analysis = analyzer.analyze(
                analyzer_values
            )

            if (
                len(analysis.findings)
                != len(readable_items)
            ):
                raise RuntimeError(
                    f"{panel_name} analyzer returned "
                    "an unexpected number of findings."
                )

            for item, finding in zip(
                readable_items,
                analysis.findings,
                strict=True,
            ):

                if finding.name != item.name:
                    raise RuntimeError(
                        f"{panel_name} analyzer finding "
                        "order does not match normalized values."
                    )

                result.value_traces.append(
                    PathologyValueTrace(
                        raw_name=item.raw_name,
                        panel=panel_name,
                        canonical_name=item.name,
                        value=item.value,
                        unit=item.unit,
                        reference_min=(
                            item.reference_min
                        ),
                        reference_max=(
                            item.reference_max
                        ),
                        reference_text=(
                            item.reference_text
                        ),
                        flag=finding.flag.value,
                        mapping_status="mapped",
                    )
                )

            setattr(
                result,
                panel_name,
                analysis,
            )

            result.detected_panels.append(
                panel_name
            )

        unmapped_values = [
            item
            for item in report.results
            if item.raw_name
            not in recognized_raw_names
        ]

        result.unmapped_tests = [
            item.raw_name
            for item in unmapped_values
        ]

        for item in unmapped_values:

            result.value_traces.append(
                PathologyValueTrace(
                    raw_name=item.raw_name,
                    panel=None,
                    canonical_name=None,
                    value=item.value,
                    unit=item.unit,
                    reference_min=(
                        item.reference_min
                    ),
                    reference_max=(
                        item.reference_max
                    ),
                    reference_text=(
                        item.reference_text
                    ),
                    flag="unknown",
                    mapping_status="unmapped",
                )
            )

        result.skipped_unreadable = list(
            dict.fromkeys(
                result.skipped_unreadable
            )
        )

        return result