"""Helpers for the milestone 2 lab notebooks.

Each notebook teaches one idea. Code that is not about that idea (loading data, displaying
tables, running many model calls at once) lives here so the notebooks can stay short. The
section headings say which notebook uses each piece.

The notebooks also import this milestone's production package, retail_profit_stack. Running
code that a model wrote needs care, and the careful version is the production one.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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


# ---- The business's records (explored in notebook 1; LLD section 2) ---------

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


# ---- One calculation, two engines (written by hand in notebook 2) -----------


def sales_pandas(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The sales transformation in pandas, as written by hand in notebook 2."""
    lines = inputs["order_items"].merge(inputs["orders"], on="order_id")
    lines = lines[lines["status"] != "cancelled"]
    lines["month"] = lines["order_date"].dt.strftime("%Y-%m")
    lines["gross"] = lines["quantity"] * lines["unit_list_price"]
    return lines.groupby(["month", "product_id"], as_index=False).agg(
        units_sold=("quantity", "sum"),
        gross_sales=("gross", "sum"),
        discounts=("discount_amount", "sum"),
    )


SALES_SQL = """
SELECT
    strftime(o.order_date, '%Y-%m') AS month,
    i.product_id,
    SUM(i.quantity) AS units_sold,
    SUM(i.quantity * i.unit_list_price) AS gross_sales,
    SUM(i.discount_amount) AS discounts
FROM order_items AS i
JOIN orders AS o ON o.order_id = i.order_id
WHERE o.status <> 'cancelled'
GROUP BY 1, 2
ORDER BY 1, 2
"""


def run_sql(sql: str, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Run a SQL query over pandas DataFrames, using DuckDB, and return a DataFrame."""
    database = duckdb.connect(":memory:")
    for name, frame in tables.items():
        database.register(name, frame)
    return database.sql(sql).df()


# ---- A draft with a mistake in it (notebook 5) --------------------------------


def broken_all_in_one_sql() -> str:
    """The all-in-one query with the mistake from notebook 2 put into it.

    It joins order lines straight to refunds, so a line with two refunds is counted twice.
    """
    path = MILESTONE / "retail_profit_stack/transform/implementations/sql/profit_all_in_one.sql"
    correct = path.read_text(encoding="utf-8")
    lines = [line for line in correct.splitlines() if not line.startswith("--")]
    broken = "\n".join(lines).replace(
        "FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id",
        "FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id\n"
        "    LEFT JOIN refunds AS x ON x.order_item_id = i.order_item_id",
    )
    if broken == "\n".join(lines):
        raise RuntimeError("The production query changed; update broken_all_in_one_sql")
    return broken


# ---- Connecting to a model (notebooks 3 to 6) -------------------------------


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


# ---- Showing how a draft did (notebooks 3 to 5) -----------------------------


def cases_table(results) -> pd.DataFrame:
    """Test results as a table: one row per hand-worked case."""
    return pd.DataFrame([
        {"case": result.case, "passed": "yes" if result.passed else "NO", "what went wrong": result.message}
        for result in results
    ])  # fmt: skip


def run_comparison(client, models, tasks, languages, workers: int = 8) -> list:
    """Ask every model for every task in every language, several requests at a time.

    Returns one DraftResult per draft. A model that fails to answer gets a result with zero
    cases passed, so one slow or broken model cannot stop the comparison.
    """
    from retail_profit_stack.transform.drafting import draft_and_score

    jobs = [(model, task, language) for model in models for task in tasks for language in languages]
    print(
        f"{len(jobs)} drafts to request: {len(models)} models x {len(tasks)} tasks x {len(languages)} languages"
    )
    start = time.time()
    finished = []

    def one(job):
        model, task, language = job
        result = draft_and_score(client, model, task, language)
        finished.append(result)
        if len(finished) % 10 == 0 or len(finished) == len(jobs):
            print(f"  {len(finished)} of {len(jobs)} done after {time.time() - start:.0f} seconds")
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    cost = sum(result.cost for result in results)
    print(f"Finished in {time.time() - start:.0f} seconds. Total cost ${cost:.4f}")
    return results


def repeat(function, times: int) -> list:
    """Call a function several times at once and return every result.

    Models do not give the same answer twice, so one run says little. Use this to run the
    same experiment a few times and look at all the outcomes.
    """
    with ThreadPoolExecutor(max_workers=times) as pool:
        return list(pool.map(lambda _: function(), range(times)))


def summarise(results, by=("model",)) -> pd.DataFrame:
    """Accuracy, cost, and speed for each model (or each model and language)."""
    frame = pd.DataFrame([result.model_dump() for result in results])
    frame["model"] = frame["model"].str.split("/").str[-1]
    grouped = frame.groupby(list(by), sort=False)
    summary = grouped.agg(
        drafts=("all_passed", "size"),
        fully_correct=("all_passed", "sum"),
        cases_passed=("cases_passed", "sum"),
        cases_total=("cases_total", "sum"),
        cost=("cost", "sum"),
        seconds=("seconds", "mean"),
        output_tokens=("output_tokens", "mean"),
    ).reset_index()
    summary["cases passed (%)"] = (
        (100 * summary["cases_passed"] / summary["cases_total"]).round().astype(int)
    )
    summary["fully correct"] = (
        summary["fully_correct"].astype(str) + " of " + summary["drafts"].astype(str)
    )
    summary["cost per draft ($)"] = (summary["cost"] / summary["drafts"]).round(5)
    summary["seconds per draft"] = summary["seconds"].round(1)
    columns = [*by, "cases passed (%)", "fully correct", "cost per draft ($)", "seconds per draft"]
    return summary[columns].sort_values("cases passed (%)", ascending=False).reset_index(drop=True)


# ---- The answer, and the answer key (notebook 6) ----------------------------


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
    """Look up each line of milestone 1's answer key in the calculated tables.

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
            "Answer key (milestone 1)": _money(line["value"], line["kind"]),
            "Calculated (milestone 2)": _money(calculated, line["kind"]),
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
