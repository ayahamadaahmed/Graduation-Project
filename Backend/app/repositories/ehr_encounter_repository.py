from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ehr_encounter import (
    EHREncounter,
)


class EHREncounterRepository:

    def __init__(
        self,
        session: Session,
    ) -> None:
        self.session = session

    def get_for_patient_provider(
        self,
        *,
        encounter_id: UUID,
        patient_id: UUID,
        provider_id: UUID,
    ) -> EHREncounter | None:

        statement = (
            select(EHREncounter)
            .where(
                EHREncounter.id
                == encounter_id,

                EHREncounter.patient_id
                == patient_id,

                EHREncounter.provider_id
                == provider_id,
            )
        )

        return self.session.scalar(
            statement
        )