-- refund_totals: refunds and return handling cost by refund month and product (LLD section 5).
-- A refund counts in the month it was issued, whenever the order was placed.
SELECT
    strftime(refund_date, '%Y-%m') AS month,
    product_id,
    SUM(refund_amount) AS refunds,
    SUM(return_handling_cost) AS return_cost
FROM refunds
GROUP BY 1, 2
