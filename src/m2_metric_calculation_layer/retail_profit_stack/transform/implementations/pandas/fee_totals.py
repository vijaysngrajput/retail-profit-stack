"""fee_totals: payment fees by capture month and product (LLD section 5)."""

import pandas as pd


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fees = inputs["payment_fees"]
    fees = fees.assign(month=fees["capture_date"].dt.strftime("%Y-%m"))
    return fees.groupby(["month", "product_id"], as_index=False).agg(
        payment_fees=("fee_amount", "sum"),
    )
