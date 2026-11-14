"""Pydantic models for tool results and for the analyst's answer.

Implements LLD section 4 (tool result shapes) and section 5 (answer format).
These shapes are fixed contracts: later milestones may add fields but must not
remove or rename them.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Every term defined in LLD section 2, in the order of the profit calculation.
MONEY_TERMS = [
    "gross_sales",
    "discounts",
    "refunds",
    "net_sales",
    "product_cost",
    "gross_profit",
    "fulfillment_cost",
    "shipping_cost",
    "payment_fees",
    "return_cost",
    "contribution_profit",
]
ALL_TERMS = ["units_sold", *MONEY_TERMS]
APPROVED_METRICS = ["net_sales", "gross_profit", "contribution_profit"]

GroupBy = Literal["product", "category"]
ConfidenceLevel = Literal["high", "medium", "low"]


class SourceRef(BaseModel):
    """The rows a tool read, or the rows an answer relies on."""

    table: str = Field(description="Table or file name, for example monthly_product_profit")
    keys: list[str] = Field(default_factory=list, description="Row keys such as 2026-10/P001")


# ---- Tool results (LLD section 4) -------------------------------------------


class ReportingPeriod(BaseModel):
    as_of_date: str
    current_month: str
    previous_month: str
    available_months: list[str]
    sources: list[SourceRef]


class MetricDefinition(BaseModel):
    name: str
    version: str
    approved: bool
    unit: str
    description: str
    formula: str
    components: list[str]
    assumptions: list[str]
    sources: list[SourceRef]


class ProfitRow(BaseModel):
    entity_type: GroupBy
    entity_id: str
    entity_name: str
    category: str
    month: str
    units_sold: int
    gross_sales: float | None
    discounts: float | None
    refunds: float | None
    net_sales: float | None
    product_cost: float | None
    gross_profit: float | None
    fulfillment_cost: float | None
    shipping_cost: float | None
    payment_fees: float | None
    return_cost: float | None
    contribution_profit: float | None
    rank: int | None = Field(description="1 is highest for the chosen metric; None if unavailable")
    is_complete: bool = Field(description="False when a value is missing or a sum leaves rows out")


class ProfitResult(BaseModel):
    month: str
    group_by: GroupBy
    metric: str
    metric_version: str
    rows: list[ProfitRow]
    sources: list[SourceRef]


class ComparisonRow(BaseModel):
    entity_type: GroupBy
    entity_id: str
    entity_name: str
    current: float | None
    previous: float | None
    change: float | None
    pct_change: float | None
    is_complete: bool


class ProfitComparison(BaseModel):
    month: str
    previous_month: str
    group_by: GroupBy
    metric: str
    metric_version: str
    rows: list[ComparisonRow]
    sources: list[SourceRef]


class EvidenceRecord(BaseModel):
    evidence_id: str
    month: str
    product_id: str
    record_type: str
    source_table: str
    source_record_id: str
    amount: float
    description: str


class EvidenceResult(BaseModel):
    month: str
    product_id: str
    records: list[EvidenceRecord]
    is_sample: bool = True
    total_records: int = 0
    note: str = (
        "These are real records from the business's source tables, most notable first. "
        "They are some of the records behind the figures, not all of them."
    )
    sources: list[SourceRef]


class QualityFlag(BaseModel):
    flag_id: str
    month: str
    product_id: str
    product_name: str
    category: str
    check_name: str
    severity: Literal["high", "medium", "low"]
    affected_metrics: list[str]
    description: str


class QualityResult(BaseModel):
    month: str
    product_id: str | None
    category: str | None
    flags: list[QualityFlag]
    confidence_level: ConfidenceLevel
    confidence_reasons: list[str]
    sources: list[SourceRef]


# ---- The analyst's answer (LLD section 5) -----------------------------------


class Figure(BaseModel):
    """One number in the answer. It must equal a value returned by a tool."""

    label: str = Field(
        description="Plain description, e.g. 'Trail water bottle, contribution profit'"
    )
    metric: str = Field(description="A metric name such as contribution_profit or net_sales")
    kind: Literal["value", "change", "pct_change"] = Field(
        description="value for a month's figure; change or pct_change for a comparison"
    )
    value: float | None = Field(description="Exactly as a tool returned it. None means unavailable")
    unit: Literal["USD", "percent", "units"]
    month: str = Field(description="YYYY-MM. For a change, the later month")
    entity_type: GroupBy
    entity_id: str = Field(description="A product_id such as P001, or a category name")
    source_tool: str = Field(description="The tool that returned this value")


class DefinitionRef(BaseModel):
    metric: str
    version: str


class Caveat(BaseModel):
    flag_id: str | None = Field(default=None, description="The quality flag, e.g. QF-001, if any")
    text: str


class Confidence(BaseModel):
    level: ConfidenceLevel
    reasons: list[str]


class AnalystAnswer(BaseModel):
    """The structured answer the analyst returns for every question."""

    status: Literal["answered", "declined"]
    headline: str = Field(description="The answer in one or two sentences")
    narrative: str = Field(description="A short explanation using only numbers from tools")
    figures: list[Figure] = Field(default_factory=list)
    definitions_used: list[DefinitionRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[Caveat] = Field(default_factory=list)
    confidence: Confidence | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    decline_reason: str | None = None


# ---- A run of the analyst, and the checks on it (LLD sections 6 and 8) -------


class ToolCall(BaseModel):
    """One entry in the tool log: what was called, with what, and what came back."""

    name: str
    arguments: dict
    result: dict | None = None
    error: str | None = None


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class VerificationReport(BaseModel):
    passed: bool
    checks: list[CheckResult]


class AnalystRun(BaseModel):
    """Everything about one question: the answer, how it was reached, and whether it holds up."""

    question: str
    model: str
    answer: AnalystAnswer | None = None
    tool_log: list[ToolCall] = Field(default_factory=list)
    verification: VerificationReport | None = None
    error: str | None = None
    seconds: float = 0.0
