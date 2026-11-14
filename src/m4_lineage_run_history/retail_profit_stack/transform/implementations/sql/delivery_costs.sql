-- delivery_costs: pick-and-pack and carrier cost by ship month and product (LLD section 5).
SELECT
    strftime(ship_date, '%Y-%m') AS month,
    product_id,
    SUM(pick_pack_cost) AS fulfillment_cost,
    SUM(carrier_cost) AS shipping_cost
FROM shipments
GROUP BY 1, 2
