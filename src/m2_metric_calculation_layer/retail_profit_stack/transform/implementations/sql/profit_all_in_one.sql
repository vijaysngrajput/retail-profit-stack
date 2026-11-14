-- profit_all_in_one: the whole calculation in one query (a lab task, not run by the pipeline).
-- The rule that makes it correct: sum each table on its own first, then join the sums.
-- Joining order lines straight to refunds or shipments would repeat rows and inflate totals.
WITH sales AS (
    SELECT strftime(o.order_date, '%Y-%m') AS month, i.product_id,
           SUM(i.quantity) AS units_sold,
           SUM(i.quantity * i.unit_list_price) AS gross_sales,
           SUM(i.discount_amount) AS discounts
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled'
    GROUP BY 1, 2
), refund_totals AS (
    SELECT strftime(refund_date, '%Y-%m') AS month, product_id,
           SUM(refund_amount) AS refunds, SUM(return_handling_cost) AS return_cost
    FROM refunds GROUP BY 1, 2
), delivery_costs AS (
    SELECT strftime(ship_date, '%Y-%m') AS month, product_id,
           SUM(pick_pack_cost) AS fulfillment_cost, SUM(carrier_cost) AS shipping_cost
    FROM shipments GROUP BY 1, 2
), fee_totals AS (
    SELECT strftime(capture_date, '%Y-%m') AS month, product_id, SUM(fee_amount) AS payment_fees
    FROM payment_fees GROUP BY 1, 2
), joined AS (
    SELECT s.month, s.product_id, s.units_sold, s.gross_sales, s.discounts,
           COALESCE(r.refunds, 0) AS refunds,
           s.units_sold * c.unit_cost AS product_cost,
           COALESCE(d.fulfillment_cost, 0) AS fulfillment_cost,
           COALESCE(d.shipping_cost, 0) AS shipping_cost,
           COALESCE(f.payment_fees, 0) AS payment_fees,
           COALESCE(r.return_cost, 0) AS return_cost
    FROM sales AS s
    LEFT JOIN refund_totals AS r ON r.month = s.month AND r.product_id = s.product_id
    LEFT JOIN delivery_costs AS d ON d.month = s.month AND d.product_id = s.product_id
    LEFT JOIN fee_totals AS f ON f.month = s.month AND f.product_id = s.product_id
    LEFT JOIN product_costs AS c ON c.month = s.month AND c.product_id = s.product_id
)
SELECT month, product_id, units_sold, gross_sales, discounts, refunds,
       gross_sales - discounts - refunds AS net_sales,
       product_cost,
       gross_sales - discounts - refunds - product_cost AS gross_profit,
       fulfillment_cost, shipping_cost, payment_fees, return_cost,
       gross_sales - discounts - refunds - product_cost
           - fulfillment_cost - shipping_cost - payment_fees - return_cost AS contribution_profit,
       '1.0.0' AS metric_version
FROM joined
