"""
Offline tests of the C1-C4 guard switch (tests/concurrency_target.py and its
use in tests/test_reschedule_concurrency_scratch_db.py). No database:
Engine.connect is patched to fail, and the test module is only imported (its
tests are never run). The synthetic guard is exercised with the stub
connection from tests/test_synthetic_db_offline.py.
"""

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy
from _pytest.outcomes import Failed

from app.core.config import get_settings
from tests import concurrency_target, scratch_db_guard, synthetic_db_guard
from tests import test_synthetic_db_offline as synth

ROOT = Path(__file__).resolve().parents[2]
CONCURRENCY_TEST = ROOT / "Backend" / "tests" / "test_reschedule_concurrency_scratch_db.py"
SWITCH_VARIABLES = ("MEDMIND_DB_INTEGRATION", "MEDMIND_CONCURRENCY_TARGET", "MEDMIND_SCRATCH_CONCURRENCY",
                    "MEDMIND_SYNTHETIC_CONCURRENCY")


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def refuse(self, *args, **kwargs):
        raise AssertionError("a database connection was attempted")

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse)
    for variable in SWITCH_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    yield
    get_settings.cache_clear()


# ============================================================ selection (pure)


RESTORED = {"MEDMIND_DB_INTEGRATION": "1", "MEDMIND_CONCURRENCY_TARGET": "restored", "MEDMIND_SCRATCH_CONCURRENCY": "1"}
SYNTHETIC = {"MEDMIND_DB_INTEGRATION": "1", "MEDMIND_CONCURRENCY_TARGET": "synthetic",
             "MEDMIND_SYNTHETIC_CONCURRENCY": "1"}


@pytest.mark.parametrize("environ, target", [(RESTORED, "restored"), (SYNTHETIC, "synthetic")])
def test_an_explicit_matching_target_is_selected(environ, target):
    selected = concurrency_target.select(environ)
    assert (selected.target, selected.skip, selected.failure) == (target, None, None)


@pytest.mark.parametrize("environ", [
    {}, {"MEDMIND_CONCURRENCY_TARGET": "synthetic"},
    {"MEDMIND_DB_INTEGRATION": "1", "MEDMIND_CONCURRENCY_TARGET": "synthetic"},
    {"MEDMIND_SYNTHETIC_CONCURRENCY": "1", "MEDMIND_CONCURRENCY_TARGET": "synthetic"},
    {**SYNTHETIC, "MEDMIND_DB_INTEGRATION": "0"}, {**SYNTHETIC, "MEDMIND_SYNTHETIC_CONCURRENCY": "true"},
])
def test_without_an_opt_in_the_tests_are_skipped_never_run(environ):
    selected = concurrency_target.select(environ)
    assert selected.target is None and selected.failure is None and "MEDMIND_CONCURRENCY_TARGET" in selected.skip


@pytest.mark.parametrize("environ, reason", [
    ({**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": ""}, "no default"),
    ({k: v for k, v in SYNTHETIC.items() if k != "MEDMIND_CONCURRENCY_TARGET"}, "no default"),
    ({k: v for k, v in RESTORED.items() if k != "MEDMIND_CONCURRENCY_TARGET"}, "no default"),
    ({**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": "Synthetic"}, "no default"),
    ({**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": "synthetic "}, "no default"),
    ({**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": "MedMind_Audit_Final2"}, "no default"),
    ({**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": "restored"}, "requires MEDMIND_SCRATCH_CONCURRENCY=1"),
    ({**RESTORED, "MEDMIND_CONCURRENCY_TARGET": "synthetic"}, "requires MEDMIND_SYNTHETIC_CONCURRENCY=1"),
    ({**SYNTHETIC, "MEDMIND_SCRATCH_CONCURRENCY": "1"}, "both set"),
])
def test_a_missing_unknown_mismatched_or_ambiguous_target_fails(environ, reason):
    selected = concurrency_target.select(environ)
    assert selected.target is None and selected.skip is None and reason in selected.failure


# ============================================================ the test module, imported under each environment


def _import_concurrency_module(monkeypatch, environ):
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    name = "_offline_import_of_test_reschedule_concurrency"
    spec = importlib.util.spec_from_file_location(name, CONCURRENCY_TEST)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # imports only; defines tests, runs none
    finally:
        sys.modules.pop(name, None)
    return module


def test_the_synthetic_target_binds_the_synthetic_guard(monkeypatch):
    module = _import_concurrency_module(monkeypatch, SYNTHETIC)
    assert module.CONCURRENCY.target == "synthetic"
    assert module.scratch_connection is synthetic_db_guard.synthetic_connection
    assert module.scratch_open_transaction is synthetic_db_guard.synthetic_open_transaction
    assert module.scratch_committing_session is synthetic_db_guard.synthetic_committing_session
    assert module.pytestmark.args == (False,)  # not skipped


def test_the_restored_target_binds_the_unchanged_restored_guard(monkeypatch):
    module = _import_concurrency_module(monkeypatch, RESTORED)
    assert module.CONCURRENCY.target == "restored"
    assert module.scratch_connection is scratch_db_guard.scratch_connection
    assert module.scratch_open_transaction is scratch_db_guard.scratch_open_transaction
    assert module.scratch_committing_session is scratch_db_guard.scratch_committing_session
    assert module.pytestmark.args == (False,)


def test_without_opt_in_the_module_is_skipped(monkeypatch):
    module = _import_concurrency_module(monkeypatch, {})
    assert module.pytestmark.args == (True,) and "MEDMIND_CONCURRENCY_TARGET" in module.pytestmark.kwargs["reason"]


@pytest.mark.parametrize("environ", [
    {k: v for k, v in SYNTHETIC.items() if k != "MEDMIND_CONCURRENCY_TARGET"},
    {**SYNTHETIC, "MEDMIND_CONCURRENCY_TARGET": "restored"},
    {**SYNTHETIC, "MEDMIND_SCRATCH_CONCURRENCY": "1"},
])
def test_an_opted_in_module_without_a_valid_target_fails_at_import(monkeypatch, environ):
    with pytest.raises(Failed, match="SAFETY STOP"):
        _import_concurrency_module(monkeypatch, environ)


def test_the_target_failure_comes_before_any_guard_import():
    source = CONCURRENCY_TEST.read_text(encoding="utf-8")
    fail = source.index("pytest.fail(f\"SAFETY STOP: {CONCURRENCY.failure}.\"")
    assert source.index("CONCURRENCY = concurrency_target.select(os.environ)") < fail
    assert fail < source.index("from tests.synthetic_db_guard import (")
    assert fail < source.index("from tests.scratch_db_guard import (")
    assert "MEDMIND_SCRATCH_CONCURRENCY\") != \"1\"" not in source  # the old single-target skip is gone


# ============================================================ the switched-in synthetic guard (stub connection)


def _switched_synthetic_connection(monkeypatch, stub):
    module = _import_concurrency_module(monkeypatch, SYNTHETIC)
    engine = SimpleNamespace(connect=lambda: stub)
    monkeypatch.setattr(synthetic_db_guard, "require_synthetic_target",
                        lambda: (engine, synth.NAME, synthetic_db_guard.token_sha256(synth.TOKEN)))
    return module.scratch_connection


def test_the_switched_guard_accepts_the_verified_synthetic_database(monkeypatch):
    stub = synth._StubConnection()
    with _switched_synthetic_connection(monkeypatch, stub)(2000) as connection:
        assert connection is stub
    assert stub.kinds == ["set"] + synth.IDENTITY_KINDS + synth.CONTENT_KINDS + ["set"]


@pytest.mark.parametrize("case", ["server", "database_name", "other_synthetic", "files_of_final2", "restored",
                                  "level_160", "collation_latin1"])
def test_the_switched_guard_refuses_a_wrong_server_or_database(monkeypatch, case):
    stub = synth._StubConnection(**synth.BAD_IDENTITY[case])
    with pytest.raises(Failed, match="SYNTHETIC SAFETY STOP"):
        with _switched_synthetic_connection(monkeypatch, stub)(2000):
            raise AssertionError("an unverified connection was yielded")
    assert stub.kinds == ["set"] + synth.IDENTITY_KINDS  # nothing inside the database was read


@pytest.mark.parametrize("override, reason", [
    ({"marker_id": [(None,)]}, "no synthetic marker"),
    ({"marker": []}, "exactly one row"),
    ({"marker": [(synth.NAME, "synthetic", "synthetic-v1", "0" * 64, synth.fx.MANIFEST_SHA256)]},
     "this run's token"),
    ({"marker": [(synth.NAME, "synthetic", "synthetic-v1", synthetic_db_guard.token_sha256(synth.TOKEN), "0" * 64)]},
     "manifest"),
    ({"marker": [("MedMind_SynthConc_20261026_ffffff", "synthetic", "synthetic-v1",
                  synthetic_db_guard.token_sha256(synth.TOKEN), synth.fx.MANIFEST_SHA256)]}, "does not describe"),
])
def test_the_switched_guard_refuses_a_missing_or_mismatched_marker_or_token(monkeypatch, override, reason):
    stub = synth._StubConnection(**override)
    with pytest.raises(Failed, match=reason):
        with _switched_synthetic_connection(monkeypatch, stub)(2000):
            raise AssertionError("an unverified connection was yielded")
    assert "SET LOCK_TIMEOUT 2000" not in stub.executed


# ============================================================ unchanged protections


def test_the_selector_is_pure_and_the_restored_guard_is_unchanged():
    tree = ast.parse(Path(concurrency_target.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert [(node.module, [a.name for a in node.names]) for node in imports] == [("types", ["SimpleNamespace"])]
    assert scratch_db_guard.SOURCE_DATABASE == "MedMind_Audit_Final2"
    runner = ROOT / "Database_latest" / "scratch_concurrency" / "Invoke-ScratchGate.ps1"
    assert hashlib.sha256(runner.read_bytes()).hexdigest() == (
        "f9466ca17101b3377ac1694ec55a949036fe98bf56fbb834571307551afc9078")
