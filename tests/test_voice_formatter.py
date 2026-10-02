from __future__ import annotations

import unittest

from voice_gateway.text.voice_formatter import (
    format_arabic_time,
    prepare_text_for_speech,
)


class VoiceFormatterTests(unittest.TestCase):

    def test_arabic_booking_times_are_spoken_naturally(
        self,
    ) -> None:

        cases = {
            "12:00": "الساعة اتناشر الضهر",
            "12:30": "الساعة اتناشر ونص الضهر",
            "13:00": "الساعة واحدة الضهر",
            "14:30": "الساعة اتنين ونص الضهر",
            "17:00": "الساعة خمسة العصر",
            "20:00": "الساعة تمانية بالليل",
        }

        for value, expected in cases.items():

            with self.subTest(value=value):

                self.assertEqual(
                    format_arabic_time(value),
                    expected,
                )

    def test_arabic_confirmation_and_reference_hiding(
        self,
    ) -> None:

        backend_reply = (
            "تم تأكيد الحجز بنجاح. "
            "رقم الحجز: APT-260826-ABC123"
        )

        spoken_reply = prepare_text_for_speech(
            backend_reply,
            language="ar-EG",
        )

        self.assertEqual(
            spoken_reply,
            "تمام، حجزك اتأكد.",
        )

        # Original backend value remains unchanged.
        self.assertTrue(
            backend_reply.endswith(
                "APT-260826-ABC123"
            )
        )

    def test_english_reference_hiding_still_works(
        self,
    ) -> None:

        backend_reply = (
            "Booking reference: APT-260826-ABC123. "
            "Your appointment is at 12:30"
        )

        spoken_reply = prepare_text_for_speech(
            backend_reply,
            language="en",
        )

        self.assertEqual(
            spoken_reply,
            "Your appointment is at 12:30 PM",
        )

    def test_booking_completion_messages(
        self,
    ) -> None:

        cases = {
            "تم إلغاء الحجز بنجاح.": (
                "تمام، حجزك اتلغى."
            ),
            "تم تغيير ميعاد الحجز بنجاح.": (
                "تمام، ميعاد حجزك اتغير."
            ),
            (
                "تم تغيير ميعاد الحجز بنجاح. "
                "المعاد الجديد: 2026-08-27 الساعة 14:30."
            ): (
                "تمام، ميعاد حجزك اتغير. "
                "الميعاد الجديد: الخميس سبعة وعشرين أغسطس "
                "الساعة اتنين ونص الضهر."
            ),
            (
                "الموعد الجديد يوم "
                "2026-08-27 الساعة 17:00"
            ): (
                "الميعاد الجديد يوم "
                "الخميس سبعة وعشرين أغسطس "
                "الساعة خمسة العصر"
            ),
        }

        for backend_reply, expected in cases.items():

            with self.subTest(
                backend_reply=backend_reply
            ):

                self.assertEqual(
                    prepare_text_for_speech(
                        backend_reply,
                        language="ar",
                    ),
                    expected,
                )

    def test_available_times_are_compact(
        self,
    ) -> None:

        backend_reply = (
            "المواعيد المتاحة: "
            "12:00، 12:30، 13:00، "
            "14:30، 17:00، 20:00"
        )

        spoken_reply = prepare_text_for_speech(
            backend_reply,
            language="ar",
        )

        self.assertEqual(
            spoken_reply,
            (
                "المواعيد المتاحة: "
                "اتناشر الضهر، "
                "اتناشر ونص الضهر، "
                "واحدة الضهر، "
                "اتنين ونص الضهر، "
                "خمسة العصر، "
                "تمانية بالليل"
            ),
        )

    def test_unlisted_minutes_use_words(
        self,
    ) -> None:

        spoken_reply = prepare_text_for_speech(
            "الموعد الساعة 12:07",
            language="ar",
        )

        self.assertEqual(
            spoken_reply,
            "الميعاد الساعة اتناشر وسبع دقايق الضهر",
        )

    def test_arabic_indic_digits_are_normalized_for_tts(
        self,
    ) -> None:

        backend_reply = (
            "الموعد يوم "
            "٢٠٢٦-٠٨-٢٧ "
            "الساعة ١٤:٣٠"
        )

        spoken_reply = (
            prepare_text_for_speech(
                backend_reply,
                language="ar",
            )
        )

        self.assertEqual(
            spoken_reply,
            (
                "الميعاد يوم "
                "الخميس سبعة وعشرين أغسطس "
                "الساعة اتنين ونص الضهر"
            ),
        ) 

    def test_extended_arabic_indic_time_digits(
        self,
    ) -> None:

        spoken_reply = (
            prepare_text_for_speech(
                "الموعد الساعة ۱۴:۳۰",
                language="ar",
            )
        )

        self.assertEqual(
            spoken_reply,
            "الميعاد الساعة اتنين ونص الضهر",
        )       


if __name__ == "__main__":
    unittest.main()
