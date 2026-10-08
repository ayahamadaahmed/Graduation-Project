from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


# ============================================================
# OPTIONAL .ENV LOADING
# ============================================================

try:
    from dotenv import load_dotenv

    load_dotenv(
        ROOT / ".env"
    )

except ImportError:
    pass


# ============================================================
# PROJECT IMPORTS
# ============================================================

from langchain_openai import ChatOpenAI

from agent.medmind.understanding.capability_router import (
    SemanticCapabilityRouter,
)

from agent.medmind.understanding.fallback_tool_planner import (
    FallbackToolPlanner,
)

from agent.medmind.understanding.orchestrator import (
    UnderstandingOrchestrator,
)

from agent.medmind.understanding.qwen_tool_planner import (
    QwenToolPlanner,
)

from agent.medmind.understanding.tool_planner import (
    ToolPlanner,
)

from evals.understanding.scoring import (
    CaseScore,
    score_understanding_result,
)


# ============================================================
# PATHS
# ============================================================

DATASET_PATH = (
    ROOT
    / "evals"
    / "understanding"
    / "cases.jsonl"
)

RESULTS_DIR = (
    ROOT
    / "evals"
    / "understanding"
    / "results"
)


# ============================================================
# COUNTING WRAPPER
#
# Observability only.
# Does not change planner decisions.
# ============================================================

class CountingPlanner:

    def __init__(
        self,
        *,
        name: str,
        planner: Any,
    ) -> None:

        self.name = name
        self.planner = planner
        self.calls = 0

    async def plan(
        self,
        *,
        message,
        candidates,
        context=None,
    ):

        self.calls += 1

        return await self.planner.plan(
            message=message,
            candidates=candidates,
            context=context,
        )


# ============================================================
# DATASET
# ============================================================

def load_cases() -> list[dict[str, Any]]:

    cases: list[dict[str, Any]] = []

    with DATASET_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            stripped = line.strip()

            if not stripped:
                continue

            cases.append(
                json.loads(
                    stripped
                )
            )

    return cases


# ============================================================
# PERCENTILE
# ============================================================

def percentile(
    values: list[float],
    p: float,
) -> float:

    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        len(ordered) - 1
    ) * p

    lower = int(position)
    upper = min(
        lower + 1,
        len(ordered) - 1,
    )

    fraction = (
        position - lower
    )

    return (
        ordered[lower]
        + (
            ordered[upper]
            - ordered[lower]
        )
        * fraction
    )


# ============================================================
# RESULT SERIALIZATION
# ============================================================

def result_to_dict(
    result: Any,
) -> dict[str, Any]:

    return {
        "status":
            getattr(
                result,
                "status",
                None,
            ),

        "capability":
            getattr(
                result,
                "capability",
                None,
            ),

        "arguments":
            dict(
                getattr(
                    result,
                    "arguments",
                    {},
                )
                or {}
            ),

        "confirmation":
            getattr(
                result,
                "confirmation",
                "unknown",
            ),

        "correction_target":
            getattr(
                result,
                "correction_target",
                None,
            ),

        "ambiguity_kind":
            getattr(
                result,
                "ambiguity_kind",
                None,
            ),

        "reason":
            getattr(
                result,
                "reason",
                None,
            ),

        "attempts":
            getattr(
                result,
                "attempts",
                None,
            ),

        "used_broad_candidates":
            getattr(
                result,
                "used_broad_candidates",
                False,
            ),
    }


# ============================================================
# FAILURE CLASSIFICATION
# ============================================================

def classify_failure(
    *,
    score: CaseScore,
    actual: dict[str, Any],
) -> str:

    if (
        actual.get("status")
        == "fallback_required"
    ):

        reason = (
            actual.get("reason")
            or "unknown"
        )

        return (
            f"fallback_required:{reason}"
        )

    if not score.status_correct:
        return "status_mismatch"

    if not score.capability_correct:
        return "capability_mismatch"

    if not score.arguments_correct:

        if score.missing_arguments:
            return "missing_argument"

        return (
            "wrong_or_hallucinated_argument"
        )

    if not score.confirmation_correct:
        return "confirmation_mismatch"

    if (
        not
        score.correction_target_correct
    ):
        return "correction_target_mismatch"

    if not score.ambiguity_correct:
        return "ambiguity_mismatch"

    return "unknown"


# ============================================================
# PRODUCTION CONFIG
# ============================================================

def read_positive_float(
    name: str,
    default: str,
) -> float:

    value = float(
        os.getenv(
            name,
            default,
        )
    )

    if value <= 0:
        raise RuntimeError(
            f"{name} must be greater than zero."
        )

    return value


def read_positive_int(
    name: str,
    default: str,
) -> int:

    value = int(
        os.getenv(
            name,
            default,
        )
    )

    if value <= 0:
        raise RuntimeError(
            f"{name} must be greater than zero."
        )

    return value


# ============================================================
# BUILD PRODUCTION UNDERSTANDING STACK
# ============================================================

def build_understanding_stack():

    groq_api_key = os.getenv(
        "GROQ_API_KEY"
    )

    if not groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is required."
        )

    if not os.getenv(
        "OPENAI_API_KEY"
    ):
        raise RuntimeError(
            "OPENAI_API_KEY is required."
        )

    # --------------------------------------------------------
    # Same production configuration.
    # --------------------------------------------------------

    qwen_model = os.getenv(
        "QWEN_PLANNER_MODEL",
        "qwen/qwen3.6-27b",
    )

    qwen_timeout = (
        read_positive_float(
            "QWEN_PLANNER_TIMEOUT",
            "3",
        )
    )

    qwen_primary_budget = (
        read_positive_float(
            "QWEN_PRIMARY_BUDGET",
            "1.5",
        )
    )

    qwen_max_tokens = (
        read_positive_int(
            "QWEN_PLANNER_MAX_TOKENS",
            "160",
        )
    )

    gpt_model_name = os.getenv(
        "PLANNER_FALLBACK_MODEL",
        "gpt-4.1",
    )

    gpt_timeout = (
        read_positive_float(
            "GPT_PLANNER_TIMEOUT",
            "4",
        )
    )

    understanding_top_k = (
        read_positive_int(
            "UNDERSTANDING_TOP_K",
            "8",
        )
    )

    understanding_timeout = (
        read_positive_float(
            "UNDERSTANDING_TIMEOUT",
            "5",
        )
    )

    router_timeout = (
        read_positive_float(
            "UNDERSTANDING_ROUTER_TIMEOUT",
            "2",
        )
    )

    # --------------------------------------------------------
    # Semantic router.
    # --------------------------------------------------------

    router = (
        SemanticCapabilityRouter()
    )

    # --------------------------------------------------------
    # Qwen primary.
    # --------------------------------------------------------

    qwen = QwenToolPlanner(
        api_key=groq_api_key,
        model=qwen_model,
        timeout=qwen_timeout,
        max_tokens=qwen_max_tokens,
    )

    counted_qwen = CountingPlanner(
        name="qwen",
        planner=qwen,
    )

    # --------------------------------------------------------
    # GPT fallback.
    # --------------------------------------------------------

    gpt_model = ChatOpenAI(
        model=gpt_model_name,
        temperature=0,
        timeout=gpt_timeout,
        max_retries=0,
    )

    gpt = ToolPlanner(
        model=gpt_model,
    )

    counted_gpt = CountingPlanner(
        name="gpt",
        planner=gpt,
    )

    # --------------------------------------------------------
    # Production planner policy / fallback layer.
    # --------------------------------------------------------

    planner = FallbackToolPlanner(
        primary=counted_qwen,
        fallback=counted_gpt,
        primary_timeout_seconds=(
            qwen_primary_budget
        ),
    )

    # --------------------------------------------------------
    # Orchestrator.
    #
    # Tenant capability enforcement is tested separately by
    # deterministic tenant-policy tests. This evaluation
    # measures semantic Understanding quality over the current
    # registered capability space.
    # --------------------------------------------------------

    orchestrator = (
        UnderstandingOrchestrator(
            router=router,
            planner=planner,
            top_k=understanding_top_k,
            total_timeout_seconds=(
                understanding_timeout
            ),
            router_timeout_seconds=(
                router_timeout
            ),
        )
    )

    config = {
        
        "qwen_primary_budget_seconds":
            qwen_primary_budget,
        "qwen_model":
            qwen_model,

        "qwen_timeout_seconds":
            qwen_timeout,

        "qwen_max_tokens":
            qwen_max_tokens,

        "gpt_model":
            gpt_model_name,

        "gpt_timeout_seconds":
            gpt_timeout,

        "understanding_top_k":
            understanding_top_k,

        "understanding_timeout_seconds":
            understanding_timeout,

        "router_timeout_seconds":
            router_timeout,
    }

    return (
        orchestrator,
        counted_qwen,
        counted_gpt,
        config,
    )


# ============================================================
# RUN EVALUATION
# ============================================================

async def run_evaluation(
    *,
    tag: str | None,
    case_id: str | None,
    limit: int | None,
    repeat: int,
) -> dict[str, Any]:
    cases = load_cases()

    if tag:

        cases = [
            case
            for case in cases
            if tag in case["tags"]
        ]

    if case_id:

        cases = [
            case
            for case in cases
            if case["id"] == case_id
        ]    

    if limit is not None:

        cases = cases[
            :limit
        ]

    if repeat > 1:

        repeated_cases = []

        for case in cases:

            for run_number in range(
                1,
                repeat + 1,
            ):

                repeated_case = dict(
                    case
                )

                repeated_case[
                    "id"
                ] = (
                    f"{case['id']}"
                    f"#run-{run_number}"
                )

                repeated_cases.append(
                    repeated_case
                )

        cases = repeated_cases    

    if not cases:
        raise RuntimeError(
            "No evaluation cases selected."
        )

    (
        orchestrator,
        qwen,
        gpt,
        config,
    ) = build_understanding_stack()

    print()
    print(
        "Initializing semantic router..."
    )

    # Warm only the local semantic router.
    # No paid LLM request is made here.
    orchestrator.router.route(
        "test",
        top_k=1,
    )

    print(
        f"Running {len(cases)} cases..."
    )
    print()

    results = []

    latencies_ms: list[float] = []

    full_pass_count = 0
    capability_correct_count = 0
    arguments_correct_count = 0
    confirmation_correct_count = 0
    ambiguity_correct_count = 0

    fallback_count = 0
    unexpected_ambiguity_count = 0

    failure_counts: Counter[str] = (
        Counter()
    )

    tag_totals = defaultdict(int)
    tag_passes = defaultdict(int)

    # ========================================================
    # SEQUENTIAL BASELINE
    #
    # Avoid rate-limit/concurrency noise during semantic
    # quality baseline.
    # ========================================================

    for index, case in enumerate(
        cases,
        start=1,
    ):

        qwen_before = qwen.calls
        gpt_before = gpt.calls

        started = time.perf_counter()

        try:

            result = await (
                orchestrator.understand(
                    message=case["message"],
                    context=case["context"],
                )
            )

            actual = (
                result_to_dict(
                    result
                )
            )

            runtime_error = None

        except Exception as exc:

            actual = {
                "status":
                    "error",

                "capability":
                    None,

                "arguments":
                    {},

                "confirmation":
                    "unknown",

                "correction_target":
                    None,

                "ambiguity_kind":
                    None,

                "reason":
                    type(exc).__name__,
            }

            runtime_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

        latency_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000
        )

        latencies_ms.append(
            latency_ms
        )

        qwen_calls = (
            qwen.calls
            - qwen_before
        )

        gpt_calls = (
            gpt.calls
            - gpt_before
        )

        score = (
            score_understanding_result(
                expected=case[
                    "expected"
                ],
                actual=actual,
            )
        )

        if score.passed:
            full_pass_count += 1

        if score.capability_correct:
            capability_correct_count += 1

        if score.arguments_correct:
            arguments_correct_count += 1

        if score.confirmation_correct:
            confirmation_correct_count += 1

        if score.ambiguity_correct:
            ambiguity_correct_count += 1

        if (
            actual.get("status")
            == "fallback_required"
        ):
            fallback_count += 1

        if (
            case["expected"].get(
                "status"
            )
            == "selected"
            and
            actual.get("status")
            == "ambiguous"
        ):
            unexpected_ambiguity_count += 1

        failure_type = None

        if not score.passed:

            failure_type = (
                classify_failure(
                    score=score,
                    actual=actual,
                )
            )

            failure_counts[
                failure_type
            ] += 1

        for case_tag in case["tags"]:

            tag_totals[
                case_tag
            ] += 1

            if score.passed:

                tag_passes[
                    case_tag
                ] += 1

        result_row = {
            "id":
                case["id"],

            "message":
                case["message"],

            "tags":
                case["tags"],

            "expected":
                case["expected"],

            "actual":
                actual,

            "passed":
                score.passed,

            "latency_ms":
                round(
                    latency_ms,
                    2,
                ),

            "qwen_calls":
                qwen_calls,

            "gpt_calls":
                gpt_calls,

            "missing_arguments":
                list(
                    score
                    .missing_arguments
                ),

            "wrong_arguments":
                list(
                    score
                    .wrong_arguments
                ),

            "failure_type":
                failure_type,

            "runtime_error":
                runtime_error,
        }

        results.append(
            result_row
        )

        marker = (
            "PASS"
            if score.passed
            else "FAIL"
        )

        provider_path = []

        if qwen_calls:
            provider_path.append(
                f"Qwen x{qwen_calls}"
            )

        if gpt_calls:
            provider_path.append(
                f"GPT x{gpt_calls}"
            )

        if not provider_path:
            provider_path.append(
                "deterministic"
            )

        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{marker:<4} "
            f"{case['id']:<30} "
            f"{latency_ms:8.1f} ms "
            f"{' -> '.join(provider_path)}"
        )

        if not score.passed:

            print(
                "       expected:",
                json.dumps(
                    case["expected"],
                    ensure_ascii=False,
                ),
            )

            print(
                "       actual:  ",
                json.dumps(
                    actual,
                    ensure_ascii=False,
                ),
            )

            print(
                "       failure: ",
                failure_type,
            )

    total = len(cases)

    tag_metrics = {}

    for case_tag in sorted(
        tag_totals
    ):

        count = tag_totals[
            case_tag
        ]

        passed = tag_passes[
            case_tag
        ]

        tag_metrics[
            case_tag
        ] = {
            "passed":
                passed,

            "total":
                count,

            "accuracy":
                round(
                    passed / count,
                    4,
                ),
        }

    summary = {
        "total_cases":
            total,

        "passed":
            full_pass_count,

        "failed":
            total
            - full_pass_count,

        "full_accuracy":
            round(
                full_pass_count
                / total,
                4,
            ),

        "capability_accuracy":
            round(
                capability_correct_count
                / total,
                4,
            ),

        "argument_accuracy":
            round(
                arguments_correct_count
                / total,
                4,
            ),

        "confirmation_accuracy":
            round(
                confirmation_correct_count
                / total,
                4,
            ),

        "ambiguity_accuracy":
            round(
                ambiguity_correct_count
                / total,
                4,
            ),

        "fallback_required_count":
            fallback_count,

        "unexpected_ambiguity_count":
            unexpected_ambiguity_count,

        "qwen_calls":
            qwen.calls,

        "gpt_calls":
            gpt.calls,

        "latency_ms": {
            "p50":
                round(
                    percentile(
                        latencies_ms,
                        0.50,
                    ),
                    2,
                ),

            "p95":
                round(
                    percentile(
                        latencies_ms,
                        0.95,
                    ),
                    2,
                ),

            "max":
                round(
                    max(
                        latencies_ms
                    ),
                    2,
                ),

            "mean":
                round(
                    sum(
                        latencies_ms
                    )
                    / len(
                        latencies_ms
                    ),
                    2,
                ),
        },

        "failure_types":
            dict(
                failure_counts
            ),

        "tag_metrics":
            tag_metrics,
    }

    return {
        "generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "config":
            config,

        "summary":
            summary,

        "results":
            results,
    }


# ============================================================
# REPORT
# ============================================================

def print_summary(
    report: dict[str, Any],
) -> None:

    summary = report[
        "summary"
    ]

    print()
    print(
        "=" * 72
    )
    print(
        "MEDMIND UNDERSTANDING EVALUATION"
    )
    print(
        "=" * 72
    )

    print(
        f"Cases:                 "
        f"{summary['total_cases']}"
    )

    print(
        f"Passed:                "
        f"{summary['passed']}"
    )

    print(
        f"Failed:                "
        f"{summary['failed']}"
    )

    print(
        f"Full accuracy:         "
        f"{summary['full_accuracy'] * 100:.2f}%"
    )

    print(
        f"Capability accuracy:   "
        f"{summary['capability_accuracy'] * 100:.2f}%"
    )

    print(
        f"Argument accuracy:     "
        f"{summary['argument_accuracy'] * 100:.2f}%"
    )

    print(
        f"Confirmation accuracy: "
        f"{summary['confirmation_accuracy'] * 100:.2f}%"
    )

    print(
        f"Ambiguity accuracy:    "
        f"{summary['ambiguity_accuracy'] * 100:.2f}%"
    )

    print()
    print(
        f"Qwen calls:            "
        f"{summary['qwen_calls']}"
    )

    print(
        f"GPT calls:             "
        f"{summary['gpt_calls']}"
    )

    print(
        f"Fallback required:     "
        f"{summary['fallback_required_count']}"
    )

    print(
        f"Unexpected ambiguity:  "
        f"{summary['unexpected_ambiguity_count']}"
    )

    latency = summary[
        "latency_ms"
    ]

    print()
    print(
        f"Latency P50:           "
        f"{latency['p50']:.2f} ms"
    )

    print(
        f"Latency P95:           "
        f"{latency['p95']:.2f} ms"
    )

    print(
        f"Latency max:           "
        f"{latency['max']:.2f} ms"
    )

    print(
        f"Latency mean:          "
        f"{latency['mean']:.2f} ms"
    )

    if summary[
        "failure_types"
    ]:

        print()
        print(
            "Failure types:"
        )

        for (
            failure_type,
            count,
        ) in sorted(
            summary[
                "failure_types"
            ].items()
        ):

            print(
                f"  {failure_type}: "
                f"{count}"
            )

    print()
    print(
        "Tag accuracy:"
    )

    for (
        tag,
        metrics,
    ) in sorted(
        summary[
            "tag_metrics"
        ].items()
    ):

        print(
            f"  {tag:<24} "
            f"{metrics['passed']}/"
            f"{metrics['total']} "
            f"("
            f"{metrics['accuracy'] * 100:.1f}%"
            f")"
        )


# ============================================================
# CLI
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Run the MedMind live "
            "Understanding evaluation."
        )
    )

    parser.add_argument(
        "--tag",
        default=None,
        help=(
            "Run only cases containing "
            "this tag."
        ),
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help=(
            "Run only the evaluation case "
            "with this exact ID."
        ),
    )

    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "Repeat each selected case N times."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Run only the first N "
            "selected cases."
        ),
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help=(
            "Do not save the JSON report."
        ),
    )

    return parser.parse_args()


async def async_main() -> None:

    args = parse_args()

    if (
        args.limit is not None
        and args.limit <= 0
    ):
        raise RuntimeError(
            "--limit must be greater than zero."
        )

    report = await run_evaluation(
        tag=args.tag,
        case_id=args.case_id,
        limit=args.limit,
        repeat=args.repeat,
    )

    print_summary(
        report
    )

    if args.repeat <= 0:
        raise RuntimeError(
            "--repeat must be greater than zero."
        )

    if not args.no_save:

        RESULTS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )

        output_path = (
            RESULTS_DIR
            / (
                "understanding_eval_"
                f"{timestamp}.json"
            )
        )

        output_path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print()
        print(
            f"Report saved to: "
            f"{output_path}"
        )


if __name__ == "__main__":

    asyncio.run(
        async_main()
    )