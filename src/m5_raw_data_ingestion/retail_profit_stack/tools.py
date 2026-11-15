"""The seven bounded tools: the only way the analyst can reach data.

Implements LLD section 6 (The tools). Six are from earlier milestones. New in milestone 4:
get_evidence reads the lineage a run saved, compare_runs is added, and results name their run.
Every number in an answer must come from one of these functions. They read, sum, rank, and
compare; the model never does.
"""

from retail_profit_stack.lineage import compare
from retail_profit_stack.lineage.runs import read_history
from retail_profit_stack.schemas import (
    ALL_TERMS,
    MONEY_TERMS,
    ComparisonRow,
    ConfidenceLevel,
    EvidenceRecord,
    EvidenceResult,
    GroupBy,
    MetricDefinition,
    ProfitComparison,
    ProfitResult,
    ProfitRow,
    QualityFlag,
    QualityResult,
    ReportingPeriod,
    RunComparison,
    RunFigure,
    SourceRef,
)
from retail_profit_stack.store import Store, get_store

# LLD section 4, confidence rule: the worst flag severity sets the confidence level.
SEVERITY_TO_CONFIDENCE: dict[str, ConfidenceLevel] = {
    "high": "low",
    "medium": "medium",
    "low": "high",
}
CONFIDENCE_ORDER: list[ConfidenceLevel] = ["high", "medium", "low"]


class ToolInputError(ValueError):
    """A tool was called with a value that does not exist. The message lists the valid values."""


def _check(value: str, valid: list[str], what: str) -> None:
    if value not in valid:
        raise ToolInputError(f"Unknown {what} '{value}'. Valid values: {', '.join(valid)}")


def _product_id(value: str, store: Store) -> str:
    """Accept a product id (P011) or a product name (sun hat), and return the id.

    New in milestone 3. A question usually names a product. If the tool refused names, the
    analyst would have to look at the whole month's flags just to find the id.
    """
    names = {
        row["product_name"].lower(): row["product_id"]
        for row in store.rows("SELECT product_id, product_name FROM products")
    }
    value = names.get(value.strip().lower(), value)
    _check(value, store.product_ids(), "product_id")
    return value


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def get_reporting_period(store: Store | None = None) -> ReportingPeriod:
    """Say which month 'last month' is, and which months have data."""
    store = store or get_store()
    return ReportingPeriod(
        **store.reporting_period,
        available_months=store.months(),
        sources=[SourceRef(table="reporting_period", keys=["as_of_date"])],
    )


def get_metric_definition(metric: str, store: Store | None = None) -> MetricDefinition:
    """Return a metric's formula, components, assumptions, and version."""
    store = store or get_store()
    definitions = {item["name"]: item for item in store.definitions["metrics"]}
    _check(metric, list(definitions), "metric")
    return MetricDefinition(
        **definitions[metric], sources=[SourceRef(table="metric_definitions", keys=[metric])]
    )


def _profit_rows(store: Store, month: str, group_by: GroupBy) -> list[dict]:
    """One row per product, or per category summed from its product rows."""
    if group_by == "product":
        return store.rows(
            f"""
            SELECT 'product' AS entity_type, p.product_id AS entity_id,
                   p.product_name AS entity_name, p.category, m.month, m.units_sold,
                   {", ".join(f"m.{term}" for term in MONEY_TERMS)},
                   m.contribution_profit IS NOT NULL AS is_complete
            FROM monthly_product_profit m JOIN products p USING (product_id)
            WHERE m.month = ? ORDER BY p.product_id
            """,
            [month],
        )
    # SUM skips missing values, so a category total covers only the products that have one.
    # is_complete says whether every product contributed to every term.
    complete = " AND ".join(f"COUNT(m.{term}) = COUNT(*)" for term in MONEY_TERMS)
    return store.rows(
        f"""
        SELECT 'category' AS entity_type, p.category AS entity_id, p.category AS entity_name,
               p.category, m.month, CAST(SUM(m.units_sold) AS INTEGER) AS units_sold,
               {", ".join(f"ROUND(SUM(m.{term}), 2) AS {term}" for term in MONEY_TERMS)},
               ({complete}) AS is_complete
        FROM monthly_product_profit m JOIN products p USING (product_id)
        WHERE m.month = ? GROUP BY p.category, m.month ORDER BY p.category
        """,
        [month],
    )


def _profit_sources(store: Store, month: str) -> list[SourceRef]:
    keys = [f"{month}/{product_id}" for product_id in store.product_ids()]
    return [SourceRef(table="monthly_product_profit", keys=keys), SourceRef(table="products")]


def query_profit(
    month: str,
    group_by: GroupBy,
    metric: str = "contribution_profit",
    top_n: int | None = None,
    store: Store | None = None,
) -> ProfitResult:
    """Return every profit term by product or category for a month, ranked by one metric."""
    store = store or get_store()
    _check(month, store.months(), "month")
    _check(group_by, ["product", "category"], "group_by")
    _check(metric, ALL_TERMS, "metric")
    rows = _profit_rows(store, month, group_by)
    # Highest first. Rows with no value for the metric are unranked and listed last.
    ranked = sorted((row for row in rows if row[metric] is not None), key=lambda row: -row[metric])
    unranked = [row for row in rows if row[metric] is None]
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    for row in unranked:
        row["rank"] = None
    ordered = ranked + unranked
    if top_n is not None:
        ordered = ordered[: max(top_n, 0)]
    return ProfitResult(
        run_id=store.run_id,
        month=month,
        group_by=group_by,
        metric=metric,
        metric_version=store.definitions["version"],
        rows=[ProfitRow(**row) for row in ordered],
        sources=_profit_sources(store, month),
    )


def compare_profit(
    month: str,
    previous_month: str,
    group_by: GroupBy,
    metric: str = "contribution_profit",
    store: Store | None = None,
) -> ProfitComparison:
    """Return the change in one metric between two months, by product or category."""
    store = store or get_store()
    for value in (month, previous_month):
        _check(value, store.months(), "month")
    _check(group_by, ["product", "category"], "group_by")
    _check(metric, ALL_TERMS, "metric")
    current_rows = {row["entity_id"]: row for row in _profit_rows(store, month, group_by)}
    previous_rows = {row["entity_id"]: row for row in _profit_rows(store, previous_month, group_by)}
    rows = []
    for entity_id, current_row in current_rows.items():
        previous_row = previous_rows[entity_id]
        current, previous = current_row[metric], previous_row[metric]
        # A partial category sum is not comparable with a full one, so no change is reported.
        change = pct_change = None
        complete = bool(
            current is not None
            and previous is not None
            and current_row["is_complete"]
            and previous_row["is_complete"]
        )
        if current is not None and previous is not None and complete:
            change = round(current - previous, 2)
            if previous != 0:
                pct_change = round(change / previous * 100, 1)
        rows.append(
            ComparisonRow(
                entity_type=group_by,
                entity_id=entity_id,
                entity_name=current_row["entity_name"],
                current=current,
                previous=previous,
                change=change,
                pct_change=pct_change,
                is_complete=complete,
            )
        )
    rows.sort(key=lambda row: (row.change is None, row.change if row.change is not None else 0))
    return ProfitComparison(
        run_id=store.run_id,
        month=month,
        previous_month=previous_month,
        group_by=group_by,
        metric=metric,
        metric_version=store.definitions["version"],
        rows=rows,
        sources=[
            SourceRef(
                table="monthly_product_profit",
                keys=[
                    f"{value}/{product_id}"
                    for value in (month, previous_month)
                    for product_id in store.product_ids()
                ],
            ),
            SourceRef(table="products"),
        ],
    )


EVIDENCE_SQL = """
WITH records AS (
    -- Every source record, described in words. The same shape as in milestone 2.
    SELECT 'order_item' AS record_type, 'order_items' AS source_table, i.row_number,
           i.order_item_id AS source_record_id,
           i.quantity * i.unit_list_price - i.discount_amount AS amount,
           i.quantity || ' x ' || p.product_name || ' on order ' || i.order_id || ' ('
               || o.order_date || '), list price ' || printf('%.2f', i.unit_list_price)
               || ', discount ' || printf('%.2f', i.discount_amount) AS description,
           1 AS type_order
    FROM order_items i JOIN orders o USING (order_id) JOIN products p USING (product_id)
    UNION ALL
    SELECT 'refund', 'refunds', row_number, refund_id, refund_amount,
           'Refund issued ' || refund_date || ' against line ' || order_item_id
               || ', return handling cost ' || printf('%.2f', return_handling_cost), 2
    FROM refunds
    UNION ALL
    SELECT 'product_cost', 'product_costs', row_number, product_id || '/' || month, unit_cost,
           'Unit cost agreed with the vendor for ' || month, 3
    FROM product_costs
    UNION ALL
    SELECT 'shipment', 'shipments', row_number, shipment_id, pick_pack_cost + carrier_cost,
           'Shipped ' || ship_date || ' for line ' || order_item_id || ': pick and pack '
               || printf('%.2f', pick_pack_cost) || ', carrier ' || printf('%.2f', carrier_cost), 4
    FROM shipments
    UNION ALL
    SELECT 'payment_fee', 'payment_fees', row_number, fee_id, fee_amount,
           'Payment fee captured ' || capture_date || ' for line ' || order_item_id, 5
    FROM payment_fees
), in_lineage AS (
    -- New in milestone 4: the lineage decides which records count for this product and month.
    SELECT DISTINCT source_table, row_number
    FROM figure_lineage
    WHERE month = $month AND product_id = $product_id
), ranked AS (
    -- The largest amounts first within each kind of record.
    SELECT r.*, ROW_NUMBER() OVER (
               PARTITION BY r.record_type ORDER BY r.amount DESC, r.source_record_id
           ) AS position
    FROM records r JOIN in_lineage l USING (source_table, row_number)
)
SELECT * FROM ranked ORDER BY position, type_order LIMIT $limit
"""


def _lineage_steps(store: Store) -> list[str]:
    """The tables a figure passes through, one sentence per transformation."""
    made_from: dict[str, list[str]] = {}
    for row in store.rows("SELECT output_table, input_table FROM lineage_steps"):
        made_from.setdefault(row["output_table"], []).append(row["input_table"])
    return [f"{output} is made from {' and '.join(inputs)}" for output, inputs in made_from.items()]


def get_evidence(
    month: str, product_id: str, limit: int = 5, store: Store | None = None
) -> EvidenceResult:
    """Return the records behind one product's figures for a month, read from lineage."""
    store = store or get_store()
    _check(month, store.months(), "month")
    product_id = _product_id(product_id, store)
    scope = {"month": month, "product_id": product_id}
    with store._lock:
        cursor = store.db.execute(EVIDENCE_SQL, {**scope, "limit": max(limit, 0)})
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    records = [
        EvidenceRecord(
            evidence_id=f"{row['source_table']}/{row['source_record_id']}",
            month=month, product_id=product_id, record_type=row["record_type"],
            source_table=row["source_table"], source_record_id=row["source_record_id"],
            amount=round(row["amount"], 2), description=row["description"],
        )
        for row in rows
    ]  # fmt: skip

    # Every record behind the figures, counted by source table.
    counts = store.rows(
        "SELECT source_table, COUNT(DISTINCT row_number) AS records FROM figure_lineage "
        "WHERE month = ? AND product_id = ? GROUP BY source_table ORDER BY source_table",
        [month, product_id],
    )
    record_counts = {row["source_table"]: row["records"] for row in counts}
    total_records = sum(record_counts.values())
    # Records the checks set aside for this product and month. They are not in the lineage.
    set_aside = store.rows(
        "SELECT COUNT(*) AS records FROM finding_records r "
        "JOIN quality_flags q ON q.flag_id = r.finding_id "
        "WHERE r.quarantined AND q.month = ? AND q.product_id = ?",
        [month, product_id],
    )
    tables = sorted(record_counts)
    return EvidenceResult(
        month=month, product_id=product_id, records=records,
        is_sample=len(records) < total_records,
        total_records=total_records,
        run_id=store.run_id,
        record_counts=record_counts,
        set_aside_count=set_aside[0]["records"],
        steps=_lineage_steps(store),
        sources=[
            SourceRef(
                table=table,
                keys=[r.source_record_id for r in records if r.source_table == table],
            )
            for table in tables
        ] + [SourceRef(table="figure_lineage", keys=[store.run_id])],
    )  # fmt: skip


def compare_runs(
    month: str | None = None,
    product_id: str | None = None,
    metric: str = "contribution_profit",
    store: Store | None = None,
) -> RunComparison:
    """Compare the latest pipeline run with the one before it. New in milestone 4."""
    store = store or get_store()
    if month is not None:
        _check(month, store.months(), "month")
    if product_id is not None:
        product_id = _product_id(product_id, store)
    _check(metric, ALL_TERMS, "metric")
    run_ids = [record["run_id"] for record in read_history(store.warehouse_dir)]
    if len(run_ids) < 2:
        raise ToolInputError("There is only one pipeline run, so there is nothing to compare.")
    earlier_run, later_run = run_ids[-2], run_ids[-1]
    result = compare.compare_runs(earlier_run, later_run, store.warehouse_dir)

    def in_scope(row: dict) -> bool:
        """True when a row is for the month and product that were asked about."""
        if month is not None and row["month"] != month:
            return False
        return product_id is None or row["product_id"] == product_id

    names = {
        row["product_id"]: row["product_name"]
        for row in store.rows("SELECT product_id, product_name FROM products")
    }
    changed = [
        RunFigure(**row, product_name=names[row["product_id"]])
        for row in result["figures_changed"]
        if row["metric"] == metric and in_scope(row)
    ]
    # When one product was asked about and its figure did not move, still show the figure,
    # so the analyst can say "no change" with a number.
    unchanged = []
    if product_id is not None:
        changed_months = {figure.month for figure in changed}
        profit_rows = store.rows(
            f"SELECT month, product_id, {metric} AS value FROM monthly_product_profit "
            "WHERE product_id = ? ORDER BY month",
            [product_id],
        )
        for row in profit_rows:
            if not in_scope(row) or row["month"] in changed_months:
                continue
            value = _round(row["value"])
            unchanged.append(
                RunFigure(
                    month=row["month"],
                    product_id=product_id,
                    product_name=names[product_id],
                    metric=metric,
                    earlier=value,
                    later=value,
                    change=None if value is None else 0.0,
                )
            )
    return RunComparison(
        earlier_run=earlier_run,
        later_run=later_run,
        run_id=later_run,
        earlier_note=result["earlier_note"],
        later_note=result["later_note"],
        month=month,
        product_id=product_id,
        metric=metric,
        metric_version=store.definitions["version"],
        settings_changed=result["settings_changed"],
        inputs_changed=result["inputs_changed"],
        code_changed=result["code_changed"],
        checks_changed=result["checks_changed"],
        figures_changed=changed,
        figures_unchanged=unchanged,
        records_changed=[row for row in result["records_changed"] if in_scope(row)],
        findings=[row for row in result["findings"] if in_scope(row)],
        sources=[
            SourceRef(table="run_history", keys=[earlier_run, later_run]),
            SourceRef(table="monthly_product_profit"),
            SourceRef(table="figure_lineage"),
        ],
    )


def get_quality_flags(
    month: str,
    product_id: str | None = None,
    category: str | None = None,
    store: Store | None = None,
) -> QualityResult:
    """Return known data problems for a month, optionally narrowed, and the confidence level."""
    store = store or get_store()
    _check(month, store.months(), "month")
    sql = (
        "SELECT q.*, p.product_name, p.category FROM quality_flags q "
        "JOIN products p USING (product_id) WHERE q.month = ?"
    )
    params: list = [month]
    if product_id is not None:
        product_id = _product_id(product_id, store)
        sql += " AND q.product_id = ?"
        params.append(product_id)
    if category is not None:
        _check(category, store.categories(), "category")
        sql += " AND p.category = ?"
        params.append(category)
    flags = [
        QualityFlag(**{**row, "affected_metrics": row["affected_metrics"].split(";")})
        for row in store.rows(sql + " ORDER BY q.flag_id", params)
    ]
    level: ConfidenceLevel = "high"
    for flag in flags:
        candidate = SEVERITY_TO_CONFIDENCE[flag.severity]
        if CONFIDENCE_ORDER.index(candidate) > CONFIDENCE_ORDER.index(level):
            level = candidate
    reasons = [f"{flag.flag_id} ({flag.severity}): {flag.description}" for flag in flags]
    if not flags:
        reasons = ["No known data problems for this scope."]
    return QualityResult(
        run_id=store.run_id,
        month=month,
        product_id=product_id,
        category=category,
        flags=flags,
        confidence_level=level,
        confidence_reasons=reasons,
        sources=[SourceRef(table="quality_flags", keys=[flag.flag_id for flag in flags])],
        set_aside_count=sum(flag.record_count for flag in flags if flag.outcome == "quarantine"),
    )
