from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(
    "medmind.voice_gateway.deepgram"
)

DEFAULT_KEYTERMS = [
    # =====================================================
    # Booking
    # =====================================================
    "أحجز",
    "احجز",
    "أحجز كشف",
    "احجز كشف",
    "أحجز عند دكتور",
    "موعد كشف",
    "ميعاد كشف",

    # =====================================================
    # Cancellation
    # =====================================================
    "ألغي الحجز",
    "إلغاء الحجز",
    "ألغي الميعاد",
    "إلغاء الموعد",

    # =====================================================
    # Rescheduling
    # =====================================================
    "أغير الميعاد",
    "أغير الموعد",
    "أأجل الميعاد",
    "أقدم الميعاد",
    "إعادة جدولة",
    "reschedule appointment",

    # =====================================================
    # Dermatology
    # =====================================================
    "جلدية",
    "كشف جلدية",
    "دكتور جلدية",
    "الأمراض الجلدية",

    # =====================================================
    # Ophthalmology
    # =====================================================
    "عيون",
    "كشف عيون",
    "دكتور عيون",
    "طب العيون",

    # =====================================================
    # Internal Medicine
    # =====================================================
    "باطنة",
    "كشف باطنة",
    "دكتور باطنة",
    "الباطنة",

    # =====================================================
    # Pediatrics
    # =====================================================
    "أطفال",
    "كشف أطفال",
    "دكتور أطفال",
    "طب الأطفال",

    # =====================================================
    # Code switching
    # =====================================================
    "appointment",
    "book appointment",
    "cancel appointment",
]

TranscriptCallback = Callable[
    [str, bool],
    None,
]



FINALIZE_SETTLE_DELAY_SECONDS = 0.60

FINALIZE_MAX_WAIT_SECONDS = 1.50

# Watchdog polling frequency.
FINALIZE_WATCHDOG_INTERVAL_SECONDS = 0.05


class DeepgramStreamingSTT:
    """
    Streaming Deepgram Nova-3 STT.

    Supported inputs:
        - G.711 mu-law, mono, 8 kHz
        - Linear PCM16, mono, configurable sample rate

    Turn ownership:
        Silero VAD owns user turn boundaries.

    Important:
        Deepgram may emit multiple is_final=True segments
        for ONE spoken utterance.

        Example:

            final=True
            "عايز ألغي"

            final=True
            "الحجز"

        These belong to one user turn.

        We buffer them and emit one final transcript after
        Deepgram's finalized results settle.
    """

    def __init__(
        self,
        *,
        language: str = "ar-EG",
        encoding: str = "mulaw",
        sample_rate: int = 8000,
        keyterms: list[str] | None = None,
        on_transcript: TranscriptCallback | None = None,
    ) -> None:

        api_key = os.getenv(
            "DEEPGRAM_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is not configured"
            )

        if encoding not in {
            "mulaw",
            "linear16",
        }:
            raise ValueError(
                "Unsupported Deepgram encoding: "
                f"{encoding}"
            )

        if sample_rate <= 0:
            raise ValueError(
                "sample_rate must be greater than zero"
            )

        self._client = AsyncDeepgramClient(
            api_key=api_key,
        )

        self._language = language
        self._encoding = encoding
        self._sample_rate = sample_rate
        self._keyterms = (
            keyterms
            if keyterms is not None
            else DEFAULT_KEYTERMS
        )
        self._on_transcript = on_transcript

        self._context: Any = None
        self._connection: Any = None

        self._listener_task: (
            asyncio.Task[Any]
            | None
        ) = None

        self._open_event = asyncio.Event()
        self._closed_event = asyncio.Event()

        # ====================================================
        # Final transcript aggregation
        # ====================================================

        self._final_parts: list[str] = []

        # ====================================================
        # Silero-owned utterance state
        # ====================================================

        # True while Silero believes the caller is speaking.
        self._utterance_active = False

        # ====================================================
        # Finalize state
        # ====================================================

        # True after Silero speech-end triggers send_finalize().
        self._finalize_pending = False

        # monotonic timestamp when Finalize was sent.
        self._finalize_started_at: (
            float
            | None
        ) = None

        # monotonic timestamp of the latest useful finalized
        # Deepgram segment.
        self._last_final_at: (
            float
            | None
        ) = None

        # Single watchdog task.
        self._finalize_flush_task: (
            asyncio.Task[Any]
            | None
        ) = None

    # ========================================================
    # Start
    # ========================================================

    async def start(
        self,
    ) -> None:

        if self._connection is not None:
            return

        self._open_event.clear()
        self._closed_event.clear()

        self._final_parts.clear()

        await self._cancel_finalize_flush_task()

        self._utterance_active = False
        self._finalize_pending = False
        self._finalize_started_at = None
        self._last_final_at = None

        # ====================================================
        # Deepgram connection
        #
        # endpointing=false:
        #
        # Deepgram should not independently control our
        # user-turn boundary.
        #
        # Silero VAD is the source of truth for:
        #
        #     speech start
        #     speech end
        #
        # Deepgram remains responsible for transcription.
        # ====================================================

        self._context = (
                self._client.listen.v1.connect(
                    model="nova-3",
                    language=self._language,
                    encoding=self._encoding,
                    sample_rate=str(
                        self._sample_rate
                    ),
                    channels="1",
                    interim_results="true",
                    smart_format="true",
                    endpointing="false",

                    # Nova-3 Keyterm Prompting
                    keyterm=self._keyterms,
                )
        )

        self._connection = (
            await self._context.__aenter__()
        )

        self._connection.on(
            EventType.OPEN,
            self._handle_open,
        )

        self._connection.on(
            EventType.MESSAGE,
            self._handle_message,
        )

        self._connection.on(
            EventType.ERROR,
            self._handle_error,
        )

        self._connection.on(
            EventType.CLOSE,
            self._handle_close,
        )

        # ----------------------------------------------------
        # start_listening() owns Deepgram's receive loop.
        #
        # It must run independently from the audio producer.
        # ----------------------------------------------------

        self._listener_task = (
            asyncio.create_task(
                self._connection.start_listening(),
                name="deepgram-stt-listener",
            )
        )

        try:

            await asyncio.wait_for(
                self._open_event.wait(),
                timeout=5.0,
            )

        except TimeoutError as exc:

            await self.close()

            raise RuntimeError(
                "Deepgram WebSocket "
                "did not open in time"
            ) from exc

        logger.info(
            "deepgram_stt_started "
            "model=nova-3 "
            "language=%s "
            "encoding=%s "
            "sample_rate=%d "
            "endpointing=false "
            "keyterms=%s "
            "finalize_settle_ms=%d "
            "finalize_max_wait_ms=%d",
            self._language,
            self._encoding,
            self._sample_rate,
            self._keyterms,
            int(
                FINALIZE_SETTLE_DELAY_SECONDS
                * 1000
            ),
            int(
                FINALIZE_MAX_WAIT_SECONDS
                * 1000
            ),
        )

    # ========================================================
    # Silero Speech Start
    # ========================================================

    def begin_utterance(
        self,
    ) -> None:
        """
        Called by Silero when real user speech starts.

        If another Silero speech-start happens while the
        previous Finalize is still settling, treat it as
        continuation of the same user turn.

        This protects us from a short pause being split into
        two separate MedMind requests.
        """

        # ----------------------------------------------------
        # Silero may briefly report end-of-speech and then
        # detect speech again before our settle timer expires.
        #
        # In that situation:
        #
        #   - cancel the pending watchdog
        #   - keep _final_parts
        #   - reopen the same logical user turn
        #
        # The next speech-end will call finalize() again.
        # ----------------------------------------------------

        if self._finalize_pending:

            logger.info(
                "deepgram_utterance_resumed "
                "action=cancel_pending_finalize"
            )

            self._cancel_finalize_watchdog_nowait()

            self._finalize_pending = False
            self._finalize_started_at = None
            self._last_final_at = None

        self._utterance_active = True

        logger.debug(
            "deepgram_utterance_started"
        )

    # ========================================================
    # Send Audio
    # ========================================================

    async def send_audio(
        self,
        audio: bytes,
    ) -> None:

        if self._connection is None:
            raise RuntimeError(
                "Deepgram STT is not started"
            )

        if not audio:
            return

        if (
            self._listener_task is not None
            and self._listener_task.done()
        ):
            raise RuntimeError(
                "Deepgram listener "
                "is no longer running"
            )

        try:

            await self._connection.send_media(
                audio
            )

        except ConnectionClosed as exc:

            raise RuntimeError(
                "Deepgram connection closed "
                "while sending audio"
            ) from exc

    # ========================================================
    # Keep Alive
    # ========================================================

    async def keep_alive(
        self,
    ) -> None:

        if self._connection is None:
            return

        try:

            await (
                self._connection.send_keep_alive()
            )

        except ConnectionClosed:

            logger.warning(
                "deepgram_keep_alive_"
                "skipped_connection_closed"
            )

    # ========================================================
    # Finalize
    #
    # Called by Silero VAD when speech ends.
    # ========================================================

    async def finalize(
        self,
    ) -> None:

        if self._connection is None:
            return

        try:

            await (
                self._connection.send_finalize()
            )

        except ConnectionClosed:

            logger.warning(
                "deepgram_finalize_"
                "skipped_connection_closed"
            )

            return

        # ----------------------------------------------------
        # Silero decided that the current speech region ended.
        # ----------------------------------------------------

        self._utterance_active = False

        now = time.monotonic()

        self._finalize_pending = True

        self._finalize_started_at = now

        # ----------------------------------------------------
        # Start settle timing from Finalize itself.
        #
        # If Deepgram produces finalized text afterwards,
        # _last_final_at will be moved forward.
        # ----------------------------------------------------

        self._last_final_at = now

        logger.info(
            "deepgram_finalize_sent "
            "settle_ms=%d "
            "max_wait_ms=%d",
            int(
                FINALIZE_SETTLE_DELAY_SECONDS
                * 1000
            ),
            int(
                FINALIZE_MAX_WAIT_SECONDS
                * 1000
            ),
        )

        # ----------------------------------------------------
        # There must be ONE watchdog only.
        # ----------------------------------------------------

        await self._cancel_finalize_flush_task()

        self._finalize_flush_task = (
            asyncio.create_task(
                self._finalize_watchdog(),
                name="deepgram-finalize-watchdog",
            )
        )

    # ========================================================
    # Close
    # ========================================================

    async def close(
        self,
    ) -> None:

        connection = (
            self._connection
        )

        context = (
            self._context
        )

        listener_task = (
            self._listener_task
        )

        self._connection = None
        self._context = None
        self._listener_task = None

        await (
            self._cancel_finalize_flush_task()
        )

        self._utterance_active = False
        self._finalize_pending = False
        self._finalize_started_at = None
        self._last_final_at = None

        # ----------------------------------------------------
        # Do not send unfinished user text to MedMind after
        # the phone call has already ended.
        # ----------------------------------------------------

        self._final_parts.clear()

        if connection is not None:

            try:

                await (
                    connection.send_close_stream()
                )

            except ConnectionClosed:

                logger.info(
                    "deepgram_close_stream_"
                    "skipped_connection_closed"
                )

            except Exception:

                logger.exception(
                    "deepgram_close_stream_error"
                )

        if context is not None:

            try:

                await context.__aexit__(
                    None,
                    None,
                    None,
                )

            except ConnectionClosed:

                pass

            except Exception:

                logger.exception(
                    "deepgram_context_close_error"
                )

        if (
            listener_task is not None
            and not listener_task.done()
        ):

            listener_task.cancel()

            await asyncio.gather(
                listener_task,
                return_exceptions=True,
            )

        logger.info(
            "deepgram_stt_closed"
        )

    # ========================================================
    # Deepgram OPEN
    # ========================================================

    def _handle_open(
        self,
        _: Any,
    ) -> None:

        logger.info(
            "deepgram_connection_open"
        )

        self._open_event.set()

    # ========================================================
    # Deepgram MESSAGE
    # ========================================================

    def _handle_message(
        self,
        message: Any,
    ) -> None:

        if (
            getattr(
                message,
                "type",
                None,
            )
            != "Results"
        ):
            return

        channel = getattr(
            message,
            "channel",
            None,
        )

        if channel is None:
            return

        alternatives = getattr(
            channel,
            "alternatives",
            None,
        )

        if not alternatives:
            return

        transcript = getattr(
            alternatives[0],
            "transcript",
            "",
        ).strip()

        is_final = bool(
            getattr(
                message,
                "is_final",
                False,
            )
        )

        speech_final = bool(
            getattr(
                message,
                "speech_final",
                False,
            )
        )

        from_finalize = bool(
            getattr(
                message,
                "from_finalize",
                False,
            )
        )

        # ====================================================
        # Logging
        #
        # Do NOT return only because transcript == "".
        #
        # Deepgram can return a final/control Results message
        # with an empty transcript.
        # ====================================================

        if (
            transcript
            or is_final
            or speech_final
            or from_finalize
        ):

            logger.info(
                "deepgram_transcript "
                "final=%s "
                "speech_final=%s "
                "from_finalize=%s "
                "text=%s",
                is_final,
                speech_final,
                from_finalize,
                transcript,
            )

        # ====================================================
        # Interim Result
        # ====================================================

        if not is_final:

            # ------------------------------------------------
            # Only expose interim transcription while Silero
            # considers speech active.
            #
            # After speech-end, late Deepgram interims should
            # not become a new logical user turn.
            # ------------------------------------------------

            if (
                transcript
                and self._utterance_active
                and self._on_transcript
                is not None
            ):

                self._on_transcript(
                    transcript,
                    False,
                )

            return

        # ====================================================
        # Ignore late final text outside a Silero turn
        # ====================================================
        #
        # After the watchdog finishes:
        #
        #   _utterance_active = False
        #   _finalize_pending = False
        #
        # Deepgram WebSocket remains connected and can still
        # produce late/noisy finalized text.
        #
        # That text must NOT become another MedMind request.
        # ====================================================

        if not (
            self._utterance_active
            or self._finalize_pending
        ):

            if transcript:

                logger.info(
                    "deepgram_late_final_ignored "
                    "text=%s",
                    transcript,
                )

            return

        # ====================================================
        # Final Deepgram segment
        # ====================================================

        if transcript:

            self._final_parts.append(
                transcript
            )

            # ------------------------------------------------
            # The watchdog uses this value to detect when
            # Deepgram final results have stopped arriving.
            # ------------------------------------------------

            self._last_final_at = (
                time.monotonic()
            )

            logger.debug(
                "deepgram_final_segment_buffered "
                "parts=%d "
                "text=%s",
                len(
                    self._final_parts
                ),
                transcript,
            )

        # ====================================================
        # Diagnostic flags only
        #
        # DO NOT flush here.
        # ====================================================

        if speech_final:

            logger.debug(
                "deepgram_speech_final_received "
                "action=wait_for_settle"
            )

        if from_finalize:

            logger.debug(
                "deepgram_from_finalize_received "
                "action=wait_for_settle"
            )

    # ========================================================
    # Finalize Watchdog
    # ========================================================

    async def _finalize_watchdog(
        self,
    ) -> None:
        """
        Wait until Deepgram's finalized text has been quiet
        for FINALIZE_SETTLE_DELAY_SECONDS.

        Also enforce FINALIZE_MAX_WAIT_SECONDS from the
        moment send_finalize() was sent.
        """

        current_task = (
            asyncio.current_task()
        )

        try:

            while self._finalize_pending:

                await asyncio.sleep(
                    FINALIZE_WATCHDOG_INTERVAL_SECONDS
                )

                now = (
                    time.monotonic()
                )

                finalize_started_at = (
                    self._finalize_started_at
                )

                last_final_at = (
                    self._last_final_at
                )

                if finalize_started_at is None:
                    return

                # ============================================
                # Normal path
                #
                # At least one finalized text segment exists,
                # and no newer final segment has appeared for
                # 600 ms.
                # ============================================

                if (
                    self._final_parts
                    and last_final_at is not None
                    and (
                        now
                        - last_final_at
                    )
                    >= FINALIZE_SETTLE_DELAY_SECONDS
                ):

                    logger.info(
                        "deepgram_finalize_settled "
                        "parts=%d "
                        "quiet_ms=%.0f",
                        len(
                            self._final_parts
                        ),
                        (
                            now
                            - last_final_at
                        )
                        * 1000,
                    )

                    self._finish_finalize(
                        reason="finalize_settled",
                    )

                    return

                # ============================================
                # Absolute safety limit
                # ============================================

                if (
                    now
                    - finalize_started_at
                ) >= FINALIZE_MAX_WAIT_SECONDS:

                    logger.warning(
                        "deepgram_finalize_max_wait "
                        "parts=%d "
                        "waited_ms=%.0f",
                        len(
                            self._final_parts
                        ),
                        (
                            now
                            - finalize_started_at
                        )
                        * 1000,
                    )

                    self._finish_finalize(
                        reason="finalize_max_wait",
                    )

                    return

        except asyncio.CancelledError:

            return

        finally:

            if (
                self._finalize_flush_task
                is current_task
            ):

                self._finalize_flush_task = None

    # ========================================================
    # Finish Finalize Transaction
    # ========================================================

    def _finish_finalize(
        self,
        *,
        reason: str,
    ) -> None:

        self._finalize_pending = False

        self._finalize_started_at = None
        self._last_final_at = None

        self._flush_final_transcript(
            reason=reason,
        )

    # ========================================================
    # Emit ONE Complete Transcript
    # ========================================================

    def _flush_final_transcript(
        self,
        *,
        reason: str,
    ) -> None:

        if not self._final_parts:

            logger.debug(
                "deepgram_final_flush_empty "
                "reason=%s",
                reason,
            )

            return

        transcript = " ".join(
            part.strip()
            for part
            in self._final_parts
            if part.strip()
        ).strip()

        self._final_parts.clear()

        if not transcript:
            return

        logger.info(
            "deepgram_utterance_final "
            "reason=%s "
            "text=%s",
            reason,
            transcript,
        )

        if (
            self._on_transcript
            is not None
        ):

            self._on_transcript(
                transcript,
                True,
            )

    # ========================================================
    # Cancel watchdog synchronously
    #
    # Used when speech resumes before pending Finalize settles.
    # ========================================================

    def _cancel_finalize_watchdog_nowait(
        self,
    ) -> None:

        task = (
            self._finalize_flush_task
        )

        self._finalize_flush_task = None

        if task is None:
            return

        if not task.done():
            task.cancel()

    # ========================================================
    # Cancel watchdog asynchronously
    # ========================================================

    async def _cancel_finalize_flush_task(
        self,
    ) -> None:

        task = (
            self._finalize_flush_task
        )

        self._finalize_flush_task = None

        if task is None:
            return

        if not task.done():
            task.cancel()

        await asyncio.gather(
            task,
            return_exceptions=True,
        )

    # ========================================================
    # Deepgram ERROR
    # ========================================================

    def _handle_error(
        self,
        error: Any,
    ) -> None:

        logger.error(
            "deepgram_connection_error "
            "error=%s",
            error,
        )

    # ========================================================
    # Deepgram CLOSE
    # ========================================================

    def _handle_close(
        self,
        _: Any,
    ) -> None:

        logger.info(
            "deepgram_connection_closed"
        )

        self._closed_event.set()