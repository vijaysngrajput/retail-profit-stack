-- monthly_product_profit: the profit table the six tools read (LLD section 5).
-- Every input is already summed to one row per month and product, so these joins
-- cannot repeat a row. A null product_cost makes the two profit lines null.
WITH joined AS (
    SELECT
        s.month,
        s.product_id,
        s.units_sold,
        s.gross_sales,
        s.discounts,
        COALESCE(r.refunds, 0) AS refunds,
        c.product_cost,
        COALESCE(d.fulfillment_cost, 0) AS fulfillment_cost,
        COALESCE(d.shipping_cost, 0) AS shipping_cost,
        COALESCE(f.payment_fees, 0) AS payment_fees,
        COALESCE(r.return_cost, 0) AS return_cost
    FROM sales AS s
    LEFT JOIN refund_totals AS r ON r.month = s.month AND r.product_id = s.product_id
    LEFT JOIN delivery_costs AS d ON d.month = s.month AND d.product_id = s.product_id
    LEFT JOIN fee_totals AS f ON f.month = s.month AND f.product_id = s.product_id
    LEFT JOIN product_cost AS c ON c.month = s.month AND c.product_id = s.product_id
)
SELECT
    month,
    product_id,
    units_sold,
    gross_sales,
    discounts,
    refunds,
    gross_sales - discounts - refunds AS net_sales,
    product_cost,
    gross_sales - discounts - refunds - product_cost AS gross_profit,
    fulfillment_cost,
    shipping_cost,
    payment_fees,
    return_cost,
    gross_sales - discounts - refunds - product_cost
        - fulfillment_cost - shipping_cost - payment_fees - return_cost AS contribution_profit,
    '1.0.0' AS metric_version
FROM joined
