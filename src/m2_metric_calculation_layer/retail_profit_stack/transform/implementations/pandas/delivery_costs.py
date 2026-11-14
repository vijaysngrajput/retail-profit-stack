"""delivery_costs: pick-and-pack and carrier cost by ship month and product (LLD section 5)."""

import pandas as pd


def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    shipments = inputs["shipments"]
    shipments = shipments.assign(month=shipments["ship_date"].dt.strftime("%Y-%m"))
    return shipments.groupby(["month", "product_id"], as_index=False).agg(
        fulfillment_cost=("pick_pack_cost", "sum"),
        shipping_cost=("carrier_cost", "sum"),
    )
