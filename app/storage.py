from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


class InvoiceStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('needs_review', 'approved', 'rejected')),
                    draft_json TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, invoice_id: str, source_id: str, draft: dict[str, Any], raw_text: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO invoices (id, source_id, status, draft_json, raw_text)
                VALUES (?, ?, 'needs_review', ?, ?)
                """,
                (invoice_id, source_id, json.dumps(draft), raw_text),
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM invoices")

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM invoices"
        parameters: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY created_at DESC, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._as_dict(row) for row in rows]

    def get(self, invoice_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
            ).fetchone()
        return self._as_dict(row) if row is not None else None

    def get_by_source_id(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM invoices WHERE source_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()
        return self._as_dict(row) if row is not None else None

    def decide(self, invoice_id: str, status: str, draft: dict[str, Any] | None = None) -> bool:
        if status not in {"approved", "rejected"}:
            raise ValueError(f"Invalid invoice status: {status}")
        with self._connect() as connection:
            if draft is None:
                result = connection.execute(
                    """
                    UPDATE invoices SET status = ?
                    WHERE id = ? AND status = 'needs_review'
                    """,
                    (status, invoice_id),
                )
            else:
                result = connection.execute(
                    """
                    UPDATE invoices SET status = ?, draft_json = ?
                    WHERE id = ? AND status = 'needs_review'
                    """,
                    (status, json.dumps(draft), invoice_id),
                )
        return result.rowcount == 1

    @staticmethod
    def _as_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source_id": row["source_id"],
            "status": row["status"],
            "draft": json.loads(row["draft_json"]),
            "raw_text": row["raw_text"],
            "created_at": row["created_at"],
        }
