"""Offline tests for the DB integration safety guard (no SQL Server).

unsafe_engine_target() must accept only the approved audit target, read from
the engine's own URL, and both DB fixtures must apply it before
engine.connect(). Engines here are built with create_engine(), which does not
connect, or are fakes whose connect() fails the test if reached too early.
All credentials are fake.
"""

from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

import app.db.session as db_session_module
import tests.test_booking_concurrency_db as concurrency
import tests.test_lab_booking_without_doctor_db as lab
from app.core.config import Settings, get_settings

APPROVED = {"db_server": r"localhost\SQLEXPRESS", "db_name": "MedMind_Audit_Final2", "db_trusted_connection": True}
FAKE_PASSWORD = "fake-sql-password-not-real"


def _engine(**overrides):
    """A real (unconnected) SQLAlchemy engine built exactly like app/db/session.py."""
    values = {**APPROVED, **overrides}
    return create_engine(Settings(_env_file=None, **values).database_url)


def _url_engine(url):
    return SimpleNamespace(url=make_url(url))


def _odbc_url(odbc):
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)


APPROVED_ODBC = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
                 "DATABASE=MedMind_Audit_Final2;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes")


# ============================================================ unsafe_engine_target


def test_the_approved_target_is_accepted():
    assert lab.unsafe_engine_target(_engine()) is None
    assert lab.unsafe_engine_target(_url_engine(_odbc_url(APPROVED_ODBC))) is None


@pytest.mark.parametrize(
    "db_name",
    ["MedMind_Booking_DB", "medmind_booking_db", "MEDMIND_BOOKING_DB", "medmind_audit_final2",
     "MEDMIND_AUDIT_FINAL2", "MedMind_Audit_Final3", "MedMind_Audit", "master", ""],
)
def test_other_databases_are_rejected(db_name):
    assert lab.unsafe_engine_target(_engine(db_name=db_name)) == "not the approved database"


@pytest.mark.parametrize(
    "db_server", [r"otherhost\SQLEXPRESS", r"LOCALHOST\SQLEXPRESS", "localhost", "tcp:prod.example.com,1433", ""],
)
def test_other_servers_are_rejected(db_server):
    assert lab.unsafe_engine_target(_engine(db_server=db_server)) == "not the approved server"


def test_sql_login_is_rejected_without_echoing_the_password():
    engine = _engine(db_trusted_connection=False, db_user="fake_user", db_password=FAKE_PASSWORD)

    reason = lab.unsafe_engine_target(engine)

    assert reason == "unexpected ODBC keys"  # UID/PWD instead of Trusted_Connection
    assert FAKE_PASSWORD not in reason and "fake_user" not in reason


@pytest.mark.parametrize(
    "overrides, reason",
    [
        # A second DATABASE key smuggled through DB_NAME.
        ({"db_name": "MedMind_Audit_Final2;DATABASE=MedMind_Booking_DB"}, "duplicate ODBC keys"),
        # An alias key smuggled through DB_SERVER.
        ({"db_server": r"localhost\SQLEXPRESS;Initial Catalog=MedMind_Booking_DB"}, "unexpected ODBC keys"),
    ],
)
def test_connection_string_injection_is_rejected(overrides, reason):
    assert lab.unsafe_engine_target(_engine(**overrides)) == reason


@pytest.mark.parametrize(
    "url, reason",
    [
        ("sqlite://", "not an mssql+pyodbc engine"),
        ("mssql+pyodbc://fake_user:" + FAKE_PASSWORD + "@prod-host/MedMind_Audit_Final2?driver=ODBC+Driver+18",
         "the engine URL must carry only odbc_connect"),
        ("mssql+pyodbc://somehost/?odbc_connect=" + quote_plus(APPROVED_ODBC),
         "the engine URL must carry only odbc_connect"),
        (_odbc_url(APPROVED_ODBC) + "&driver=other", "the engine URL must carry only odbc_connect"),
        (_odbc_url(APPROVED_ODBC) + "&odbc_connect=" + quote_plus("SERVER=x;DATABASE=MedMind_Booking_DB"),
         "odbc_connect must appear once"),
        (_odbc_url("DRIVER={unterminated;SERVER=localhost\\SQLEXPRESS"), "unparseable ODBC connection string"),
        (_odbc_url(APPROVED_ODBC.replace("Trusted_Connection=yes", "Trusted_Connection=no")),
         "not a Windows Trusted Connection"),
        (_odbc_url(APPROVED_ODBC.replace(";Trusted_Connection=yes", "")), "not a Windows Trusted Connection"),
        (_odbc_url(APPROVED_ODBC + ";Address=prod-host"), "unexpected ODBC keys"),
    ],
)
def test_unexpected_engine_urls_are_rejected(url, reason):
    result = lab.unsafe_engine_target(_url_engine(url))

    assert result == reason
    assert FAKE_PASSWORD not in result


def test_braced_values_and_key_case_are_parsed_like_odbc():
    pairs = lab._odbc_pairs("driver={A;B}}C};Server=s;DATABASE = d ;")

    assert pairs == [("driver", "A;B}C"), ("Server", "s"), ("DATABASE", "d")]


# ============================================================ the fixtures check before connecting


class FakeEngine:
    def __init__(self, url):
        self.url = make_url(url) if isinstance(url, str) else url
        self.connects = 0

    def connect(self):
        self.connects += 1
        raise RuntimeError("connect() reached")


@pytest.fixture
def approved_settings(monkeypatch):
    monkeypatch.setenv("DB_SERVER", r"localhost\SQLEXPRESS")
    monkeypatch.setenv("DB_NAME", "MedMind_Audit_Final2")
    monkeypatch.setenv("DB_TRUSTED_CONNECTION", "true")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _open_db_session():
    generator = lab.db_session.__wrapped__()
    return next(generator)


def _open_guarded_session():
    with concurrency.guarded_session():
        pass


OPENERS = [_open_db_session, _open_guarded_session]


@pytest.mark.parametrize("open_session", OPENERS)
@pytest.mark.parametrize(
    "engine_url",
    [
        _odbc_url(APPROVED_ODBC.replace("MedMind_Audit_Final2", "MedMind_Booking_DB")),
        _odbc_url(APPROVED_ODBC.replace("MedMind_Audit_Final2", "medmind_audit_final2")),
        _odbc_url(APPROVED_ODBC.replace(r"localhost\SQLEXPRESS", r"prod-host\SQLEXPRESS")),
        _odbc_url(APPROVED_ODBC.replace("Trusted_Connection=yes", "UID=fake_user;PWD=" + FAKE_PASSWORD)),
    ],
)
def test_fixtures_refuse_an_unsafe_engine_before_connecting(approved_settings, open_session, engine_url):
    # Fresh settings say "approved", but the already-built engine does not.
    engine = FakeEngine(engine_url)
    approved_settings.setattr(db_session_module, "engine", engine)

    with pytest.raises(pytest.fail.Exception, match="SAFETY STOP: the engine does not target") as stop:
        open_session()

    assert engine.connects == 0
    assert FAKE_PASSWORD not in str(stop.value)


@pytest.mark.parametrize("open_session", OPENERS)
def test_fixtures_reach_connect_only_for_the_approved_engine(approved_settings, open_session):
    engine = FakeEngine(_odbc_url(APPROVED_ODBC))
    approved_settings.setattr(db_session_module, "engine", engine)

    with pytest.raises(RuntimeError, match="connect\\(\\) reached"):
        open_session()

    assert engine.connects == 1  # guard passed; the post-connect DB_NAME() check would run next


@pytest.mark.parametrize("open_session", OPENERS)
def test_the_settings_check_still_runs_first(approved_settings, open_session):
    approved_settings.setenv("DB_NAME", "MedMind_Booking_DB")
    get_settings.cache_clear()
    engine = FakeEngine(_odbc_url(APPROVED_ODBC))
    approved_settings.setattr(db_session_module, "engine", engine)

    with pytest.raises(pytest.fail.Exception, match="SAFETY STOP"):
        open_session()

    assert engine.connects == 0


def test_the_post_connect_db_name_check_is_still_in_both_fixtures():
    import inspect

    for function in (lab.db_session.__wrapped__, concurrency.guarded_session):
        source = inspect.getsource(function)
        assert source.index("unsafe_engine_target(engine)") < source.index("engine.connect()")
        assert source.index("engine.connect()") < source.index('SELECT DB_NAME()')
        assert 'join_transaction_mode="create_savepoint"' in source
        assert "outer.rollback()" in source
