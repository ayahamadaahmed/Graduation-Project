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
        "staff_percent": "نسبة Staff كما وردت في التقرير",
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

            follow_up = {
                "chest_xray": (
                    " Start with the clinician who ordered the X-ray or a primary-care clinician; a pulmonologist may be appropriate if a chest condition is confirmed or respiratory symptoms persist."
                ),
                "brain_mri": (
                    " Start with the clinician who ordered the MRI; neurology or neurosurgery referral should depend on the radiologist's report and the clinician's review."
                ),
                "kidney_ct": (
                    " Start with the clinician who ordered the scan; urology or another relevant specialty should depend on the confirmed finding and symptoms."
                ),
            }.get(modality, " Have the study reviewed by the clinician who ordered it, who can decide whether a specialist is needed.")
            reply += " Suggested follow-up:" + follow_up

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

        follow_up_ar = {
            "chest_xray": (
                "ابدئي بالطبيب الذي طلب الأشعة أو طبيب أسرة/باطنة؛ وقد تكون الصدرية مناسبة إذا أكد الطبيب وجود مشكلة صدرية أو استمرت أعراض التنفس."
            ),
            "brain_mri": (
                "ابدئي بالطبيب الذي طلب الرنين؛ والإحالة إلى مخ وأعصاب أو جراحة مخ وأعصاب تعتمد على تقرير اختصاصي الأشعة ومراجعة الطبيب."
            ),
            "kidney_ct": (
                "ابدئي بالطبيب الذي طلب الأشعة؛ ويُحدَّد ما إذا كانت المسالك البولية أو تخصص آخر مناسبًا بعد تأكيد النتيجة ومراجعة الأعراض."
            ),
        }.get(
            modality,
            "راجعي الطبيب الذي طلب الفحص، وهو يحدد إن كانت هناك حاجة إلى اختصاصي.",
        )
        reply += "\n\n## المتابعة المناسبة\n" + follow_up_ar

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
                "## Report summary\n"
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
                    "## Results outside the report's range\n"
                    + "\n".join(f"- {item}" for item in rendered)
                )

            else:
                parts.append(
                    "## Results outside the report's range\n"
                    "No mapped result was flagged as "
                    "low or high."
                )

            if uncertain:
                names = self._result_names(
                    uncertain
                )

                if names:
                    parts.append(
                        "## Results needing clarification\n"
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
                "## Important note\n"
                "These flags describe the report values "
                "and do not establish a diagnosis."
            )

            if abnormal:
                names = {
                    str(item.get("canonical_name") or "").lower()
                    for item in abnormal
                }
                follow_up = (
                    "## Suggested follow-up\n"
                    "Start with a primary-care or internal-medicine clinician (a pediatrician for a child) to review the result with symptoms, history, and medications. The result alone cannot determine whether a specialist referral is needed."
                )
                if names.intersection({"wbc", "neutrophils_absolute"}):
                    follow_up += (
                        " If a low neutrophil count persists or other blood-count abnormalities are present, the clinician may consider hematology. Fever or marked worsening while neutrophils are low needs urgent medical assessment."
                    )
                parts.append(follow_up)

            return "\n\n".join(parts)

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
            f"## ملخص التقرير\nقرأت {report_name} وقارنت الأرقام بالمجالات المرجعية المكتوبة في التقرير."
        ]

        if abnormal:
            parts.append(
                "## قيم خارج المجال المرجعي في التقرير\n"
                + self._render_lab_table(abnormal)
            )

        else:
            parts.append(
                "## القيم خارج المجال المرجعي\nلم تظهر قيم مقروءة خارج المجالات المرجعية المكتوبة في التقرير."
            )

        readable_without_reference = [
            item
            for item in uncertain
            if item.get("value") is not None
            and str(item.get("mapping_status") or "").lower() == "mapped"
            and str(item.get("canonical_name") or "").lower() != "staff_percent"
        ]
        staff_without_reference = [
            item
            for item in uncertain
            if item.get("value") is not None
            and str(item.get("canonical_name") or "").lower() == "staff_percent"
        ]
        readable_unmapped = [
            item
            for item in uncertain
            if item.get("value") is not None
            and str(item.get("mapping_status") or "").lower() == "unmapped"
        ]
        unreadable = [
            item
            for item in uncertain
            if item.get("value") is None
            or str(item.get("mapping_status") or "").lower() == "unreadable"
        ]

        if is_cbc:
            reassuring_names = {
                "hemoglobin",
                "rbc",
                "hematocrit",
                "platelets",
                "lymphocytes_absolute",
            }
            reassuring = [
                item
                for item in results
                if isinstance(item, dict)
                and str(item.get("canonical_name") or "").lower()
                in reassuring_names
                and str(item.get("flag") or "").lower() == "normal"
            ]
            if reassuring:
                parts.append(
                    "## قيم أخرى داخل المجال المرجعي\n"
                    + self._render_lab_table(reassuring)
                )

            differential_names = {
                "neutrophils_percent",
                "neutrophils_absolute",
                "lymphocytes_percent",
                "lymphocytes_absolute",
                "monocytes_percent",
                "monocytes_absolute",
                "eosinophils_percent",
                "eosinophils_absolute",
                "basophils_percent",
                "basophils_absolute",
                "staff_percent",
            }
            if any(
                isinstance(item, dict)
                and str(item.get("canonical_name") or "").lower()
                in differential_names
                for item in results
            ):
                parts.append(
                    "## كيف نفهم نسب كرات الدم البيضاء؟\n"
                    "النسبة المئوية لنوع من كرات الدم البيضاء هي حصته من الإجمالي، "
                    "أما العدد المطلق فيوضح عدد هذا النوع في حجم الدم. الطبيب يفسرهما معًا؛ "
                    "ارتفاع النسبة وحده لا يعني بالضرورة ارتفاع العدد الفعلي."
                )

        if readable_without_reference:
            parts.append(
                "## أرقام مقروءة بلا مجال مرجعي واضح\n"
                "في أرقام اتقرت، لكن التقرير ما أظهرش لها مجالًا مرجعيًا واضحًا، "
                "فماينفعش أقول إنها طبيعية أو غير طبيعية من غير مرجع المعمل: "
                + "؛ ".join(
                    self._render_lab_result(item=item, language="ar")
                    for item in readable_without_reference
                )
                + "."
            )

        if readable_unmapped:
            parts.append(
                "## أرقام تحتاج تأكيد اسم الاختبار\n"
                "في أرقام مقروءة لكن اسم الاختبار محتاج تأكيد قبل تفسيره: "
                + "؛ ".join(
                    self._render_lab_result(item=item, language="ar")
                    for item in readable_unmapped
                )
                + "."
            )

        if unreadable:
            names = self._result_names(unreadable)
            if names:
                parts.append(
                    "## أجزاء غير واضحة في الصورة\n"
                    "في أسماء أو أرقام مش واضحة كفاية في الصورة: "
                    + "، ".join(names)
                    + "."
                )

        if staff_without_reference:
            staff_rows = "\n".join(
                f"- {self._render_lab_result(item=item, language='ar')}"
                for item in staff_without_reference
            )
            parts.append(
                "## توضيح خانة Staff\n"
                + staff_rows
                + "\nالتقرير يعرض هذه القيمة، لكن المجال المرجعي مكتوب بشرطة. لا أقدر أحدد من الصورة وحدها هل الصفر نتيجة مقاسة/عدم رصد خلايا أم أن المختبر يستخدمه للدلالة على أن الخانة لم تُقَس؛ لذلك لا أصنفها طبيعية أو غير طبيعية. يُفضّل سؤال المعمل أو الطبيب عن طريقة تسجيل هذه الخانة في تقريرهم."
            )

        has_low_white_cells = any(
            isinstance(item, dict)
            and str(item.get("canonical_name") or "").lower()
            in {"wbc", "neutrophils_absolute"}
            and str(item.get("flag") or "").lower() == "low"
            for item in results
        )
        if is_cbc and has_low_white_cells:
            parts.append(
                "## الخطوة التالية والسياق الصحي\n"
                "لأن عدد كرات الدم البيضاء أو العدلات أقل من مرجع التقرير، "
                "فالسبب مايتحددش من CBC وحده. لو حابة نفهم السياق، قوليلي: هل فيه "
                "حرارة أو عدوى حاليًا أو مؤخرًا؟ وهل فيه أدوية أو تحليل CBC أقدم للمقارنة؟ "
                "العمر ومدة النتيجة مهمين للطبيب كمان. كبداية، راجعي طبيب أسرة أو باطنة "
                "(وطبيب أطفال لو المريضة طفلة) لمراجعة النتيجة والأعراض والأدوية وتحديد "
                "الحاجة لإعادة التحليل. لو استمر انخفاض العدلات أو ظهرت اضطرابات أخرى في "
                "صورة الدم، قد يقرر الطبيب إحالتك إلى اختصاصي أمراض دم. لو عندك حرارة أو "
                "تدهور واضح في حالتك، اطلبي تقييمًا طبيًا عاجلًا."
            )
        elif abnormal:
            specialties = {
                str(item.get("canonical_name") or "").lower()
                for item in abnormal
            }
            next_step = (
                "## المتابعة المقترحة\n"
                "راجعي طبيب أسرة أو باطنة أولًا لمراجعة النتائج مع الأعراض والتاريخ الصحي؛ "
                "النتيجة وحدها لا تحدد إن كنتِ تحتاجين اختصاصيًا أو إحالة."
            )
            if specialties.intersection({"alt", "ast", "alp", "bilirubin", "ggt"}):
                next_step += (
                    " إذا استمرت اضطرابات وظائف الكبد، قد يناقش الطبيب إحالتك إلى "
                    "اختصاصي كبد أو جهاز هضمي."
                )
            elif specialties.intersection({"creatinine", "egfr", "urea", "bun"}):
                next_step += (
                    " وإذا استمر اضطراب وظائف الكلى، قد يناقش الطبيب إحالتك إلى "
                    "اختصاصي كلى."
                )
            elif specialties.intersection({"vitamin_d_25oh", "vitamin_d2", "vitamin_d3"}):
                next_step += (
                    " نقص فيتامين د يُراجع عادةً مع طبيب أسرة أو باطنة؛ وقد يلزم "
                    "اختصاصي آخر حسب الأعراض والسبب الذي يحدده الطبيب."
                )
            elif specialties.intersection(
                {"hemoglobin", "rbc", "hematocrit", "ferritin", "serum_iron", "tibc", "vitamin_b12", "folate"}
            ):
                next_step += (
                    " إذا تأكد فقر الدم أو استمر اضطراب خلايا الدم/مخزون الحديد، "
                    "قد يقرر الطبيب إحالتك إلى اختصاصي أمراض دم حسب بقية النتائج والسبب المحتمل."
                )
            parts.append(next_step)

        if clean_unreadable:
            parts.append(
                "حقول أخرى مش واضحة في الصورة: "
                + "، ".join(clean_unreadable)
                + "."
            )

        parts.append(
            "## ملاحظة مهمة\nالعلامة بتوضح إن الرقم أقل أو أعلى من المجال الذي حدده هذا المختبر، لكنها لا تحدد السبب ولا تشخّص مرضًا. الطبيب يفسرها مع الأعراض والتاريخ الصحي وباقي الفحوصات."
        )

        return "\n\n".join(parts)

    def _render_lab_table(
        self,
        items: list[dict[str, Any]],
    ) -> str:
        rows = [
            "| الفحص | النتيجة | المجال المرجعي في التقرير | المقارنة |",
            "|---|---:|---:|---|",
        ]
        for item in items:
            canonical_name = str(item.get("canonical_name") or "").strip().lower()
            raw_name = str(item.get("raw_name") or "").strip()
            name = self._LAB_LABELS_AR.get(canonical_name, raw_name or canonical_name)
            value = item.get("value")
            unit = str(item.get("unit") or "").strip()
            value_text = "غير واضح" if value is None else str(value)
            if unit:
                value_text += f" {unit}"
            reference = str(item.get("reference_text") or "—").strip()
            flag = str(item.get("flag") or "unknown").strip().lower()
            status = {
                "low": "أقل من المجال",
                "high": "أعلى من المجال",
                "normal": "داخل المجال",
                "unknown": "غير محدد",
            }.get(flag, "غير محدد")
            clean = lambda value: value.replace("|", "\\|").replace("\n", " ")
            rows.append(
                f"| {clean(name)} | {clean(value_text)} | {clean(reference)} | {status} |"
            )
        return "\n".join(rows)

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
            "unknown": (
                "التقرير يعرض القيمة دون مجال مرجعي للمقارنة"
                if value is not None
                else "القيمة غير واضحة بما يكفي للقراءة"
            ),
        }.get(
            flag,
            flag,
        )

        text = (
            f"{name} = {value_text}، وده {flag_text}"
        )

        if reference_text and reference_text.strip() not in {"-", "—", "–"}:
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
