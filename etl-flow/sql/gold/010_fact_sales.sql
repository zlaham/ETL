-- Second load.
-- Reads silver.order_line for the run in temp table eltl_run.
-- Writes gold.fact_sales. Pending and cancelled lines stay in silver.

DELETE FROM gold.fact_sales
WHERE run_id = (SELECT run_id FROM eltl_run);

DELETE FROM gold.load_exclusion
WHERE run_id = (SELECT run_id FROM eltl_run);

INSERT INTO gold.fact_sales (
    fact_id,
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    order_date,
    status,
    currency,
    quantity,
    unit_price,
    amount
)
SELECT
    row_number() OVER (ORDER BY order_id)::integer,
    run_id,
    order_id,
    customer_id,
    product_id,
    sku,
    order_date,
    status,
    currency,
    quantity,
    unit_price,
    amount
FROM silver.order_line
WHERE run_id = (SELECT run_id FROM eltl_run)
  AND status IN ('paid', 'shipped', 'completed');

INSERT INTO gold.load_exclusion (
    run_id,
    order_id,
    sku,
    status,
    order_date,
    amount,
    reason
)
SELECT
    run_id,
    order_id,
    sku,
    status,
    order_date,
    amount,
    status || ' stays in silver; fact_sales receives paid, shipped, and completed'
FROM silver.order_line
WHERE run_id = (SELECT run_id FROM eltl_run)
  AND status NOT IN ('paid', 'shipped', 'completed');
