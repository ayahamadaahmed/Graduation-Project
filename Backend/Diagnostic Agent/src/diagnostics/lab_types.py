from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LabFlag(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LabValue:
    name: str
    value: float
    unit: str

    reference_min: float | None = None
    reference_max: float | None = None

    def flag(self) -> LabFlag:
        if (
            self.reference_min is None
            and self.reference_max is None
        ):
            return LabFlag.UNKNOWN

        if (
            self.reference_min is not None
            and self.value < self.reference_min
        ):
            return LabFlag.LOW

        if (
            self.reference_max is not None
            and self.value > self.reference_max
        ):
            return LabFlag.HIGH

        return LabFlag.NORMAL


@dataclass(frozen=True)
class LabFinding:
    name: str
    value: float
    unit: str
    flag: LabFlag

    reference_min: float | None
    reference_max: float | None