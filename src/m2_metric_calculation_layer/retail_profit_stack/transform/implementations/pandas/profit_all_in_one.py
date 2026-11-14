"""profit_all_in_one: the whole calculation in one function (a lab task, not run by the pipeline).

The rule that makes it correct: sum each table on its own first, then merge the sums. Merging
order lines straight onto refunds or shipments would repeat rows and inflate the totals.
"""

import pandas as pd

KEY = ["month", "product_id"]
ZERO_WHEN_ABSENT = ["refunds", "return_cost", "fulfillment_cost", "shipping_cost", "payment_fees"]
COLUMNS = [
    "month", "product_id", "units_sold", "gross_sales", "discounts", "refunds", "net_sales",
    "product_cost", "gross_profit", "fulfillment_cost", "shipping_cost", "payment_fees",
    "return_cost", "contribution_profit", "metric_version",
]  # fmt: skip


def monthly(frame: pd.DataFrame, date_column: str, **sums: str) -> pd.DataFrame:
    """Sum columns of one table by the month of a date column and by product."""
    frame = frame.assign(month=frame[date_column].dt.strftime("%Y-%m"))
    named = {name: (column, "sum") for name, column in sums.items()}
    return frame.groupby(KEY, as_index=False).agg(**named)


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    lines = inputs["order_items"].merge(inputs["orders"], on="order_id")
    lines = lines[lines["status"] != "cancelled"]
    lines = lines.assign(gross=lines["quantity"] * lines["unit_list_price"])
    profit = monthly(
        lines, "order_date", units_sold="quantity", gross_sales="gross", discounts="discount_amount"
    )

    sums = [
        monthly(
            inputs["refunds"],
            "refund_date",
            refunds="refund_amount",
            return_cost="return_handling_cost",
        ),
        monthly(
            inputs["shipments"],
            "ship_date",
            fulfillment_cost="pick_pack_cost",
            shipping_cost="carrier_cost",
        ),
        monthly(inputs["payment_fees"], "capture_date", payment_fees="fee_amount"),
        inputs["product_costs"],
    ]
    for table in sums:
        profit = profit.merge(table, on=KEY, how="left")
    profit[ZERO_WHEN_ABSENT] = profit[ZERO_WHEN_ABSENT].fillna(0.0)

    profit["product_cost"] = profit["units_sold"] * profit["unit_cost"]
    profit["net_sales"] = profit["gross_sales"] - profit["discounts"] - profit["refunds"]
    profit["gross_profit"] = profit["net_sales"] - profit["product_cost"]
    profit["contribution_profit"] = (
        profit["gross_profit"] - profit["fulfillment_cost"] - profit["shipping_cost"]
        - profit["payment_fees"] - profit["return_cost"]
    )  # fmt: skip
    profit["metric_version"] = "1.0.0"
    return profit.filter(items=COLUMNS)
