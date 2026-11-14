"""monthly_product_profit: the profit table the six tools read (LLD section 5).

Every input is already summed to one row per month and product, so these merges cannot
repeat a row. A missing product_cost makes the two profit lines missing.
"""

import pandas as pd

KEY = ["month", "product_id"]
ZERO_WHEN_ABSENT = ["refunds", "return_cost", "fulfillment_cost", "shipping_cost", "payment_fees"]
COLUMNS = [
    "month", "product_id", "units_sold", "gross_sales", "discounts", "refunds", "net_sales",
    "product_cost", "gross_profit", "fulfillment_cost", "shipping_cost", "payment_fees",
    "return_cost", "contribution_profit", "metric_version",
]  # fmt: skip


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    profit = inputs["sales"]
    for name in ["refund_totals", "delivery_costs", "fee_totals", "product_cost"]:
        profit = profit.merge(inputs[name], on=KEY, how="left")
    profit[ZERO_WHEN_ABSENT] = profit[ZERO_WHEN_ABSENT].fillna(0.0)

    profit["net_sales"] = profit["gross_sales"] - profit["discounts"] - profit["refunds"]
    profit["gross_profit"] = profit["net_sales"] - profit["product_cost"]
    profit["contribution_profit"] = (
        profit["gross_profit"] - profit["fulfillment_cost"] - profit["shipping_cost"]
        - profit["payment_fees"] - profit["return_cost"]
    )  # fmt: skip
    profit["metric_version"] = "1.0.0"
    return profit.filter(items=COLUMNS)
