"""Helpers for the milestone 1 lab notebooks.

Each notebook teaches one idea. Once you have built something in a notebook, the
finished version lives here so that later notebooks can import it in one line
and stay short. The section headings say which notebook teaches each piece.

This is brainstorming code. The production version of the same logic is in this
milestone's retail_profit_stack/ package.
"""

import json
import os
import re
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from IPython.display import Markdown, display
from langchain_core.tools import StructuredTool
from openai import OpenAI
from pydantic import BaseModel, Field

MILESTONE = Path(__file__).resolve().parent.parent
DOCS = MILESTONE / "docs"
DATA = MILESTONE / "data" / "mock"
EVALS = MILESTONE / "evals"
RESULTS = Path(__file__).resolve().parent / "results"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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


# ---- The data (explored in notebook 1; LLD section 3) -----------------------

products = pd.read_csv(DATA / "products.csv")
profit = pd.read_csv(DATA / "monthly_product_profit.csv")
evidence = pd.read_csv(DATA / "evidence_records.csv")
flags = pd.read_csv(DATA / "quality_flags.csv")
reporting_period = json.loads((DATA / "reporting_period.json").read_text(encoding="utf-8"))
definitions = json.loads(
    (MILESTONE / "retail_profit_stack" / "definitions" / "metrics_v1.json").read_text("utf-8")
)

LAST_MONTH = reporting_period["current_month"]
PREVIOUS_MONTH = reporting_period["previous_month"]
METRIC_VERSION = definitions["version"]

MAIN_QUESTION = (
    "Which products and categories generated the most contribution profit last month, "
    "what changed, and how confident should I be in those numbers?"
)


# ---- Connecting to a model (written out in notebook 2) ----------------------


def connect() -> tuple[OpenAI, str]:
    """Return an OpenRouter client and the model name, using the key in the project's .env."""
    load_dotenv(find_dotenv(usecwd=True), override=True)
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("MODEL_NAME", "openrouter/free")
    if not api_key:
        raise RuntimeError(
            "No OpenRouter API key found. Copy .env.example to .env in the project root, "
            "add your OPENROUTER_API_KEY, and run this cell again."
        )
    print(f"Connected to OpenRouter. Using model {model}")
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key, timeout=120, max_retries=5)
    return client, model


# ---- The shape of an answer (introduced in notebook 3; LLD section 5) -------


class SourceRef(BaseModel):
    table: str = Field(description="Table name, such as monthly_product_profit")
    keys: list[str] = Field(description="Row keys such as 2026-10/P001; may be empty")


class Figure(BaseModel):
    """One number in the answer."""

    label: str = Field(
        description="Plain description, e.g. 'Trail water bottle, contribution profit'"
    )
    metric: str = Field(description="A metric name such as contribution_profit or net_sales")
    kind: Literal["value", "change", "pct_change"] = Field(
        description="value for a month's figure; change or pct_change for a comparison"
    )
    value: float | None = Field(description="The number. null means unavailable")
    unit: Literal["USD", "percent", "units"]
    month: str = Field(description="YYYY-MM. For a change, the later month")
    entity_type: Literal["product", "category"]
    entity_id: str = Field(description="A product_id such as P001, or a category name")
    source_tool: str = Field(description="The tool that returned this value, or 'prompt' if none")


class DefinitionRef(BaseModel):
    metric: str
    version: str


class Caveat(BaseModel):
    flag_id: str | None = Field(description="The quality flag, such as QF-001, if there is one")
    text: str


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    reasons: list[str]


class AnalystAnswer(BaseModel):
    """The structured answer to a profit question."""

    status: Literal["answered", "declined"]
    headline: str = Field(description="The answer in one or two sentences")
    narrative: str = Field(description="A short explanation")
    figures: list[Figure]
    definitions_used: list[DefinitionRef]
    assumptions: list[str]
    caveats: list[Caveat]
    confidence: Confidence | None
    sources: list[SourceRef]
    decline_reason: str | None


def show_answer(answer: AnalystAnswer) -> None:
    """Display an answer the way a retail leader would read it."""
    lines = [f"### {answer.headline}", answer.narrative, ""]
    if answer.decline_reason:
        lines.append(f"**Declined:** {answer.decline_reason}")
    if answer.figures:
        lines.append("| Figure | Value | Month |\n|---|---|---|")
        for figure in answer.figures:
            lines.append(
                f"| {figure.label} | {_money(figure.value, figure.kind)} | {figure.month} |"
            )
        lines.append("")
    lines += [f"- **Caveat {caveat.flag_id or ''}:** {caveat.text}" for caveat in answer.caveats]
    if answer.confidence:
        reasons = " ".join(answer.confidence.reasons)
        lines.append(f"\n**Confidence: {answer.confidence.level}.** {reasons}")
    display(Markdown("\n".join(lines)))


# ---- Checking an answer against the truth (notebooks 3 and 5) ---------------

MONEY_TERMS = [
    "gross_sales", "discounts", "refunds", "net_sales", "product_cost", "gross_profit",
    "fulfillment_cost", "shipping_cost", "payment_fees", "return_cost", "contribution_profit",
]  # fmt: skip
ALL_TERMS = ["units_sold", *MONEY_TERMS]


def to_records(frame: pd.DataFrame) -> list[dict]:
    """A DataFrame as a list of plain dicts, with missing values as None."""
    return json.loads(frame.to_json(orient="records"))


def profit_rows(month: str, group_by: str) -> list[dict]:
    """One row per product, or per category summed from its products, for one month."""
    month_rows = profit[profit["month"] == month].merge(products, on="product_id")
    if group_by == "product":
        rows = month_rows.assign(
            entity_type="product",
            entity_id=month_rows["product_id"],
            entity_name=month_rows["product_name"],
        )
        rows["is_complete"] = rows["contribution_profit"].notna()
    else:
        # sum() skips missing values, so a category total covers only the products that have one
        rows = month_rows.groupby("category", as_index=False)[ALL_TERMS].sum().round(2)
        complete = month_rows[MONEY_TERMS].notna().all(axis=1).groupby(month_rows["category"]).all()
        rows = rows.assign(
            entity_type="category", entity_id=rows["category"], entity_name=rows["category"],
            month=month,
        )  # fmt: skip
        rows["is_complete"] = rows["category"].map(complete)
    columns = ["entity_type", "entity_id", "entity_name", "category", "month", *ALL_TERMS]
    return to_records(rows[[*columns, "is_complete"]])


def build_facts() -> dict:
    """Every true figure, keyed by (metric, kind, month, entity_id)."""
    facts = {}
    for group_by in ["product", "category"]:
        current = {row["entity_id"]: row for row in profit_rows(LAST_MONTH, group_by)}
        previous = {row["entity_id"]: row for row in profit_rows(PREVIOUS_MONTH, group_by)}
        for entity_id, row in current.items():
            before = previous[entity_id]
            comparable = row["is_complete"] and before["is_complete"]
            for term in ALL_TERMS:
                change = round(row[term] - before[term], 2) if comparable else None
                percent = (
                    round(change / before[term] * 100, 1) if comparable and before[term] else None
                )
                facts[(term, "value", LAST_MONTH, entity_id)] = row[term]
                facts[(term, "value", PREVIOUS_MONTH, entity_id)] = before[term]
                facts[(term, "change", LAST_MONTH, entity_id)] = change
                facts[(term, "pct_change", LAST_MONTH, entity_id)] = percent
    return facts


FACTS = build_facts()


def same_value(left, right) -> bool:
    """True when two figures agree to the cent, or are both unavailable."""
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= 0.005


def _money(value, kind: str = "value") -> str:
    if value is None:
        return "unavailable"
    if kind == "pct_change":
        return f"{value:+.1f}%"
    sign = ("+" if value >= 0 else "-") if kind == "change" else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def key_row(what: str, entity_id: str, value, kind: str = "value") -> dict:
    """One line of the answer key: a contribution profit figure for last month."""
    return {
        "what": what, "metric": "contribution_profit", "kind": kind, "month": LAST_MONTH,
        "entity_id": entity_id, "value": None if value is None or pd.isna(value) else float(value),
    }  # fmt: skip


def compare_with_key(answer_key: dict, answers: dict) -> pd.DataFrame:
    """Put the correct answer beside what each approach said, line by line.

    answers maps a name such as "LLM" to an AnalystAnswer, or to None if it has not been run.
    """
    table = []
    for line in answer_key["figures"]:
        row = {"What": line["what"], "Correct answer": _money(line["value"], line["kind"])}
        key = (line["metric"], line["kind"], line["month"], line["entity_id"])
        for name, answer in answers.items():
            if answer is None:
                row[f"{name} said"], row[f"{name} right?"] = "not run", ""
                continue
            given = {(f.metric, f.kind, f.month, f.entity_id): f.value for f in answer.figures}
            if key not in given:
                row[f"{name} said"], row[f"{name} right?"] = "not given", "no"
            else:
                row[f"{name} said"] = _money(given[key], line["kind"])
                row[f"{name} right?"] = "yes" if same_value(given[key], line["value"]) else "NO"
        table.append(row)

    extras = [("Confidence", answer_key["confidence"])]
    extras += [(f"Mentions data problem {flag_id}", "yes") for flag_id in answer_key["flags"]]
    for what, correct in extras:
        row = {"What": what, "Correct answer": correct}
        for name, answer in answers.items():
            if answer is None:
                row[f"{name} said"], row[f"{name} right?"] = "not run", ""
                continue
            if what == "Confidence":
                said = answer.confidence.level if answer.confidence else "not given"
            else:
                text = " ".join(f"{c.flag_id or ''} {c.text}" for c in answer.caveats)
                said = "yes" if what.split()[-1] in text else "no"
            row[f"{name} said"] = said
            row[f"{name} right?"] = "yes" if said == correct else "NO"
        table.append(row)
    return pd.DataFrame(table)


def check_figures(answer: AnalystAnswer) -> pd.DataFrame:
    """Check every number an answer gave against the true figure."""
    table = []
    for figure in answer.figures:
        key = (figure.metric, figure.kind, figure.month, figure.entity_id)
        known = key in FACTS
        table.append({
            "Figure": figure.label,
            "AI said": _money(figure.value, figure.kind),
            "True figure": _money(FACTS[key], figure.kind) if known else "no such figure",
            "Right?": "yes" if known and same_value(figure.value, FACTS[key]) else "NO",
        })  # fmt: skip
    return pd.DataFrame(table)


# ---- The six tools (one built in notebook 4, all used in notebook 5; LLD section 4) ----


class ToolInputError(ValueError):
    """A tool was called with a value that does not exist."""


def check(value, valid, what) -> None:
    if value not in valid:
        raise ToolInputError(f"Unknown {what} '{value}'. Valid values: {', '.join(valid)}")


MONTHS = sorted(profit["month"].unique())
PRODUCT_IDS = sorted(products["product_id"])
CATEGORIES = sorted(products["category"].unique())
PROFIT_SOURCES = {"table": "products", "keys": []}


def get_reporting_period() -> dict:
    """Say which month 'last month' is, and which months have data."""
    sources = [{"table": "reporting_period", "keys": ["as_of_date"]}]
    return {**reporting_period, "available_months": MONTHS, "sources": sources}


def get_metric_definition(metric: str) -> dict:
    """Return a metric's formula, components, assumptions, and version."""
    by_name = {item["name"]: item for item in definitions["metrics"]}
    check(metric, list(by_name), "metric")
    return {**by_name[metric], "sources": [{"table": "metric_definitions", "keys": [metric]}]}


def query_profit(
    month: str, group_by: str, metric: str = "contribution_profit", top_n=None
) -> dict:
    """Return every profit term by product or category for a month, ranked by one metric."""
    check(month, MONTHS, "month")
    check(group_by, ["product", "category"], "group_by")
    check(metric, ALL_TERMS, "metric")
    rows = profit_rows(month, group_by)
    # Highest first. Rows with no value for the metric are unranked and listed last
    ranked = sorted([row for row in rows if row[metric] is not None], key=lambda row: -row[metric])
    unranked = [row for row in rows if row[metric] is None]
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    for row in unranked:
        row["rank"] = None
    rows = (ranked + unranked)[:top_n] if top_n is not None else ranked + unranked
    keys = [f"{month}/{product_id}" for product_id in PRODUCT_IDS]
    return {
        "month": month, "group_by": group_by, "metric": metric, "metric_version": METRIC_VERSION,
        "rows": rows,
        "sources": [{"table": "monthly_product_profit", "keys": keys}, PROFIT_SOURCES],
    }  # fmt: skip


def compare_profit(
    month: str, previous_month: str, group_by: str, metric: str = "contribution_profit"
) -> dict:
    """Return the change in one metric between two months, by product or category."""
    check(month, MONTHS, "month")
    check(previous_month, MONTHS, "month")
    check(group_by, ["product", "category"], "group_by")
    check(metric, ALL_TERMS, "metric")
    previous_rows = {row["entity_id"]: row for row in profit_rows(previous_month, group_by)}
    rows = []
    for row in profit_rows(month, group_by):
        before = previous_rows[row["entity_id"]]
        current, previous = row[metric], before[metric]
        # A partial category sum is not comparable with a full one, so no change is reported
        complete = (
            current is not None and previous is not None
            and row["is_complete"] and before["is_complete"]
        )  # fmt: skip
        change = round(current - previous, 2) if complete else None
        pct_change = round(change / previous * 100, 1) if complete and previous != 0 else None
        rows.append({
            "entity_type": group_by, "entity_id": row["entity_id"],
            "entity_name": row["entity_name"], "current": current, "previous": previous,
            "change": change, "pct_change": pct_change, "is_complete": complete,
        })  # fmt: skip
    rows.sort(key=lambda row: (row["change"] is None, row["change"] or 0))
    keys = [
        f"{value}/{product_id}" for value in (month, previous_month) for product_id in PRODUCT_IDS
    ]
    return {
        "month": month, "previous_month": previous_month, "group_by": group_by, "metric": metric,
        "metric_version": METRIC_VERSION, "rows": rows,
        "sources": [{"table": "monthly_product_profit", "keys": keys}, PROFIT_SOURCES],
    }  # fmt: skip


def get_evidence(month: str, product_id: str, limit: int = 5) -> dict:
    """Return sample source records behind one product's figures for a month."""
    check(month, MONTHS, "month")
    check(product_id, PRODUCT_IDS, "product_id")
    found = evidence[(evidence["month"] == month) & (evidence["product_id"] == product_id)]
    records = to_records(found.sort_values("evidence_id").head(limit))
    return {
        "month": month, "product_id": product_id, "records": records, "is_sample": True,
        "note": "These are sample records. They illustrate the figures and do not add up to them.",
        "sources": [{"table": "evidence_records", "keys": [r["evidence_id"] for r in records]}],
    }  # fmt: skip


SEVERITY_TO_CONFIDENCE = {"high": "low", "medium": "medium", "low": "high"}
CONFIDENCE_ORDER = ["high", "medium", "low"]


def get_quality_flags(month: str, product_id=None, category=None) -> dict:
    """Return known data problems for a month, optionally narrowed, and the confidence level."""
    check(month, MONTHS, "month")
    found = flags[flags["month"] == month].merge(products, on="product_id")
    if product_id is not None:
        check(product_id, PRODUCT_IDS, "product_id")
        found = found[found["product_id"] == product_id]
    if category is not None:
        check(category, CATEGORIES, "category")
        found = found[found["category"] == category]
    records = to_records(found.sort_values("flag_id"))
    for record in records:
        record["affected_metrics"] = record["affected_metrics"].split(";")
    # The confidence rule: the worst flag severity sets the level
    levels = [SEVERITY_TO_CONFIDENCE[record["severity"]] for record in records]
    level = max(levels, key=CONFIDENCE_ORDER.index, default="high")
    reasons = [f"{r['flag_id']} ({r['severity']}): {r['description']}" for r in records]
    return {
        "month": month, "product_id": product_id, "category": category, "flags": records,
        "confidence_level": level,
        "confidence_reasons": reasons or ["No known data problems for this scope."],
        "sources": [{"table": "quality_flags", "keys": [r["flag_id"] for r in records]}],
    }  # fmt: skip


# ---- The six tools, wrapped for an agent (notebook 5) -----------------------


def make_agent_tools() -> tuple[list[StructuredTool], list[dict]]:
    """Return the six tools ready for an agent, and the log that every call is written to.

    This is the same wrapping you did by hand for one tool in notebook 4: a function with a
    clear docstring becomes a tool. The only addition is that each call is also logged.
    """
    tool_log: list[dict] = []

    def record(name, function, **arguments) -> str:
        try:
            result = function(**arguments)
        except ToolInputError as error:
            tool_log.append(
                {"name": name, "arguments": arguments, "result": None, "error": str(error)}
            )
            return f"Error: {error}"
        tool_log.append({"name": name, "arguments": arguments, "result": result, "error": None})
        return json.dumps(result)

    def reporting_period_tool() -> str:
        """Say which month 'last month' (current_month) is, and which months have data."""
        return record("get_reporting_period", get_reporting_period)

    def metric_definition_tool(metric: str) -> str:
        """Return a metric's formula, components, assumptions, and version.

        metric is net_sales, gross_profit, contribution_profit, or one of their components.
        """
        return record("get_metric_definition", get_metric_definition, metric=metric)

    def query_profit_tool(
        month: str, group_by: str, metric: str = "contribution_profit", top_n: int | None = None
    ) -> str:
        """Return all profit figures for a month (YYYY-MM), ranked highest first by one metric.

        group_by is 'product' or 'category'. top_n keeps only the top rows.
        Category rows are summed for you. is_complete is false when a value is missing.
        """
        return record(
            "query_profit", query_profit, month=month, group_by=group_by, metric=metric, top_n=top_n
        )

    def compare_profit_tool(
        month: str, previous_month: str, group_by: str, metric: str = "contribution_profit"
    ) -> str:
        """Return the change and percentage change in one metric between two months.

        group_by is 'product' or 'category'. Rows are sorted from the biggest fall to the
        biggest rise. change is null when the two months cannot be compared.
        """
        return record(
            "compare_profit", compare_profit, month=month, previous_month=previous_month,
            group_by=group_by, metric=metric,
        )  # fmt: skip

    def evidence_tool(month: str, product_id: str, limit: int = 5) -> str:
        """Return sample source records (orders, refunds, costs) behind one product's figures."""
        return record("get_evidence", get_evidence, month=month, product_id=product_id, limit=limit)

    def quality_flags_tool(
        month: str, product_id: str | None = None, category: str | None = None
    ) -> str:
        """Return known data problems for a month and the confidence level they imply.

        Leave product_id and category empty for the whole month, or set one to narrow the scope.
        """
        return record(
            "get_quality_flags", get_quality_flags, month=month, product_id=product_id,
            category=category,
        )  # fmt: skip

    named = {
        "get_reporting_period": reporting_period_tool,
        "get_metric_definition": metric_definition_tool,
        "query_profit": query_profit_tool,
        "compare_profit": compare_profit_tool,
        "get_evidence": evidence_tool,
        "get_quality_flags": quality_flags_tool,
    }
    tools = [StructuredTool.from_function(function, name=name) for name, function in named.items()]
    return tools, tool_log
