-- Check: totals_do_not_match
-- Adds up the kept records for each month, product, and term, and compares each total with
-- the same total in the profit table. It returns every total that differs.
-- This runs after the calculation. There is no single bad row to point at.

WITH record_totals AS (
    SELECT strftime(o.order_date, '%Y-%m') AS month, i.product_id, 'units_sold' AS term,
           sum(i.quantity) AS total
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled' GROUP BY ALL
    UNION ALL
    SELECT strftime(o.order_date, '%Y-%m'), i.product_id, 'gross_sales',
           sum(i.quantity * i.unit_list_price)
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled' GROUP BY ALL
    UNION ALL
    SELECT strftime(o.order_date, '%Y-%m'), i.product_id, 'discounts', sum(i.discount_amount)
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
    WHERE o.status <> 'cancelled' GROUP BY ALL
    UNION ALL
    SELECT strftime(refund_date, '%Y-%m'), product_id, 'refunds', sum(refund_amount)
    FROM refunds GROUP BY ALL
    UNION ALL
    SELECT strftime(refund_date, '%Y-%m'), product_id, 'return_cost', sum(return_handling_cost)
    FROM refunds GROUP BY ALL
    UNION ALL
    SELECT strftime(ship_date, '%Y-%m'), product_id, 'fulfillment_cost', sum(pick_pack_cost)
    FROM shipments GROUP BY ALL
    UNION ALL
    SELECT strftime(ship_date, '%Y-%m'), product_id, 'shipping_cost', sum(carrier_cost)
    FROM shipments GROUP BY ALL
    UNION ALL
    SELECT strftime(capture_date, '%Y-%m'), product_id, 'payment_fees', sum(fee_amount)
    FROM payment_fees GROUP BY ALL
),
table_totals AS (
    SELECT month, product_id, term, total
    FROM (
        SELECT month, product_id, CAST(units_sold AS DOUBLE) AS units_sold, gross_sales,
               discounts, refunds, return_cost, fulfillment_cost, shipping_cost, payment_fees
        FROM monthly_product_profit
    )
    UNPIVOT (total FOR term IN (units_sold, gross_sales, discounts, refunds, return_cost,
                                fulfillment_cost, shipping_cost, payment_fees))
)
SELECT coalesce(r.month, t.month) AS month,
       coalesce(r.product_id, t.product_id) AS product_id,
       'monthly_product_profit' AS source_table,
       NULL AS row_number,
       coalesce(r.term, t.term) || ': the records add up to '
           || printf('%.2f', coalesce(r.total, 0)) || ', but the profit table says '
           || printf('%.2f', coalesce(t.total, 0)) || '.' AS detail
FROM record_totals AS r
FULL OUTER JOIN table_totals AS t
    ON t.month = r.month AND t.product_id = r.product_id AND t.term = r.term
WHERE abs(coalesce(r.total, 0) - coalesce(t.total, 0)) > 0.005
