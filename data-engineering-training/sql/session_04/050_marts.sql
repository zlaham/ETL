-- Marts are queries we are willing to store. They are built from the facts.
-- A mart that joins the current dimension instead of the fact's key is a
-- different question, and it is not this table.

CREATE OR REPLACE TABLE mart_sales_by_day_category AS
SELECT
    dates.full_date AS order_date,
    dates.day_of_week,
    dates.is_weekend,
    products.category,
    CAST(SUM(facts.gross_amount) AS DECIMAL(12, 2)) AS gross_amount,
    CAST(SUM(facts.quantity) AS INTEGER) AS units
FROM fct_sales_order_lines AS facts
JOIN dim_date AS dates ON dates.date_key = facts.order_date_key
JOIN dim_product AS products ON products.product_key = facts.product_key
GROUP BY dates.full_date, dates.day_of_week, dates.is_weekend, products.category;

CREATE OR REPLACE TABLE kpi_commercial AS
SELECT
    gross.gross_sales,
    returns.return_amount,
    gross.gross_sales - returns.return_amount AS net_sales,
    gross.order_count,
    gross.line_count,
    gross.units_sold,
    returns.units_returned,
    CAST(gross.gross_sales / gross.order_count AS DECIMAL(12, 2)) AS average_order_gross
FROM (
    SELECT
        CAST(SUM(gross_amount) AS DECIMAL(12, 2)) AS gross_sales,
        COUNT(DISTINCT order_id) AS order_count,
        COUNT(*) AS line_count,
        CAST(SUM(quantity) AS INTEGER) AS units_sold
    FROM fct_sales_order_lines
) AS gross
CROSS JOIN (
    SELECT
        CAST(COALESCE(SUM(return_amount), 0) AS DECIMAL(12, 2)) AS return_amount,
        CAST(COALESCE(SUM(quantity), 0) AS INTEGER) AS units_returned
    FROM fct_returns
) AS returns;

-- Which fact uses which dimension role. This is the bus, written as data
-- so the room can query it instead of trusting a slide.
CREATE OR REPLACE TABLE gold_bus_matrix AS
SELECT * FROM (
    VALUES
        (
            'fct_sales_order_lines',
            'customer version on the order date',
            'product version on the order date',
            'order date'
        ),
        (
            'fct_returns',
            'customer version on the return date',
            'product version on the return date',
            'return date; the sale date is a second role of dim_date'
        ),
        (
            'mart_sales_by_day_category',
            'not carried; aggregate above customer',
            'category of the product key stored on the fact',
            'order date'
        )
) AS matrix(dataset, customer_role, product_role, date_role);

CREATE OR REPLACE TABLE gold_contract AS
SELECT * FROM (
    VALUES
        (
            'fct_sales_order_lines',
            'One row is one valid order line in its current authoritative state.'
        ),
        (
            'fct_returns',
            'One row is one accepted return event. It does not edit the sale.'
        ),
        (
            'dim_customer',
            'One row is one version of a customer. Type 2 adds a row. Type 1 updates the attribute.'
        ),
        (
            'dim_product',
            'One row is one version of a product. Historical sales keep the version that was effective on the order date.'
        ),
        (
            'dim_date',
            'One row is one calendar date in the published month, including dates with no sales.'
        ),
        (
            'mart_sales_by_day_category',
            'One row is category revenue for one order date, summed from the sales fact.'
        )
) AS contract(dataset, grain);
