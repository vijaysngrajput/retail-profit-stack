"""Mappings: what a renamed column means.

Implements LLD section 6 (Mappings). A mapping says that a column in a file means a column we
expect, for example list_price means unit_list_price. AI may suggest one. A person approves
it. Code applies it and checks the result. Approved mappings are saved and used again.
"""

import json
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
from pydantic import BaseModel, Field

from retail_profit_stack.config import EVALS_DIR
from retail_profit_stack.ingest.feeds import Places, expected_columns
from retail_profit_stack.transform.contracts import conform
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS

MAPPING_CASES_FILE = EVALS_DIR / "m5_mapping_cases.json"

# ---- Approved mappings: saved by feed, and used again without asking ---------


def read_approved_mappings(mappings_file: Path) -> dict[str, list[dict[str, str]]]:
    """Every approved mapping, by feed. An empty dictionary when none has been approved."""
    if not mappings_file.exists():
        return {}
    return json.loads(mappings_file.read_text(encoding="utf-8"))


def save_approved_mapping(mappings_file: Path, feed: str, mapping: dict[str, str]) -> None:
    """Add one approved mapping for a feed, unless it is already there."""
    approved = read_approved_mappings(mappings_file)
    if mapping not in approved.setdefault(feed, []):
        approved[feed].append(mapping)
    mappings_file.parent.mkdir(parents=True, exist_ok=True)
    mappings_file.write_text(json.dumps(approved, indent=2) + "\n", encoding="utf-8")


# ---- Reading a file with a mapping: code, no model ---------------------------


def read_file(file: Path, feed: str, mapping: dict[str, str] | None = None) -> pa.Table:
    """Read one landing file as its feed's table, in the contract's standard form.

    Columns named in the mapping are renamed. Columns that are not expected are dropped.
    conform then checks every value against the contract, and raises ContractError if one
    does not fit (for example, text in a price column).
    """
    schema = SOURCE_SCHEMAS[feed]
    with file.open(encoding="utf-8") as handle:
        file_columns = handle.readline().strip().split(",")
    names = [(mapping or {}).get(column, column) for column in file_columns]
    table = pacsv.read_csv(
        file,
        read_options=pacsv.ReadOptions(column_names=names, skip_rows=1),
        convert_options=pacsv.ConvertOptions(
            column_types=schema.arrow_schema(),
            strings_can_be_null=False,
            include_columns=[name for name in schema.names if name in names],
        ),
    )
    return conform(table, schema)


def sample_rows(file: Path, count: int = 5) -> list[dict]:
    """The first few rows of a CSV file, exactly as written, for a person or a model to read."""
    return pd.read_csv(file, dtype=str, nrows=count).to_dict(orient="records")


# ---- The AI's suggestion -----------------------------------------------------


class ColumnGuess(BaseModel):
    file_column: str = Field(description="A column name from the file that we do not expect")
    expected_column: str = Field(description="The expected column it means, or 'none'")
    reason: str = Field(description="One sentence: what in the name or the values shows this")


class MappingSuggestion(BaseModel):
    """What the model thinks the unknown columns of one file mean."""

    columns: list[ColumnGuess]
    confidence: Literal["high", "low"] = Field(
        description="low when the names give no clue, or two columns could be swapped"
    )
    note: str = Field(default="", description="Anything the person approving should check")

    def as_mapping(self) -> dict[str, str]:
        """file column -> expected column, leaving out the columns guessed as 'none'."""
        return {
            guess.file_column: guess.expected_column
            for guess in self.columns
            if guess.expected_column != "none"
        }


MAPPING_INSTRUCTIONS = """You help a data engineer load files for Kestrel Ridge Outfitters, \
a fictional retailer. A file has arrived whose column names differ from the ones we expect.

For each unknown column, say which missing expected column it most likely means, or "none" \
if it is simply an extra column. Use the column names and the sample values. Compare the \
values with the sample from an earlier file. Say confidence "low" if the names give no clue \
or two columns could be swapped. A person will check your suggestion before anything is loaded.
"""


def mapping_prompt(feed: str, file: Path, missing: list[str], unknown: list[str],
                   earlier_rows: list[dict]) -> str:  # fmt: skip
    """Everything the model is given about one changed file."""
    described = []
    for column in SOURCE_SCHEMAS[feed].columns:
        described.append(f"- {column.name} ({column.type}) {column.description}".rstrip())
    return "\n".join([
        f"Feed: {feed}",
        "Expected columns:",
        *described,
        f"Missing from this file: {', '.join(missing)}",
        f"Unknown columns in this file: {', '.join(unknown)}",
        f"First rows of this file ({file.name}):",
        json.dumps(sample_rows(file), indent=1),
        "First rows of an earlier file from the same feed, with the expected names:",
        json.dumps(earlier_rows, indent=1) if earlier_rows else "(none has been loaded yet)",
    ])  # fmt: skip


def earlier_rows(places: Places, feed: str, count: int = 5) -> list[dict]:
    """A few rows from the first loaded piece of a feed, as text."""
    pieces = sorted((places.loaded / feed).glob("*.parquet"))
    if not pieces:
        return []
    frame = pd.read_parquet(pieces[0]).head(count).astype(str)
    return frame.to_dict(orient="records")


def suggest_mapping(model, feed: str, file: Path, missing: list[str], unknown: list[str],
                    places: Places) -> tuple[MappingSuggestion, float]:  # fmt: skip
    """Ask the model what the unknown columns mean. Returns its suggestion and what the call cost."""
    prompt = mapping_prompt(feed, file, missing, unknown, earlier_rows(places, feed))
    structured = model.with_structured_output(
        MappingSuggestion, method="function_calling", include_raw=True
    )
    reply = structured.invoke([("system", MAPPING_INSTRUCTIONS), ("user", prompt)])
    usage = getattr(reply["raw"], "response_metadata", {}).get("token_usage") or {}
    suggestion = reply["parsed"]
    if suggestion is None:
        raise RuntimeError(f"The model returned no usable suggestion for {file.name}")
    return suggestion, float(usage.get("cost") or 0.0)


def mapping_problem(mapping: dict[str, str], feed: str, missing: list[str],
                    unknown: list[str]) -> str | None:  # fmt: skip
    """Why a mapping cannot be used for a file, or None when it can. Code checks this."""
    expected = expected_columns(feed)
    for column, target in mapping.items():
        if column not in unknown:
            return f"{column} is not an unknown column of this file"
        if target not in expected:
            return f"{target} is not an expected column of {feed}"
    not_covered = [column for column in missing if column not in mapping.values()]
    if not_covered:
        return f"nothing is mapped to {', '.join(not_covered)}"
    if len(set(mapping.values())) < len(mapping):
        return "two columns are mapped to the same expected column"
    return None


# ---- Scoring suggestions against the changes we planted ----------------------


def load_mapping_cases() -> dict[str, dict[str, str]]:
    """file name -> the true mapping, for each file that needs one."""
    return json.loads(MAPPING_CASES_FILE.read_text(encoding="utf-8"))


def score_suggestions(suggested: dict[str, dict[str, str]]) -> pd.DataFrame:
    """One row per file that needs a mapping: the truth, the suggestion, and right or wrong.

    suggested maps a file name to the mapping the model suggested for it.
    """
    rows = []
    for file_name, truth in load_mapping_cases().items():
        mapping = suggested.get(file_name)
        if mapping is None:
            result = "not given"
        else:
            result = "right" if mapping == truth else "wrong"
        rows.append(
            {"file_name": file_name, "truth": truth, "suggested": mapping, "result": result}
        )
    return pd.DataFrame(rows)
