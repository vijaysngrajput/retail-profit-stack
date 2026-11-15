"""Inspect one file and choose the rule that applies to it.

Implements LLD section 4 (Inspecting a file) and HLD section 5 (The rules for a file). One
plain function. It reads the file's bytes and its first line, and nothing else. No model is
involved: code decides what happens to a file.
"""

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

from retail_profit_stack.lineage.runs import fingerprint


@dataclass
class Inspection:
    """What code found out about one file, and what should happen to it."""

    fingerprint: str
    columns: list[str]  # the file's own column names
    missing: list[str]  # expected columns that are not in the file
    unknown: list[str]  # columns in the file that are not expected
    rule: int  # 1 to 7
    outcome: str  # already_loaded, skipped, rejected, load, or needs_mapping
    reason: str  # one sentence in plain words
    mapping: dict[str, str] = field(default_factory=dict)  # file column -> expected column
    ignored: list[str] = field(default_factory=list)  # extra columns that will be dropped

    def as_dict(self) -> dict:
        return asdict(self)


def read_header(file: Path) -> list[str]:
    """The column names on a CSV file's first line."""
    with file.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def covering_mapping(
    missing: list[str], unknown: list[str], approved: list[dict[str, str]]
) -> dict[str, str] | None:
    """The first approved mapping that maps this file's unknown columns onto every missing column."""
    for mapping in approved:
        usable = {column: target for column, target in mapping.items() if column in unknown}
        if set(usable.values()) >= set(missing):
            return usable
    return None


def inspect_file(
    file: Path,
    expected: list[str],
    loaded: dict[str, str],
    approved: list[dict[str, str]],
    loaded_names: dict[str, str] | None = None,
) -> Inspection:
    """Choose the rule for one file. The first rule that matches wins.

    loaded maps each loaded fingerprint to the file that loaded it. approved is the feed's
    approved mappings. loaded_names maps each loaded file name to its fingerprint.
    """
    print_of_file = fingerprint(file)
    columns = read_header(file)
    missing = [column for column in expected if column not in columns]
    unknown = [column for column in columns if column not in expected]
    found = {
        "fingerprint": print_of_file,
        "columns": columns,
        "missing": missing,
        "unknown": unknown,
    }

    # Rule 1: a file with this content was already loaded.
    if print_of_file in loaded:
        if loaded[print_of_file] == file.name:
            reason = "This file was loaded earlier. There is nothing to do."
            return Inspection(**found, rule=1, outcome="already_loaded", reason=reason)
        reason = f"The same content was already loaded from {loaded[print_of_file]}."
        return Inspection(**found, rule=1, outcome="skipped", reason=reason)

    # Rule 7: this name was loaded before with different content. Corrections come in milestone 6.
    if loaded_names and file.name in loaded_names:
        reason = "A file with this name but different content was already loaded."
        return Inspection(**found, rule=7, outcome="rejected", reason=reason)

    # Rules 2 and 3: every expected column is there.
    if not missing:
        if not unknown:
            reason = "Every expected column is present."
            return Inspection(**found, rule=2, outcome="load", reason=reason)
        reason = f"Every expected column is present. Extra columns ignored: {', '.join(unknown)}."
        return Inspection(**found, rule=3, outcome="load", reason=reason, ignored=unknown)

    # Rule 4: something is missing and nothing new is in its place.
    if not unknown:
        reason = f"Missing: {', '.join(missing)}. No unknown column could stand in for them."
        return Inspection(**found, rule=4, outcome="rejected", reason=reason)

    # Rules 5 and 6: something is missing and something unknown is present. Maybe a rename.
    mapping = covering_mapping(missing, unknown, approved)
    if mapping is not None:
        ignored = [column for column in unknown if column not in mapping]
        reason = f"Loaded with an approved mapping: {mapping}."
        return Inspection(**found, rule=5, outcome="load", reason=reason, mapping=mapping,
                          ignored=ignored)  # fmt: skip
    reason = f"Missing: {', '.join(missing)}. Unknown: {', '.join(unknown)}. Needs a mapping."
    return Inspection(**found, rule=6, outcome="needs_mapping", reason=reason)
