"""Unit tests for the DB schema-error classifier (background-sweep log escalation).

A schema fault (undefined table/column = pending migration) must classify as
persistent so sweeps log it at ``error``; transient DB errors stay ``warning``.
"""

from sqlalchemy.exc import OperationalError, ProgrammingError

from agentcore.db.errors import is_schema_error


def _programming_error() -> ProgrammingError:
    # Mirrors what asyncpg raises for a missing table, wrapped by SQLAlchemy.
    orig = Exception('relation "run_sessions" does not exist')
    return ProgrammingError("SELECT 1", {}, orig)


def test_is_schema_error_true_for_programming_error():
    assert is_schema_error(_programming_error()) is True


def test_is_schema_error_false_for_operational_error():
    # A transient connectivity blip — should stay at warning, not escalate.
    err = OperationalError("SELECT 1", {}, Exception("connection reset"))
    assert is_schema_error(err) is False


def test_is_schema_error_false_for_plain_exception():
    assert is_schema_error(RuntimeError("boom")) is False
