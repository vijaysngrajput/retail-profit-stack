"""Versions of the analyst: its instructions and its model.

Implements LLD section 8 (Analyst versions). Version 1 is the analyst as the code defines it.
Later versions are proposed by the improver, approved by a person, and saved here. One version
is current. Rolling back is setting an earlier version as current.
"""

import json
from pathlib import Path

from retail_profit_stack.agent import RUN_TOOL_RULE, SYSTEM_PROMPT
from retail_profit_stack.config import DEFAULT_MODEL, VERSIONS_FILE


def version_one() -> dict:
    """The analyst as the code defines it. It is never stored in the file."""
    return {
        "version": 1,
        "instructions": SYSTEM_PROMPT + RUN_TOOL_RULE,
        "model": DEFAULT_MODEL,
        "reason": "The analyst as milestone 5 left it",
    }


def _read(versions_file: Path) -> dict:
    if not versions_file.exists():
        return {"current": 1, "versions": []}
    return json.loads(versions_file.read_text(encoding="utf-8"))


def _write(versions_file: Path, saved: dict) -> None:
    versions_file.parent.mkdir(parents=True, exist_ok=True)
    versions_file.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")


def read_versions(versions_file: Path = VERSIONS_FILE) -> list[dict]:
    """Every version, oldest first. Version 1 always comes first."""
    return [version_one(), *_read(versions_file)["versions"]]


def current_version(versions_file: Path = VERSIONS_FILE) -> dict:
    """The version the analyst uses now."""
    number = _read(versions_file)["current"]
    return next(v for v in read_versions(versions_file) if v["version"] == number)


def save_version(
    instructions: str, model: str, reason: str, versions_file: Path = VERSIONS_FILE
) -> dict:
    """Add a new version. It does not become current until set_current is called."""
    saved = _read(versions_file)
    version = {
        "version": len(saved["versions"]) + 2,
        "instructions": instructions,
        "model": model,
        "reason": reason,
    }
    saved["versions"].append(version)
    _write(versions_file, saved)
    return version


def set_current(number: int, versions_file: Path = VERSIONS_FILE) -> None:
    """Make a version current. Setting an earlier number is a rollback."""
    saved = _read(versions_file)
    if number not in [v["version"] for v in read_versions(versions_file)]:
        raise ValueError(f"There is no version {number}")
    saved["current"] = number
    _write(versions_file, saved)
