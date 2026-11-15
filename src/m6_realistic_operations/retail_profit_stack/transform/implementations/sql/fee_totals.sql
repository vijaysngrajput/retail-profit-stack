-- fee_totals: payment fees by capture month and product (LLD section 5).
SELECT
    strftime(capture_date, '%Y-%m') AS month,
    product_id,
    SUM(fee_amount) AS payment_fees
FROM payment_fees
GROUP BY 1, 2
