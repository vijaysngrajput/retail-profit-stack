"""product_cost: units sold times unit cost (LLD section 5).

A left merge keeps every sales row. With no cost row, product_cost is missing, never zero.
"""

import pandas as pd


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    costed = inputs["sales"].merge(inputs["product_costs"], on=["month", "product_id"], how="left")
    costed["product_cost"] = costed["units_sold"] * costed["unit_cost"]
    return costed.filter(items=["month", "product_id", "product_cost"])
