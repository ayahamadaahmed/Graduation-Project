from __future__ import annotations

from typing import Any


class SafeDiagnosticExplanationService:
    """
    Convert trusted structured diagnostic output into
    patient-friendly text without making new medical decisions.

    Safety rules:
    - Never create a diagnosis.
    - Never change structured values.
    - Never recalculate flags or confidence.
    - Never suggest treatment.
    - Radiology classification remains model output.
    - Pathology uses analyzer-produced flags only.
    """

    _RADIOLOGY_LABELS_EN = {
        "brain_mri": "brain MRI",
        "chest_xray": "chest X-ray",
        "kidney_ct": "kidney CT",
    }

    _RADIOLOGY_LABELS_AR = {
        "brain_mri": "الرنين المغناطيسي للمخ",
        "chest_xray": "أشعة الصدر",
        "kidney_ct": "الأشعة المقطعية للكلى",
    }

    _FLAG_LABELS_EN = {
        "low": "low",
        "high": "high",
        "normal": "within the reference range",
        "unknown": "not evaluated",
    }

    _FLAG_LABELS_AR = {
        "low": "منخفض",
        "high": "مرتفع",
        "normal": "داخل النطاق المرجعي",
        "unknown": "غير محدد",
    }

    _LAB_LABELS_AR = {
        "hemoglobin": "الهيموجلوبين (بروتين ينقل الأكسجين)",
        "rbc": "عدد كرات الدم الحمراء",
        "hematocrit": "نسبة حجم كرات الدم الحمراء في الدم",
        "mcv": "متوسط حجم كرية الدم الحمراء",
        "mch": "متوسط كمية الهيموجلوبين في كرية الدم الحمراء",
        "mchc": "متوسط تركيز الهيموجلوبين في كرات الدم الحمراء",
        "rdw": "اختلاف أحجام كرات الدم الحمراء (RDW)",
        "rdw_cv": "اختلاف أحجام كرات الدم الحمراء (RDW-CV)",
        "rdw_sd": "اختلاف أحجام كرات الدم الحمراء (RDW-SD)",
        "wbc": "عدد كرات الدم البيضاء (خلايا الدفاع)",
        "platelets": "عدد الصفائح الدموية",
        "neutrophils_percent": "نسبة العدلات، وهي نوع من كرات الدم البيضاء",
        "neutrophils_absolute": "العدد المطلق للعدلات، وهي نوع من كرات الدم البيضاء",
        "lymphocytes_percent": "نسبة الخلايا الليمفاوية، وهي نوع من كرات الدم البيضاء",
        "lymphocytes_absolute": "العدد المطلق للخلايا الليمفاوية",
        "monocytes_percent": "نسبة الخلايا الوحيدة، وهي نوع من كرات الدم البيضاء",
        "monocytes_absolute": "العدد المطلق للخلايا الوحيدة",
        "eosinophils_percent": "نسبة الخلايا الحمضية، وهي نوع من كرات الدم البيضاء",
        "eosinophils_absolute": "العدد المطلق للخلايا الحمضية",
        "basophils_percent": "نسبة الخلايا القاعدية، وهي نوع من كرات الدم البيضاء",
        "basophils_absolute": "العدد المطلق للخلايا القاعدية",
        "esr": "سرعة ترسيب الدم",
        "vitamin_d_25oh": "فيتامين د (25-OH)",
        "vitamin_d2": "فيتامين د2",
        "vitamin_d3": "فيتامين د3",
        "vitamin_d_1_25oh2": "فيتامين د النشط (1,25-OH₂)",
        "ferritin": "الفيريتين (مخزون الحديد)",
        "serum_iron": "الحديد في الدم",
        "tibc": "السعة الكلية لارتباط الحديد (TIBC)",
        "transferrin_saturation": "نسبة تشبع الترانسفيرين بالحديد",
        "vitamin_b12": "فيتامين ب12",
        "folate": "الفولات (حمض الفوليك)",
        "reticulocyte_count": "عدد الخلايا الشبكية (كرات دم حمراء غير مكتملة النضج)",
    }

    _CLASSIFICATION_LABELS_AR = {
        "normal": "طبيعي",
        "pneumonia": "اشتباه التهاب رئوي",
        "pituitary": "فئة الغدة النخامية",
        "glioma": "فئة glioma",
        "meningioma": "فئة meningioma",
        "notumor": "لا يظهر ورم حسب تصنيف النموذج",
        "cyst": "كيس",
        "stone": "حصوة",
        "tumor": "ورم",
    }

    @staticmethod
    def _format_confidence_percent(
        confidence: object,
    ) -> str | None:

        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return None

        return f"{value * 100:.1f}%"

    def _classification_label_ar(
        self,
        classification: str,
    ) -> str:

        label = (
            self._CLASSIFICATION_LABELS_AR
            .get(
                classification,
            )
        )

        if label is None:
            return classification

        return f"{label} ({classification})"

    def explain_radiology(
        self,
        *,
        result: dict[str, Any],
        language: str,
    ) -> str:

        modality = str(
            result.get("modality") or ""
        ).strip()

        classification = str(
            result.get("classification") or ""
        ).strip()

        confidence = result.get("confidence")

        limitations = result.get("limitations")

        if not isinstance(limitations, list):
            limitations = []

        clean_limitations = [
            str(item).strip().rstrip(".")
            for item in limitations
            if str(item).strip()
        ]

        if language == "en":

            modality_label = (
                self._RADIOLOGY_LABELS_EN.get(
                    modality,
                    modality or "radiology image",
                )
            )

            if classification and confidence is not None:
                reply = (
                    f"For this {modality_label}, "
                    f"the AI model's screening output was "
                    f"'{classification}' with confidence score "
                    f"{confidence}. "
                    "This is a decision-support result, not a "
                    "confirmed diagnosis, and it should be reviewed "
                    "by a qualified clinician."
                )

            elif classification:
                reply = (
                    f"For this {modality_label}, "
                    f"the AI model's screening output was "
                    f"'{classification}'. "
                    "This is a decision-support result, not a "
                    "confirmed diagnosis, and it should be reviewed "
                    "by a qualified clinician."
                )

            else:
                reply = (
                    f"The {modality_label} was processed, but a "
                    "patient-facing classification could not be "
                    "reported safely. Please have the image reviewed "
                    "by a qualified clinician."
                )

            if clean_limitations:
                reply += (
                    " Model limitations: "
                    + "; ".join(clean_limitations)
                    + "."
                )

            return reply

        modality_label = (
            self._RADIOLOGY_LABELS_AR.get(
                modality,
                modality or "صورة الأشعة",
            )
        )

        if classification and confidence is not None:

            confidence_text = (
                self._format_confidence_percent(
                    confidence
                )
            )

            classification_text = (
                self._classification_label_ar(
                    classification
                )
            )

            if confidence_text is None:
                confidence_text = str(
                    confidence
                )

            reply = (
                f"بص، الموديل حلّل {modality_label} "
                f"وأقرب نتيجة طلعت عنده: "
                f"{classification_text}، "
                f"بنسبة ثقة تقريبًا: {confidence_text}. "
                "بس خلي بالك: دي قراءة مبدئية من AI "
                "بتساعد الدكتور، مش تشخيص نهائي "
                "ولا بديل للكشف. "
                "الدكتور لازم يراجع الصورة مع الأعراض "
                "والتاريخ المرضي قبل أي قرار."
            )

        elif classification:

            classification_text = (
                self._classification_label_ar(
                    classification
                )
            )

            reply = (
                f"بص، الموديل حلّل {modality_label} "
                f"وأقرب نتيجة طلعت عنده: "
                f"{classification_text}. "
                "بس دي قراءة مبدئية من AI "
                "بتساعد الدكتور، مش تشخيص نهائي "
                "ولا بديل للكشف."
            )

        else:
            reply = (
                f"تمت معالجة {modality_label}، "
                "بس مش قادرين نعرض تصنيف للمريض "
                "بشكل آمن من البيانات الحالية. "
                "الأفضل دكتور مختص يراجع الصورة."
            )

        return reply

    def explain_pathology(
        self,
        *,
        result: dict[str, Any],
        language: str,
    ) -> str:

        results = result.get("results")

        if not isinstance(results, list):
            results = []

        unreadable_fields = result.get(
            "unreadable_fields"
        )

        if not isinstance(
            unreadable_fields,
            list,
        ):
            unreadable_fields = []

        abnormal: list[dict[str, Any]] = []
        uncertain: list[dict[str, Any]] = []

        for item in results:

            if not isinstance(item, dict):
                continue

            flag = str(
                item.get("flag") or "unknown"
            ).strip().lower()

            mapping_status = str(
                item.get("mapping_status") or ""
            ).strip().lower()

            if (
                flag in {"low", "high"}
                and mapping_status == "mapped"
            ):
                abnormal.append(item)

            elif (
                flag == "unknown"
                or mapping_status != "mapped"
            ):
                uncertain.append(item)

        clean_unreadable = [
            str(item).strip()
            for item in unreadable_fields
            if str(item).strip()
        ]

        if language == "en":

            parts = [
                "The laboratory report was processed "
                "using the reference information available "
                "in the report."
            ]

            if abnormal:
                rendered = [
                    self._render_lab_result(
                        item=item,
                        language="en",
                    )
                    for item in abnormal
                ]

                parts.append(
                    "Results flagged outside their "
                    "reference range: "
                    + "; ".join(rendered)
                    + "."
                )

            else:
                parts.append(
                    "No mapped result was flagged as "
                    "low or high."
                )

            if uncertain:
                names = self._result_names(
                    uncertain
                )

                if names:
                    parts.append(
                        "Some results could not be safely "
                        "evaluated: "
                        + ", ".join(names)
                        + "."
                    )

            if clean_unreadable:
                parts.append(
                    "Unreadable fields: "
                    + ", ".join(
                        clean_unreadable
                    )
                    + "."
                )

            parts.append(
                "These flags describe the report values "
                "and do not establish a diagnosis."
            )

            return " ".join(parts)

        document_type = str(
            result.get("document_type") or ""
        ).strip().lower()
        is_cbc = document_type in {"cbc", "complete blood count"} or any(
            str(item.get("panel") or "").lower() == "cbc"
            for item in results
            if isinstance(item, dict)
        )

        report_name = (
            "تقرير صورة الدم الكاملة (CBC)"
            if is_cbc
            else "تقرير التحاليل"
        )
        parts = [
            f"قرأت {report_name} وقارنت الأرقام بالمجالات المرجعية المكتوبة في التقرير."
        ]

        if abnormal:
            rendered = [
                self._render_lab_result(
                    item=item,
                    language="ar",
                )
                for item in abnormal
            ]

            parts.append(
                "القيم التالية خارج المجال المكتوب في التقرير:\n"
                + "\n".join(f"• {item}" for item in rendered)
            )

        else:
            parts.append(
                "لم تظهر قيم مقروءة خارج المجالات المرجعية المكتوبة في التقرير."
            )

        if uncertain:
            names = self._result_names(
                uncertain
            )

            if names:
                parts.append(
                    "وفي نتائج مش قادر أقيّمها بثقة من الصورة: "
                    + "، ".join(names)
                    + "."
                )

        if clean_unreadable:
            parts.append(
                "وفي حقول مش واضحة في الصورة: "
                + "، ".join(clean_unreadable)
                + "."
            )

        parts.append(
            "المعنى ببساطة: العلامة بتقول إن الرقم أقل أو أعلى من المجال الذي حدده هذا المختبر، لكنها لا تحدد سبب ذلك ولا تشخّص مرضًا. الطبيب يفسرها مع الأعراض والتاريخ الصحي وباقي الفحوصات."
        )

        return " ".join(parts)

    def _render_lab_result(
        self,
        *,
        item: dict[str, Any],
        language: str,
    ) -> str:

        canonical_name = str(
            item.get("canonical_name") or ""
        ).strip().lower()
        raw_name = str(item.get("raw_name") or "").strip()
        name = (
            self._LAB_LABELS_AR.get(canonical_name, raw_name)
            if language == "ar"
            else raw_name or canonical_name or "result"
        )

        value = item.get("value")

        unit = str(
            item.get("unit") or ""
        ).strip()

        reference_text = str(
            item.get("reference_text") or ""
        ).strip()

        flag = str(
            item.get("flag") or "unknown"
        ).strip().lower()

        value_text = (
            str(value)
            if value is not None
            else "unknown"
        )

        if unit:
            value_text += f" {unit}"

        if language == "en":

            flag_text = (
                self._FLAG_LABELS_EN.get(
                    flag,
                    flag,
                )
            )

            text = (
                f"{name}: {value_text} "
                f"({flag_text})"
            )

            if reference_text:
                text += (
                    f", reference {reference_text}"
                )

            return text

        flag_text = (
            self._FLAG_LABELS_AR.get(
                flag,
                flag,
            )
        )

        flag_text = {
            "low": "أقل من المجال المكتوب في التقرير",
            "high": "أعلى من المجال المكتوب في التقرير",
            "normal": "داخل المجال المكتوب في التقرير",
            "unknown": "لم يمكن تقييمه بوضوح",
        }.get(
            flag,
            flag,
        )

        text = (
            f"{name} = {value_text}، وده {flag_text}"
        )

        if reference_text:
            text += (
                f"؛ الطبيعي في التقرير {reference_text}"
            )

        return text

    @staticmethod
    def _result_names(
        items: list[dict[str, Any]],
    ) -> list[str]:

        names: list[str] = []

        for item in items:

            name = str(
                item.get("raw_name")
                or item.get("canonical_name")
                or ""
            ).strip()

            if name:
                names.append(name)

        return names
