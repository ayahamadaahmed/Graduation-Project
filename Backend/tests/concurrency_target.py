"""
Which guarded database the C1-C4 concurrency tests
(tests/test_reschedule_concurrency_scratch_db.py) run against. Pure: reads
only the environment mapping it is given; never connects.

  restored   tests.scratch_db_guard     (restored scratch copy, G3-G7)
  synthetic  tests.synthetic_db_guard   (synthetic database, S1-S4)

MEDMIND_CONCURRENCY_TARGET has no default. Once the tests are opted in
(MEDMIND_DB_INTEGRATION=1 and the target's own opt-in), a missing, unknown
or mismatched target is a failure, never a fallback. Without an opt-in the
tests are skipped. Whichever guard is selected still performs all of its own
checks (names, server, marker, token, ...) on every connection.
"""

from types import SimpleNamespace

TARGET_VARIABLE = "MEDMIND_CONCURRENCY_TARGET"
OPT_IN = {"restored": "MEDMIND_SCRATCH_CONCURRENCY", "synthetic": "MEDMIND_SYNTHETIC_CONCURRENCY"}


def select(environ):
    """SimpleNamespace(target, skip, failure): exactly one of `skip` and
    `failure` is set, or neither and `target` is "restored" or "synthetic"."""
    opted = sorted(target for target, variable in OPT_IN.items() if environ.get(variable) == "1")
    if environ.get("MEDMIND_DB_INTEGRATION") != "1" or not opted:
        return SimpleNamespace(target=None, failure=None, skip=(
            "Guarded concurrency database only: set MEDMIND_DB_INTEGRATION=1, "
            f"{TARGET_VARIABLE}=restored|synthetic and the matching "
            "MEDMIND_SCRATCH_CONCURRENCY=1 or MEDMIND_SYNTHETIC_CONCURRENCY=1."))
    if len(opted) > 1:
        return SimpleNamespace(target=None, skip=None, failure=(
            "MEDMIND_SCRATCH_CONCURRENCY and MEDMIND_SYNTHETIC_CONCURRENCY are both set; set exactly one"))
    target = environ.get(TARGET_VARIABLE)
    if target not in OPT_IN:
        return SimpleNamespace(target=None, skip=None, failure=(
            f"{TARGET_VARIABLE} must be exactly 'restored' or 'synthetic' (no default)"))
    if OPT_IN[target] != OPT_IN[opted[0]]:
        return SimpleNamespace(target=None, skip=None, failure=(
            f"{TARGET_VARIABLE}={target} requires {OPT_IN[target]}=1, not {OPT_IN[opted[0]]}=1"))
    return SimpleNamespace(target=target, skip=None, failure=None)
