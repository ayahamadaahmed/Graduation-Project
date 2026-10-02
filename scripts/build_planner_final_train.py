from __future__ import annotations

import json
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

GOLD_PATH = Path(
    "data/planner/medmind_planner_train_gold.jsonl"
)

AUGMENTED_PATH = Path(
    "data/planner/"
    "medmind_planner_train_augmented_candidates.jsonl"
)

OUTPUT_PATH = Path(
    "data/planner/medmind_planner_train_final.jsonl"
)


# ============================================================
# HELPERS
# ============================================================

def read_jsonl(
    path: Path,
) -> list[dict]:

    rows: list[dict] = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            line = line.strip()

            if not line:
                continue

            try:
                rows.append(
                    json.loads(line)
                )

            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at "
                    f"{path}:{line_number}"
                ) from exc

    return rows


def write_jsonl(
    path: Path,
    rows: list[dict],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:

        for row in rows:

            file.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    gold_rows = read_jsonl(
        GOLD_PATH
    )

    augmented_rows = read_jsonl(
        AUGMENTED_PATH
    )

    # --------------------------------------------------------
    # Expected counts
    # --------------------------------------------------------

    if len(gold_rows) != 37:
        raise RuntimeError(
            f"Expected 37 Gold rows, "
            f"got {len(gold_rows)}"
        )

    if len(augmented_rows) != 370:
        raise RuntimeError(
            f"Expected 370 augmented rows, "
            f"got {len(augmented_rows)}"
        )

    # --------------------------------------------------------
    # Add source metadata to Gold rows.
    # --------------------------------------------------------

    final_gold_rows: list[dict] = []

    for row in gold_rows:

        copied = dict(
            row
        )

        copied["source"] = (
            "gold"
        )

        final_gold_rows.append(
            copied
        )

    # --------------------------------------------------------
    # Augmented rows already have:
    #
    # source = teacher_generated
    # --------------------------------------------------------

    final_rows = (
        final_gold_rows
        + augmented_rows
    )

    # --------------------------------------------------------
    # Safety check
    # --------------------------------------------------------

    if len(final_rows) != 407:
        raise RuntimeError(
            f"Expected 407 final rows, "
            f"got {len(final_rows)}"
        )

    write_jsonl(
        OUTPUT_PATH,
        final_rows,
    )

    # --------------------------------------------------------
    # Report
    # --------------------------------------------------------

    print(
        f"GOLD_ROWS="
        f"{len(final_gold_rows)}"
    )

    print(
        f"AUGMENTED_ROWS="
        f"{len(augmented_rows)}"
    )

    print(
        f"FINAL_ROWS="
        f"{len(final_rows)}"
    )

    print(
        f"OUTPUT="
        f"{OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()