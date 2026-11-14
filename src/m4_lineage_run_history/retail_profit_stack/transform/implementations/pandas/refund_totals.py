"""refund_totals: refunds and return handling cost by refund month and product (LLD section 5).

A refund counts in the month it was issued, whenever the order was placed.
"""

import pandas as pd


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    refunds = inputs["refunds"]
    refunds = refunds.assign(month=refunds["refund_date"].dt.strftime("%Y-%m"))
    return refunds.groupby(["month", "product_id"], as_index=False).agg(
        refunds=("refund_amount", "sum"),
        return_cost=("return_handling_cost", "sum"),
    )
