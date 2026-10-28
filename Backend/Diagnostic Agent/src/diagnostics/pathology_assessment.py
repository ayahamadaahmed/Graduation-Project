from __future__ import annotations

from dataclasses import dataclass, field

from src.diagnostics.lab_types import (
    LabFinding,
    LabFlag,
)

from src.diagnostics.pathology_processor import (
    PathologyProcessorResult,
)


@dataclass
class PathologyAssessment:
    detected_panels: list[str] = field(
        default_factory=list
    )

    abnormal_findings: list[LabFinding] = field(
        default_factory=list
    )

    normal_findings: list[LabFinding] = field(
        default_factory=list
    )

    unknown_findings: list[LabFinding] = field(
        default_factory=list
    )

    skipped_unreadable: list[str] = field(
        default_factory=list
    )

    unmapped_tests: list[str] = field(
        default_factory=list
    )


class PathologyAssessmentBuilder:
    """
    Combines all pathology engine outputs
    into one deterministic result.

    No diagnosis.
    No LLM interpretation.
    """

    PANEL_NAMES = (
        "cbc",
        "glycemic",
        "renal",
        "liver",
        "lipid",
    )

    def build(
        self,
        processing: PathologyProcessorResult,
    ) -> PathologyAssessment:

        assessment = PathologyAssessment(
            detected_panels=list(
                processing.detected_panels
            ),
            skipped_unreadable=list(
                processing.skipped_unreadable
            ),
            unmapped_tests=list(
                processing.unmapped_tests
            ),
        )

        for panel_name in self.PANEL_NAMES:

            analysis = getattr(
                processing,
                panel_name,
            )

            if analysis is None:
                continue

            for finding in analysis.findings:

                if finding.flag in {
                    LabFlag.LOW,
                    LabFlag.HIGH,
                }:
                    assessment.abnormal_findings.append(
                        finding
                    )

                elif finding.flag == LabFlag.NORMAL:
                    assessment.normal_findings.append(
                        finding
                    )

                else:
                    assessment.unknown_findings.append(
                        finding
                    )

        for finding in processing.additional_findings:
            if finding.flag in {LabFlag.LOW, LabFlag.HIGH}:
                assessment.abnormal_findings.append(finding)
            elif finding.flag == LabFlag.NORMAL:
                assessment.normal_findings.append(finding)
            else:
                assessment.unknown_findings.append(finding)

        return assessment
