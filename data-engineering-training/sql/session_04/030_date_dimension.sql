-- dim_date is a calendar, not the distinct dates that happened to be sold.
-- The key is the UTC date from the Session 3 contract, stored as YYYYMMDD.
-- October 2026 is the month this extract can land on. Days with no sales stay in the dimension.

CREATE OR REPLACE TABLE dim_date AS
SELECT
    CAST(strftime(full_date, '%Y%m%d') AS INTEGER) AS date_key,
    full_date,
    year(full_date) AS year,
    quarter(full_date) AS quarter,
    month(full_date) AS month,
    monthname(full_date) AS month_name,
    dayname(full_date) AS day_of_week,
    isodow(full_date) IN (6, 7) AS is_weekend
FROM (
    SELECT unnest(generate_series(DATE '2026-10-01', DATE '2026-10-31', INTERVAL 1 DAY)) AS full_date
);
