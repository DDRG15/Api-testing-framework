"""Fixed, parameterized assertions over a read-only SQLite test database.

The local lab uses SQLite. PostgreSQL permissions and transaction behavior must
be verified separately before using a different database backend.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LEDGER_QUERIES = {
    "ledger_effect": (
        "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM ledger "
        "WHERE org_id = ? AND event_id = ?"
    ),
}


def _read_only_authorizer(
    action: int,
    argument: str | None,
    function: str | None,
    database: str | None,
    source: str | None,
) -> int:
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and function in {"count", "sum", "coalesce"}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class ReadOnlyOracle:
    """Execute approved named queries; never accept SQL from an assertion or LLM."""

    def __init__(
        self,
        database: Path,
        *,
        queries: Mapping[str, str] | None = None,
        max_rows: int = 1_000,
    ) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        self._database = database.resolve()
        self._queries = dict(LEDGER_QUERIES if queries is None else queries)
        self._max_rows = max_rows

    def query(self, name: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        sql = self._queries[name]
        uri = self._database.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.set_authorizer(_read_only_authorizer)
            rows = connection.execute(sql, parameters).fetchmany(self._max_rows + 1)
            if len(rows) > self._max_rows:
                raise ValueError(f"Approved query {name!r} exceeded max_rows")
            return rows
        finally:
            connection.close()

    def assert_ledger_effect(
        self,
        org_id: str,
        event_id: str,
        *,
        count: int,
        amount: int,
    ) -> None:
        actual = self.query("ledger_effect", (org_id, event_id))
        expected = [(count, amount)]
        if actual != expected:
            raise AssertionError(
                f"Persisted ledger effect for org={org_id!r}, event={event_id!r}: "
                f"expected {expected}, got {actual}"
            )
