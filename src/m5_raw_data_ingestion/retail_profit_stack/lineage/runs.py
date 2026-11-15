"""Run ids, fingerprints, run records, and the history file.

Implements LLD section 3 (Run records). A run is one calculation of all the figures. Every run
gets an id, one entry in run_history.json, and its own folder of tables. Nothing is overwritten.
"""

import hashlib
import json
from pathlib import Path

from retail_profit_stack.config import WAREHOUSE_DIR

HISTORY_FILE_NAME = "run_history.json"


def fingerprint(file: Path) -> str:
    """A short code worked out from a file's content.

    The same content always gives the same code. Change one character and the code changes.
    It is the first 12 characters of the file's SHA-256 hash.
    """
    return hashlib.sha256(file.read_bytes()).hexdigest()[:12]


def read_history(warehouse_dir: Path = WAREHOUSE_DIR) -> list[dict]:
    """Every run record, oldest first. An empty list when no run has been made."""
    history_file = warehouse_dir / HISTORY_FILE_NAME
    if not history_file.exists():
        return []
    return json.loads(history_file.read_text(encoding="utf-8"))


def next_run_id(warehouse_dir: Path = WAREHOUSE_DIR) -> str:
    """RUN-0001 for the first run, then RUN-0002, and so on."""
    history = read_history(warehouse_dir)
    if not history:
        return "RUN-0001"
    last_number = int(history[-1]["run_id"].removeprefix("RUN-"))
    return f"RUN-{last_number + 1:04d}"


def latest_run_id(warehouse_dir: Path = WAREHOUSE_DIR) -> str | None:
    """The id of the newest run, or None when there is no run yet."""
    history = read_history(warehouse_dir)
    return history[-1]["run_id"] if history else None


def run_folder(run_id: str, warehouse_dir: Path = WAREHOUSE_DIR) -> Path:
    """The folder that holds one run's tables."""
    return warehouse_dir / "runs" / run_id


def read_run_record(run_id: str, warehouse_dir: Path = WAREHOUSE_DIR) -> dict:
    """One run's record from the history file."""
    for record in read_history(warehouse_dir):
        if record["run_id"] == run_id:
            return record
    raise KeyError(f"No run called {run_id} in the run history")


def save_run_record(record: dict, warehouse_dir: Path = WAREHOUSE_DIR) -> None:
    """Add one run record to the end of the history file."""
    history = read_history(warehouse_dir)
    history.append(record)
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    history_file = warehouse_dir / HISTORY_FILE_NAME
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")


def input_fingerprints(source_dir: Path, row_counts: dict[str, int]) -> dict[str, dict]:
    """For each source table: its rows, how many files it was built from, and a fingerprint.

    Changed in milestone 5. A table is now built from loaded pieces, so its fingerprint is
    worked out from the names and fingerprints of its pieces. Loading one more file changes it.
    """
    inputs = {}
    for table_name, rows in row_counts.items():
        pieces = sorted((source_dir / table_name).glob("*.parquet"))
        described = "".join(f"{piece.name}:{fingerprint(piece)};" for piece in pieces)
        combined = hashlib.sha256(described.encode("utf-8")).hexdigest()[:12]
        inputs[table_name] = {"rows": rows, "files": len(pieces), "fingerprint": combined}
    return inputs


def code_fingerprints(code_files: dict[str, Path]) -> dict[str, str]:
    """The fingerprint of each transformation file and each check file."""
    return {name: fingerprint(file) for name, file in code_files.items()}
