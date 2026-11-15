"""The source table schemas and the six transformation specs.

Implements LLD section 2 (Source tables) and section 5 (The six transformations). This is the
one description of the calculations that people, engines, tests, and AI prompts all read.
"""

from retail_profit_stack.config import METRIC_VERSION
from retail_profit_stack.transform.contracts import Column, TableSchema, TransformationSpec

# ---- Source tables ----------------------------------------------------------
# No key is set on these. Whether a row may repeat is a data quality question, and data
# quality checks arrive in milestone 3. Until then, a repeated row is counted as it appears.

SOURCE_SCHEMAS: dict[str, TableSchema] = {
    schema.name: schema
    for schema in [
        TableSchema("products", (
            Column("product_id", "string"),
            Column("product_name", "string"),
            Column("category", "string", description="Hydration, Camp, or Apparel"),
        )),
        TableSchema("orders", (
            Column("order_id", "string"),
            Column("order_date", "date"),
            Column("status", "string", description="completed or cancelled"),
        )),
        TableSchema("order_items", (
            Column("order_item_id", "string"),
            Column("order_id", "string"),
            Column("product_id", "string"),
            Column("quantity", "integer"),
            Column("unit_list_price", "decimal", description="list price of one unit"),
            Column("discount_amount", "decimal", description="discount on the whole line"),
        )),
        TableSchema("refunds", (
            Column("refund_id", "string"),
            Column("order_item_id", "string"),
            Column("product_id", "string"),
            Column("refund_date", "date"),
            Column("refund_amount", "decimal"),
            Column("return_handling_cost", "decimal"),
        )),
        TableSchema("shipments", (
            Column("shipment_id", "string"),
            Column("order_item_id", "string"),
            Column("product_id", "string"),
            Column("ship_date", "date"),
            Column("pick_pack_cost", "decimal"),
            Column("carrier_cost", "decimal"),
        )),
        TableSchema("payment_fees", (
            Column("fee_id", "string"),
            Column("order_item_id", "string"),
            Column("product_id", "string"),
            Column("capture_date", "date"),
            Column("fee_amount", "decimal"),
        )),
        TableSchema("product_costs", (
            Column("product_id", "string"),
            Column("month", "month", description="the month this cost is in force, like 2026-10"),
            Column("unit_cost", "decimal", description="what the retailer pays for one unit"),
        )),
    ]
}  # fmt: skip

KEY = ("month", "product_id")
MONTH = Column("month", "month", description="text like 2026-10")
PRODUCT = Column("product_id", "string")

MONEY_TERMS = [
    "gross_sales", "discounts", "refunds", "net_sales", "product_cost", "gross_profit",
    "fulfillment_cost", "shipping_cost", "payment_fees", "return_cost", "contribution_profit",
]  # fmt: skip
NULLABLE_TERMS = {"product_cost", "gross_profit", "contribution_profit"}

PROFIT_COLUMNS = (
    MONTH, PRODUCT, Column("units_sold", "integer"),
    *(Column(term, "decimal", nullable=term in NULLABLE_TERMS) for term in MONEY_TERMS),
    Column("metric_version", "string"),
)  # fmt: skip

PROFIT_RULE = (
    "One row for every row of sales. Take units_sold, gross_sales, and discounts from sales. "
    "Take refunds and return_cost from refund_totals, fulfillment_cost and shipping_cost from "
    "delivery_costs, payment_fees from fee_totals, and product_cost from product_cost, matching "
    "on month and product_id. Where a product has no refunds, delivery costs, or fees in a "
    "month, use 0.00 for those terms. "
    "net_sales = gross_sales - discounts - refunds. "
    "gross_profit = net_sales - product_cost. "
    "contribution_profit = gross_profit - fulfillment_cost - shipping_cost - payment_fees - "
    "return_cost. "
    "If product_cost is missing, product_cost, gross_profit, and contribution_profit are "
    "missing (null); never use zero in its place. "
    f"metric_version is the text {METRIC_VERSION} on every row."
)

SPECS: dict[str, TransformationSpec] = {
    spec.name: spec
    for spec in [
        TransformationSpec(
            name="sales",
            inputs=("orders", "order_items"),
            output=TableSchema("sales", (
                MONTH, PRODUCT, Column("units_sold", "integer"),
                Column("gross_sales", "decimal"), Column("discounts", "decimal"),
            ), KEY),
            rule=(
                "For order lines whose order is not cancelled, grouped by the month of the "
                "order's order_date and by product_id: units_sold is the sum of quantity; "
                "gross_sales is the sum of quantity x unit_list_price; discounts is the sum of "
                "discount_amount. A line that appears more than once is counted each time."
            ),
            definitions=("units_sold", "gross_sales", "discounts"),
        ),
        TransformationSpec(
            name="refund_totals",
            inputs=("refunds",),
            output=TableSchema("refund_totals", (
                MONTH, PRODUCT, Column("refunds", "decimal"), Column("return_cost", "decimal"),
            ), KEY),
            rule=(
                "Grouped by the month of refund_date and by product_id: refunds is the sum of "
                "refund_amount; return_cost is the sum of return_handling_cost. A refund counts "
                "in the month it was issued, whenever the order was placed."
            ),
            definitions=("refunds", "return_cost"),
        ),
        TransformationSpec(
            name="delivery_costs",
            inputs=("shipments",),
            output=TableSchema("delivery_costs", (
                MONTH, PRODUCT,
                Column("fulfillment_cost", "decimal"), Column("shipping_cost", "decimal"),
            ), KEY),
            rule=(
                "Grouped by the month of ship_date and by product_id: fulfillment_cost is the "
                "sum of pick_pack_cost; shipping_cost is the sum of carrier_cost."
            ),
            definitions=("fulfillment_cost", "shipping_cost"),
        ),
        TransformationSpec(
            name="fee_totals",
            inputs=("payment_fees",),
            output=TableSchema("fee_totals", (
                MONTH, PRODUCT, Column("payment_fees", "decimal"),
            ), KEY),
            rule=(
                "Grouped by the month of capture_date and by product_id: payment_fees is the "
                "sum of fee_amount."
            ),
            definitions=("payment_fees",),
        ),
        TransformationSpec(
            name="product_cost",
            inputs=("sales", "product_costs"),
            output=TableSchema("product_cost", (
                MONTH, PRODUCT, Column("product_cost", "decimal", nullable=True),
            ), KEY),
            rule=(
                "One row for every row of sales. product_cost is units_sold x unit_cost, using "
                "the unit_cost for the same product_id and month. If there is no cost for that "
                "product and month, keep the row and leave product_cost missing (null); never "
                "use zero in its place."
            ),
            definitions=("product_cost",),
        ),
        TransformationSpec(
            name="monthly_product_profit",
            inputs=("sales", "refund_totals", "delivery_costs", "fee_totals", "product_cost"),
            output=TableSchema("monthly_product_profit", PROFIT_COLUMNS, KEY),
            rule=PROFIT_RULE,
            definitions=("net_sales", "gross_profit", "contribution_profit"),
        ),
    ]
}  # fmt: skip

# A task used only in the lab: the whole calculation in one step, straight from the business's
# records. It is the "simple approach" that the six small transformations are compared with.
# The pipeline does not run it.
ALL_IN_ONE = TransformationSpec(
    name="profit_all_in_one",
    inputs=("orders", "order_items", "refunds", "shipments", "payment_fees", "product_costs"),
    output=TableSchema("profit_all_in_one", PROFIT_COLUMNS, KEY),
    rule=(
        "Calculate monthly profit per product straight from the business's records. "
        "One row for every month and product that has sales. "
        "Sales count in the month of the order's order_date and leave out cancelled orders: "
        "units_sold is the sum of quantity, gross_sales the sum of quantity x unit_list_price, "
        "discounts the sum of discount_amount. "
        "refunds (sum of refund_amount) and return_cost (sum of return_handling_cost) count in "
        "the month of refund_date, whenever the order was placed. "
        "fulfillment_cost (sum of pick_pack_cost) and shipping_cost (sum of carrier_cost) count "
        "in the month of ship_date. payment_fees (sum of fee_amount) count in the month of "
        "capture_date. Where a product has none of these in a month, use 0.00. "
        "product_cost is units_sold x the unit_cost for that product and month. "
        "net_sales = gross_sales - discounts - refunds. "
        "gross_profit = net_sales - product_cost. "
        "contribution_profit = gross_profit - fulfillment_cost - shipping_cost - payment_fees - "
        "return_cost. "
        "If there is no unit_cost for a product and month, product_cost, gross_profit, and "
        "contribution_profit are missing (null); never use zero in its place. "
        "A row that appears more than once in a table is counted each time. "
        f"metric_version is the text {METRIC_VERSION} on every row."
    ),
    definitions=tuple(MONEY_TERMS),
)

TASKS: dict[str, TransformationSpec] = {**SPECS, ALL_IN_ONE.name: ALL_IN_ONE}


def schema_for(table_name: str) -> TableSchema:
    """The schema of a source table or of a transformation's output."""
    if table_name in SOURCE_SCHEMAS:
        return SOURCE_SCHEMAS[table_name]
    return TASKS[table_name].output


def ordered_specs() -> list[TransformationSpec]:
    """The six pipeline transformations, each after the ones it reads from."""
    done: list[TransformationSpec] = []
    remaining = list(SPECS.values())
    while remaining:
        ready = [
            spec for spec in remaining
            if all(name in SOURCE_SCHEMAS or name in {d.name for d in done} for name in spec.inputs)
        ]  # fmt: skip
        if not ready:
            raise ValueError("The transformations depend on each other in a circle")
        done.extend(ready)
        remaining = [spec for spec in remaining if spec not in ready]
    return done
