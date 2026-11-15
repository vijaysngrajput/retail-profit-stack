"""The load record: every file seen, and every content that has been loaded.

Implements LLD section 5 (The load record and the loaded pieces). Two small tables in a SQLite
file. loaded_content is what makes loading safe to repeat: its key is the file's fingerprint,
and adding a fingerprint that is already there does nothing.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS files_seen (
    file_name   TEXT PRIMARY KEY,
    feed        TEXT,
    fingerprint TEXT,
    outcome     TEXT,
    rule        INTEGER,
    reason      TEXT,
    rows_loaded INTEGER,
    mapping     TEXT,
    approved_by TEXT,
    seen_at     TEXT
);
CREATE TABLE IF NOT EXISTS loaded_content (
    fingerprint TEXT PRIMARY KEY,
    file_name   TEXT
);
CREATE TABLE IF NOT EXISTS files_replaced (
    file_name   TEXT,
    fingerprint TEXT,
    replaced_at TEXT
);
"""


def connect(state_file: Path) -> sqlite3.Connection:
    """Open the SQLite file and make sure the two tables exist."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_file, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.executescript(CREATE_TABLES)
    return connection


def record_file(state_file: Path, file_name: str, feed: str, fingerprint: str, outcome: str,
                rule: int, reason: str, rows_loaded: int = 0, mapping: dict | None = None,
                approved_by: str = "") -> None:  # fmt: skip
    """Write (or replace) one file's row in files_seen."""
    connection = connect(state_file)
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO files_seen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_name, feed, fingerprint, outcome, rule, reason, rows_loaded,
                json.dumps(mapping or {}), approved_by, datetime.now().isoformat(timespec="seconds"),
            ),
        )  # fmt: skip
    connection.close()


def claim_content(state_file: Path, fingerprint: str, file_name: str) -> str:
    """Try to add a fingerprint to loaded_content. Returns the file that owns it.

    If the fingerprint is new, this file owns it. If it was already there, nothing is written
    and the earlier owner is returned. The database does this in one step, so it is safe even
    when two copies of a file are loaded at the same moment.
    """
    connection = connect(state_file)
    with connection:
        connection.execute(
            "INSERT INTO loaded_content VALUES (?, ?) ON CONFLICT (fingerprint) DO NOTHING",
            (fingerprint, file_name),
        )
        owner = connection.execute(
            "SELECT file_name FROM loaded_content WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()["file_name"]
    connection.close()
    return owner


def record_replaced(state_file: Path, file_name: str, old_fingerprint: str) -> None:
    """New in milestone 6: note that a correction replaced an earlier version of a file."""
    connection = connect(state_file)
    with connection:
        connection.execute(
            "INSERT INTO files_replaced VALUES (?, ?, ?)",
            (file_name, old_fingerprint, datetime.now().isoformat(timespec="seconds")),
        )
    connection.close()


def files_replaced(state_file: Path) -> list[dict]:
    """Every earlier version of a file that a correction replaced."""
    connection = connect(state_file)
    rows = connection.execute("SELECT * FROM files_replaced ORDER BY replaced_at").fetchall()
    connection.close()
    return [dict(row) for row in rows]


def loaded_fingerprints(state_file: Path) -> dict[str, str]:
    """Every loaded fingerprint, with the file that loaded it."""
    connection = connect(state_file)
    rows = connection.execute("SELECT fingerprint, file_name FROM loaded_content").fetchall()
    connection.close()
    return {row["fingerprint"]: row["file_name"] for row in rows}


def files_seen(state_file: Path) -> list[dict]:
    """The whole load record, in file-name order."""
    connection = connect(state_file)
    rows = connection.execute("SELECT * FROM files_seen ORDER BY file_name").fetchall()
    connection.close()
    seen = []
    for row in rows:
        entry = dict(row)
        entry["mapping"] = json.loads(entry["mapping"])
        seen.append(entry)
    return seen


def outcome_counts(state_file: Path) -> dict[str, int]:
    """How many files ended in each outcome."""
    counts: dict[str, int] = {}
    for entry in files_seen(state_file):
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
    return counts
