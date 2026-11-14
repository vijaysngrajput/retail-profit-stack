"""Helpers for the milestone 3 lab notebooks.

Each notebook teaches one idea. Code that is not about that idea (loading data, showing
documents, connecting to a model) lives here so the notebooks can stay short. The section
headings say which notebook uses each piece.

The notebooks also import this milestone's production package, retail_profit_stack.
"""

import json
import os
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from IPython.display import Markdown, display
from openai import OpenAI

MILESTONE = Path(__file__).resolve().parent.parent
DOCS = MILESTONE / "docs"
SOURCE = MILESTONE / "data" / "source"
MOCK = MILESTONE / "data" / "mock"
RESULTS = Path(__file__).resolve().parent / "results"

# Let the notebooks import the production package, which is in this milestone's folder.
if str(MILESTONE) not in sys.path:
    sys.path.insert(0, str(MILESTONE))

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"

reporting_period = json.loads((MOCK / "reporting_period.json").read_text(encoding="utf-8"))
LAST_MONTH = reporting_period["current_month"]
PREVIOUS_MONTH = reporting_period["previous_month"]

MAIN_QUESTION = (
    "Which products and categories generated the most contribution profit last month, "
    "what changed, and how confident should I be in those numbers?"
)


# ---- Plumbing: showing documents and saving results (not about AI) ----------


def get_section(document: str, heading: str) -> str:
    """Return one '## ' section of a design document as text."""
    text = (DOCS / document).read_text(encoding="utf-8")
    pattern = rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError(f"No section '{heading}' in {document}")
    return match.group(1).strip()


def show_doc(document: str, heading: str) -> None:
    """Display one section of a design document (BRD.md, HLD.md, or LLD.md)."""
    note = f"*(Diagram: open `docs/{document}` to see it.)*"
    body = re.sub(r"```mermaid.*?```", note, get_section(document, heading), flags=re.DOTALL)
    display(Markdown(f"> **From `docs/{document}`: {heading}**\n\n{body}"))


def show_code(code: str, language: str = "python") -> None:
    """Display code with syntax colouring. language is 'sql', 'pandas', or 'python'."""
    display(Markdown(f"```{'sql' if language == 'sql' else 'python'}\n{code.strip()}\n```"))


def save_result(name: str, data) -> None:
    """Save something from this notebook so a later notebook can load it."""
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved results/{name}.json")


def load_result(name: str, required_from: str | None = None):
    """Load something an earlier notebook saved. Returns None if it is not there."""
    path = RESULTS / f"{name}.json"
    if not path.exists():
        if required_from:
            raise FileNotFoundError(f"results/{name}.json is missing. Run {required_from} first.")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---- The business's records (explored in notebook 1; LLD section 3) ---------

DATE_COLUMNS = {
    "orders": ["order_date"], "refunds": ["refund_date"],
    "shipments": ["ship_date"], "payment_fees": ["capture_date"],
}  # fmt: skip
SOURCE_TABLES = [
    "products", "orders", "order_items", "refunds", "shipments", "payment_fees", "product_costs",
]  # fmt: skip


def load_source_tables() -> dict[str, pd.DataFrame]:
    """Every source table as a pandas DataFrame, with dates as real dates."""
    return {
        name: pd.read_csv(SOURCE / f"{name}.csv", parse_dates=DATE_COLUMNS.get(name, []))
        for name in SOURCE_TABLES
    }


# ---- Running SQL on tables, and two checks written by hand (notebook 2) ------


def run_sql(sql: str, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Run a SQL query over pandas DataFrames, using DuckDB, and return a DataFrame."""
    database = duckdb.connect(":memory:")
    for name, frame in tables.items():
        database.register(name, frame)
    return database.sql(sql).df()


def add_row_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the table with a row_number column: 1 for the first row, 2 for the next."""
    numbered = frame.copy()
    numbered["row_number"] = range(1, len(numbered) + 1)
    return numbered


# The two checks the learner writes by hand in notebook 2. Production has the full versions
# in retail_profit_stack/quality/sql/. A test compares these with production.

DUPLICATE_LINES_SQL = """
SELECT row_number, order_item_id, product_id, copy_number
FROM (
    SELECT *,
           row_number() OVER (
               PARTITION BY order_item_id, order_id, product_id, quantity,
                            unit_list_price, discount_amount
               ORDER BY row_number
           ) AS copy_number
    FROM order_items
)
WHERE copy_number > 1
ORDER BY row_number
"""

REFUND_EXCEEDS_LINE_SQL = """
WITH line_values AS (
    SELECT DISTINCT order_item_id,
           quantity * unit_list_price - discount_amount AS line_value
    FROM order_items
)
SELECT r.row_number, r.refund_id, r.product_id, r.refund_amount, l.line_value
FROM refunds AS r JOIN line_values AS l ON l.order_item_id = r.order_item_id
WHERE r.refund_amount > l.line_value + 0.005
ORDER BY r.row_number
"""


# ---- Connecting to a model (notebooks 4 to 6) -------------------------------


def connect(timeout: int = 120, max_retries: int = 5) -> tuple[OpenAI, str]:
    """Return an OpenRouter client and the default model name, using the key in the .env file."""
    load_dotenv(find_dotenv(usecwd=True), override=True)
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("MODEL_NAME", DEFAULT_MODEL)
    if not api_key:
        raise RuntimeError(
            "No OpenRouter API key found. Copy .env.example to .env in the project root, "
            "add your OPENROUTER_API_KEY, and run this cell again."
        )
    print(f"Connected to OpenRouter. Default model: {model}")
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL, api_key=api_key, timeout=timeout, max_retries=max_retries
    )
    return client, model


# ---- The answer, and the answer key (notebooks 3 and 6) ---------------------


def _money(value, kind: str = "value") -> str:
    if value is None:
        return "unavailable"
    sign = ("+" if value >= 0 else "-") if kind == "change" else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def same_value(left, right) -> bool:
    """True when two figures agree to the cent, or are both unavailable."""
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= 0.005


def check_key_against_calculated(answer_key: dict) -> pd.DataFrame:
    """Look up each line of the answer key in the calculated tables.

    The figures are read through the production tools, the same way the analyst reads them.
    """
    from retail_profit_stack import tools

    table = []
    for line in answer_key["figures"]:
        group_by = "product" if line["entity_id"].startswith("P0") else "category"
        if line["kind"] == "value":
            rows = tools.query_profit(line["month"], group_by, line["metric"]).rows
            found = {row.entity_id: getattr(row, line["metric"]) for row in rows}
        else:
            rows = tools.compare_profit(
                line["month"], PREVIOUS_MONTH, group_by, line["metric"]
            ).rows
            found = {row.entity_id: row.change for row in rows}
        calculated = found[line["entity_id"]]
        table.append({
            "What": line["what"],
            "Answer key (by hand)": _money(line["value"], line["kind"]),
            "Calculated (by the pipeline)": _money(calculated, line["kind"]),
            "Same?": "yes" if same_value(calculated, line["value"]) else "NO",
        })  # fmt: skip
    return pd.DataFrame(table)


def show_answer(answer) -> None:
    """Display an analyst's answer the way a retail leader would read it."""
    lines = [f"### {answer.headline}", answer.narrative, ""]
    if answer.decline_reason:
        lines.append(f"**Declined:** {answer.decline_reason}")
    if answer.figures:
        lines.append("| Figure | Value | Month |\n|---|---|---|")
        for figure in answer.figures:
            value = (
                f"{figure.value:+.1f}%"
                if figure.kind == "pct_change" and figure.value is not None
                else _money(figure.value, figure.kind)
            )
            lines.append(f"| {figure.label} | {value} | {figure.month} |")
        lines.append("")
    lines += [f"- **Caveat {caveat.flag_id or ''}:** {caveat.text}" for caveat in answer.caveats]
    if answer.confidence:
        reasons = " ".join(answer.confidence.reasons)
        lines.append(f"\n**Confidence: {answer.confidence.level}.** {reasons}")
    display(Markdown("\n".join(lines)))
