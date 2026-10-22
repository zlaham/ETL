-- fct_sales_order_lines
-- Grain: one current, valid, recognized-revenue order line.
-- The foreign keys are the dimension versions in effect on the order date.
-- gross_amount is quantity * unit_price. This fact does not store returns.

CREATE OR REPLACE TABLE fct_sales_order_lines AS
SELECT
    sales.order_line_id,
    sales.order_id,
    customers.customer_key,
    products.product_key,
    dates.date_key AS order_date_key,
    sales.quantity,
    sales.unit_price,
    sales.gross_amount,
    sales.currency
FROM silver_sales AS sales
JOIN dim_customer AS customers
  ON customers.customer_id = sales.customer_id
 AND version_covers(customers.effective_from, customers.effective_to, sales.order_date)
JOIN dim_product AS products
  ON products.product_id = sales.product_id
 AND version_covers(products.effective_from, products.effective_to, sales.order_date)
JOIN dim_date AS dates
  ON dates.full_date = sales.order_date;

-- A return is its own fact. It points at the versions in effect on the return
-- date, which are not required to be the versions stored on the sale.
CREATE OR REPLACE TABLE return_resolution AS
SELECT
    events.return_id,
    events.order_line_id,
    CAST(events.quantity AS INTEGER) AS quantity,
    CAST(events.return_amount AS DECIMAL(12, 2)) AS return_amount,
    CAST(events.return_date AS DATE) AS return_date,
    events.reason,
    sales.customer_id,
    sales.product_id,
    sales.order_date AS sale_date,
    sales.quantity AS sold_quantity,
    sales.unit_price AS sale_unit_price,
    CASE
        WHEN sales.order_line_id IS NULL THEN 'return_unknown_line'
        WHEN CAST(events.quantity AS INTEGER) <= 0
          OR CAST(events.quantity AS INTEGER) > sales.quantity THEN 'return_quantity_invalid'
        WHEN CAST(events.return_amount AS DECIMAL(12, 2))
             <> CAST(CAST(events.quantity AS INTEGER) * sales.unit_price AS DECIMAL(12, 2))
            THEN 'return_amount_mismatch'
        WHEN CAST(events.return_date AS DATE) < sales.order_date THEN 'return_before_sale'
        ELSE NULL
    END AS reject_reason
FROM return_events AS events
LEFT JOIN silver_sales AS sales USING (order_line_id);

CREATE OR REPLACE TABLE fct_returns AS
SELECT
    resolved.return_id,
    resolved.order_line_id,
    customers.customer_key,
    products.product_key,
    sale_dates.date_key AS sale_date_key,
    return_dates.date_key AS return_date_key,
    resolved.quantity,
    resolved.return_amount,
    'USD' AS currency
FROM return_resolution AS resolved
JOIN dim_customer AS customers
  ON customers.customer_id = resolved.customer_id
 AND version_covers(customers.effective_from, customers.effective_to, resolved.return_date)
JOIN dim_product AS products
  ON products.product_id = resolved.product_id
 AND version_covers(products.effective_from, products.effective_to, resolved.return_date)
JOIN dim_date AS sale_dates
  ON sale_dates.full_date = resolved.sale_date
JOIN dim_date AS return_dates
  ON return_dates.full_date = resolved.return_date
WHERE resolved.reject_reason IS NULL;

-- Recognized revenue requires a real customer and a real product.
-- The unknown members exist so a query can name the missing party.
-- They are not a bucket we pour sales into.
CREATE OR REPLACE TABLE gold_suspense AS
SELECT
    late_sales.order_line_id,
    late_sales.order_id,
    late_sales.customer_id,
    late_sales.product_id,
    CAST(late_sales.order_date AS DATE) AS event_date,
    CAST(CAST(late_sales.quantity AS INTEGER) * CAST(late_sales.unit_price AS DECIMAL(12, 2)) AS DECIMAL(12, 2)) AS amount,
    'unknown_customer' AS reason
FROM late_sales
WHERE late_sales.customer_id NOT IN (
        SELECT customer_id FROM dim_customer WHERE customer_key > 0
    )
   OR late_sales.product_id NOT IN (
        SELECT product_id FROM dim_product WHERE product_key > 0
    )
UNION ALL
SELECT
    return_resolution.order_line_id,
    NULL,
    return_resolution.customer_id,
    return_resolution.product_id,
    return_resolution.return_date,
    return_resolution.return_amount,
    return_resolution.reject_reason
FROM return_resolution
WHERE return_resolution.reject_reason IS NOT NULL
UNION ALL
SELECT
    resolved.order_line_id,
    NULL,
    resolved.customer_id,
    resolved.product_id,
    resolved.return_date,
    resolved.return_amount,
    CASE
        WHEN resolved.sale_date NOT IN (SELECT full_date FROM dim_date)
          OR resolved.return_date NOT IN (SELECT full_date FROM dim_date)
            THEN 'return_outside_calendar'
        WHEN NOT EXISTS (
            SELECT 1
            FROM dim_customer AS customers
            WHERE customers.customer_id = resolved.customer_id
              AND version_covers(customers.effective_from, customers.effective_to, resolved.return_date)
        ) THEN 'return_customer_version_missing'
        ELSE 'return_product_version_missing'
    END AS reason
FROM return_resolution AS resolved
WHERE resolved.reject_reason IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM fct_returns AS posted WHERE posted.return_id = resolved.return_id
  )
UNION ALL
SELECT
    sales.order_line_id,
    sales.order_id,
    sales.customer_id,
    sales.product_id,
    sales.order_date,
    sales.gross_amount,
    'sale_not_conformed' AS reason
FROM silver_sales AS sales
WHERE sales.order_line_id NOT IN (
    SELECT order_line_id FROM fct_sales_order_lines
);
