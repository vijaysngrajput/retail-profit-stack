-- Check: event_out_of_order
-- Finds each refund and each shipment that is dated before its order.
-- line_orders has one row per order line, even when a line appears twice in order_items.

WITH line_orders AS (
    SELECT DISTINCT i.order_item_id, o.order_date
    FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id
)
SELECT strftime(r.refund_date, '%Y-%m') AS month,
       r.product_id,
       'refunds' AS source_table,
       r.row_number,
       'Refund dated ' || r.refund_date || ', but its order is dated ' || l.order_date || '.' AS detail
FROM refunds AS r JOIN line_orders AS l ON l.order_item_id = r.order_item_id
WHERE r.refund_date < l.order_date

UNION ALL

SELECT strftime(s.ship_date, '%Y-%m') AS month,
       s.product_id,
       'shipments' AS source_table,
       s.row_number,
       'Shipment dated ' || s.ship_date || ', but its order is dated ' || l.order_date || '.' AS detail
FROM shipments AS s JOIN line_orders AS l ON l.order_item_id = s.order_item_id
WHERE s.ship_date < l.order_date
