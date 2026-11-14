"""The six bounded tools: the only way the analyst can reach data.

Implements milestone 1's LLD section 4 (Tools), unchanged except for get_evidence, which now
reads real source records (this milestone's LLD section 7). Every number in an answer must come from one
of these functions. They read, sum, rank, and compare; the model never does.
"""

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
    SELECT 'order_item' AS record_type, 'order_items' AS source_table,
           i.order_item_id AS source_record_id,
           i.quantity * i.unit_list_price - i.discount_amount AS amount,
           i.quantity || ' x ' || p.product_name || ' on order ' || i.order_id || ' ('
               || o.order_date || '), list price ' || printf('%.2f', i.unit_list_price)
               || ', discount ' || printf('%.2f', i.discount_amount) AS description,
           1 AS type_order
    FROM order_items i JOIN orders o USING (order_id) JOIN products p USING (product_id)
    WHERE o.status <> 'cancelled' AND strftime(o.order_date, '%Y-%m') = $month
      AND i.product_id = $product_id
    UNION ALL
    SELECT 'refund', 'refunds', refund_id, refund_amount,
           'Refund issued ' || refund_date || ' against line ' || order_item_id
               || ', return handling cost ' || printf('%.2f', return_handling_cost), 2
    FROM refunds
    WHERE strftime(refund_date, '%Y-%m') = $month AND product_id = $product_id
    UNION ALL
    SELECT 'product_cost', 'product_costs', product_id || '/' || month, unit_cost,
           'Unit cost agreed with the vendor for ' || month, 3
    FROM product_costs WHERE month = $month AND product_id = $product_id
    UNION ALL
    SELECT 'shipment', 'shipments', shipment_id, pick_pack_cost + carrier_cost,
           'Shipped ' || ship_date || ' for line ' || order_item_id || ': pick and pack '
               || printf('%.2f', pick_pack_cost) || ', carrier ' || printf('%.2f', carrier_cost), 4
    FROM shipments
    WHERE strftime(ship_date, '%Y-%m') = $month AND product_id = $product_id
    UNION ALL
    SELECT 'payment_fee', 'payment_fees', fee_id, fee_amount,
           'Payment fee captured ' || capture_date || ' for line ' || order_item_id, 5
    FROM payment_fees
    WHERE strftime(capture_date, '%Y-%m') = $month AND product_id = $product_id
), counted AS (
    SELECT *, COUNT(*) OVER () AS total_records,
           COUNT(*) OVER (PARTITION BY record_type, source_record_id) AS times_seen
    FROM records
), ranked AS (
    -- Most notable first within each kind of record: repeated records, then largest amounts.
    SELECT *, ROW_NUMBER() OVER (
               PARTITION BY record_type ORDER BY times_seen DESC, amount DESC, source_record_id
           ) AS position
    FROM counted
)
SELECT * FROM ranked ORDER BY position, type_order LIMIT $limit
"""


def get_evidence(
    month: str, product_id: str, limit: int = 5, store: Store | None = None
) -> EvidenceResult:
    """Return real source records behind one product's figures for a month."""
    store = store or get_store()
    _check(month, store.months(), "month")
    _check(product_id, store.product_ids(), "product_id")
    with store._lock:
        cursor = store.db.execute(
            EVIDENCE_SQL, {"month": month, "product_id": product_id, "limit": max(limit, 0)}
        )
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
    tables = sorted({record.source_table for record in records})
    return EvidenceResult(
        month=month, product_id=product_id, records=records,
        total_records=rows[0]["total_records"] if rows else 0,
        sources=[
            SourceRef(
                table=table,
                keys=[r.source_record_id for r in records if r.source_table == table],
            )
            for table in tables
        ] or [SourceRef(table="order_items")],
    )  # fmt: skip


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
        _check(product_id, store.product_ids(), "product_id")
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
        month=month,
        product_id=product_id,
        category=category,
        flags=flags,
        confidence_level=level,
        confidence_reasons=reasons,
        sources=[SourceRef(table="quality_flags", keys=[flag.flag_id for flag in flags])],
    )
