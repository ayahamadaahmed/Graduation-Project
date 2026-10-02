from __future__ import annotations

from sqlalchemy import text

from app.db.session import SessionLocal


TENANT_KEY = "clinic-001"


SERVICE_ARABIC_NAMES = {
    "SKIN_CONSULT":
        "كشف جلدية",

    "ACNE_SCARS":
        "علاج حب الشباب وآثاره",

    "MELASMA_PIGMENTATION":
        "علاج الكلف والتصبغات",

    "HAIR_LOSS":
        "فحص وعلاج تساقط الشعر",

    "LASER_HAIR_REMOVAL":
        "إزالة الشعر بالليزر",

    "CHEMICAL_PEELS_FACIALS":
        "التقشير الكيميائي والعناية بالبشرة",

    "BOTOX_FILLERS":
        "البوتوكس والفيلر",

    "SKIN_CANCER_SCREENING":
        "فحص سرطان الجلد",

    "ECZEMA_PSORIASIS":
        "علاج الإكزيما والصدفية",

    "GENITAL_DERMATOLOGY":
        "الأمراض الجلدية التناسلية",
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

        for code, name_ar in (
            SERVICE_ARABIC_NAMES.items()
        ):

            result = session.execute(
                text(
                    """
                    UPDATE dbo.services
                    SET name_ar = :name_ar
                    WHERE provider_id = :provider_id
                      AND code = :code;
                    """
                ),
                {
                    "provider_id": provider_id,
                    "code": code,
                    "name_ar": name_ar,
                },
            )

            if result.rowcount != 1:
                raise RuntimeError(
                    f"{code}: expected 1 row, "
                    f"updated {result.rowcount}"
                )

            print(
                f"Updated {code}: {name_ar}"
            )

        session.commit()

        print(
            "\nArabic service names repaired."
        )


if __name__ == "__main__":
    main()