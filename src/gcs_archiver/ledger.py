"""SQLite ledger of every batch, so runs are resumable and auditable."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_key     TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    job_name      TEXT,
    status        TEXT NOT NULL,
    object_count  INTEGER NOT NULL,
    total_bytes   INTEGER NOT NULL,
    verified      INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (batch_key, seq)
);
"""

TERMINAL_OK = {"SUCCESS", "VERIFIED"}
COLUMNS = {"job_name", "status", "object_count", "total_bytes", "verified", "note", "updated_at"}


class Ledger:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def upsert(self, key: str, seq: int, **fields) -> None:
        if unknown := set(fields) - COLUMNS:
            raise ValueError(f"unknown ledger columns: {unknown}")
        fields["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        existing = self.get(key, seq)
        with self._db:
            if existing is None:
                cols = ["batch_key", "seq", *fields]
                self._db.execute(
                    f"INSERT INTO batches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [key, seq, *fields.values()],
                )
            else:
                sets = ", ".join(f"{k} = ?" for k in fields)
                self._db.execute(f"UPDATE batches SET {sets} WHERE batch_key = ? AND seq = ?", [*fields.values(), key, seq])

    def get(self, key: str, seq: int) -> sqlite3.Row | None:
        with closing(self._db.execute("SELECT * FROM batches WHERE batch_key = ? AND seq = ?", (key, seq))) as cur:
            return cur.fetchone()

    def all(self) -> list[sqlite3.Row]:
        with closing(self._db.execute("SELECT * FROM batches ORDER BY batch_key, seq")) as cur:
            return cur.fetchall()

    def is_done(self, key: str, seq: int) -> bool:
        row = self.get(key, seq)
        return row is not None and row["status"] in TERMINAL_OK
