from __future__ import annotations

from sqlalchemy import text

from app.db.session import SessionLocal


TENANT_KEY = "clinic-001"


VOICE_SERVICE_PRESENTATION = {
    "SKIN_CONSULT": {
        "label_ar": "كشف جلدية",
        "label_en": "Dermatology consultation",
        "rank": 1,
    },
    "HAIR_LOSS": {
        "label_ar": "تساقط الشعر",
        "label_en": "Hair loss",
        "rank": 2,
    },
    "SKIN_CANCER_SCREENING": {
        "label_ar": "سرطان الجلد",
        "label_en": "Skin cancer screening",
        "rank": 3,
    },
    "ECZEMA_PSORIASIS": {
        "label_ar": "الإكزيما والصدفية",
        "label_en": "Eczema and psoriasis",
        "rank": 4,
    },
}


def main() -> None:

    with SessionLocal() as session:

        provider_id = session.execute(
            text(
                """
                SELECT id
                FROM dbo.providers
                WHERE tenant_key = :tenant_key
                  AND is_active = 1;
                """
            ),
            {
                "tenant_key": TENANT_KEY,
            },
        ).scalar_one()

        print(
            f"Provider: {provider_id}"
        )

        # Reconcile the provider configuration so rerunning
        # this script always produces the same final state.
        session.execute(
            text(
                """
                UPDATE dbo.services
                SET
                    voice_label_ar = NULL,
                    voice_label_en = NULL,
                    voice_featured_rank = NULL
                WHERE provider_id = :provider_id;
                """
            ),
            {
                "provider_id": provider_id,
            },
        )

        for code, config in (
            VOICE_SERVICE_PRESENTATION.items()
        ):

            result = session.execute(
                text(
                    """
                    UPDATE dbo.services
                    SET
                        voice_label_ar = :voice_label_ar,
                        voice_label_en = :voice_label_en,
                        voice_featured_rank = :voice_featured_rank
                    WHERE provider_id = :provider_id
                      AND code = :code
                      AND is_active = 1;
                    """
                ),
                {
                    "provider_id": provider_id,
                    "code": code,
                    "voice_label_ar": config["label_ar"],
                    "voice_label_en": config["label_en"],
                    "voice_featured_rank": config["rank"],
                },
            )

            if result.rowcount != 1:
                raise RuntimeError(
                    f"{code}: expected 1 active service, "
                    f"updated {result.rowcount}"
                )

            print(
                f"Configured {code} "
                f"rank={config['rank']}"
            )

        session.commit()

        print(
            "\nVoice service presentation configured."
        )


if __name__ == "__main__":
    main()