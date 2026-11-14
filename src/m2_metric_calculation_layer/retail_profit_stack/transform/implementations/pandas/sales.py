"""sales: units, gross sales, and discounts by order month and product (LLD section 5).

Cancelled orders are left out. A line that appears twice is counted twice.
"""

import pandas as pd


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    lines = inputs["order_items"].merge(inputs["orders"], on="order_id")
    lines = lines[lines["status"] != "cancelled"]
    lines = lines.assign(
        month=lines["order_date"].dt.strftime("%Y-%m"),
        gross=lines["quantity"] * lines["unit_list_price"],
    )
    return lines.groupby(["month", "product_id"], as_index=False).agg(
        units_sold=("quantity", "sum"),
        gross_sales=("gross", "sum"),
        discounts=("discount_amount", "sum"),
    )
