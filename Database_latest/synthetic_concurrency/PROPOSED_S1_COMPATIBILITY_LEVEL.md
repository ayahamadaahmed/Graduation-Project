# DECIDED: option B, S1 pins compatibility level 170 and collation SQL_Latin1_General_CP1_CI_AS

**Status: decided and implemented offline in `S1_create_synthetic_db.sql`
(re-pinned in `Invoke-SyntheticGate.ps1`, runner hash in `README.md`).
S1 has not run.** Running S1 still needs its own explicit approval.

## Decision

| Setting | Value | Source |
|---|---|---|
| Compatibility level | `170` | S0's report for `model` on 2026-10-26 (SQL Server 17.0.1000.7, Express Edition) |
| Collation | `SQL_Latin1_General_CP1_CI_AS` | the same S0 report, `model.collation_name` |

Both values come **only** from that S0 report. `MedMind_Audit_Final2` was not
inspected, and the synthetic database is **not** claimed to match its
compatibility level or collation. Option A (matching Final2) was not chosen
and would need its own approved catalog query.

## What S1 now does

- `CREATE DATABASE [<name>] ON PRIMARY (...) LOG ON (...) COLLATE SQL_Latin1_General_CP1_CI_AS;`
  Without `COLLATE`, a new database takes the instance's default collation,
  not `model`'s; S0 reported `model`'s only, so the collation is set
  explicitly.
- `ALTER DATABASE [<name>] SET COMPATIBILITY_LEVEL = 170;` after the other
  options (`RECOVERY SIMPLE`, `READ_COMMITTED_SNAPSHOT OFF`,
  `ALLOW_SNAPSHOT_ISOLATION OFF`, `AUTO_CLOSE OFF`).
- Verification `52110` additionally requires `is_auto_close_on = 0`,
  `compatibility_level = 170` and
  `collation_name = N'SQL_Latin1_General_CP1_CI_AS'`.
- Both values are literals in the pinned script, not runner parameters; the
  runner's S1 input is still only `@synthetic_name`.

## Why the compatibility level matters

The level selects the cardinality estimator and optimizer behavior, so it can
change plans, scans and lock footprints. That matters most for C3, which asserts
that reschedule holds overlap. Pinning it means the level no longer depends on
whatever `model` holds on the day S1 runs.

## Options that were considered

| Option | Value | Outcome |
|---|---|---|
| A. Match the real database | Final2's `compatibility_level` | Not chosen: it needs a separately approved query of Final2's catalog row, which was not run. |
| **B. Make the observed default explicit** | **170, `SQL_Latin1_General_CP1_CI_AS`** | **Chosen:** reproducible and taken from the S0 report. It says nothing about Final2. |
| C. A fixed level unrelated to S0 | for example 160 | Not chosen: the generator's dialect version controls DDL types only, not optimizer behavior. |

## Assumptions and open points

- Level 170 is valid on this instance: `model` itself is at 170 on 17.0.
- The generated schema declares no column collations, so every string
  column takes the database collation. The application code uses no
  temporary tables, so a different `tempdb` (instance) collation would not
  affect the tested paths. The instance collation itself was not reported
  by S0.
- Re-checked after S1: S4 (refusal `52413`) and `tests/synthetic_db_guard.py`
  require compatibility level `170` and collation
  `SQL_Latin1_General_CP1_CI_AS` before reading the marker or any
  application table (single source:
  `generate_synthetic_sql.SYNTHETIC_COMPATIBILITY_LEVEL` and
  `SYNTHETIC_COLLATION`). S2 and S3 do not re-check them independently;
  S1 sets and verifies both first (`52110`).
- Runtime behavior of these checks is unverified: only the read-only S0 has
  run for this workflow. S1-S4 have never executed, so the checks are
  proven offline only (SQL as text, the guard against a stub connection).
- Matching the level does not make the schema or data volume match Final2
  (see README "Schema fidelity").
