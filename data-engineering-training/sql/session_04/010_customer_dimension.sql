-- dim_customer: one row per customer version.
-- Type 1 corrects an attribute in place. Type 2 appends a version.
-- Keys are allocated once and stored. They are not row numbers of today's set.

CREATE OR REPLACE TABLE customer_version_plan AS
WITH name_fix AS (
    SELECT customer_id, title_case(new_value) AS customer_name
    FROM customer_changes
    WHERE change_type = 'type1'
      AND attribute = 'customer_name'
),
initial AS (
    SELECT
        customers.customer_id,
        COALESCE(name_fix.customer_name, customers.customer_name) AS customer_name,
        customers.country_code,
        customers.customer_segment,
        CAST(customers.source_updated_at AS DATE) AS effective_from,
        1 AS version_number,
        'initial_publish' AS change_reason
    FROM silver_customers AS customers
    LEFT JOIN name_fix ON name_fix.customer_id = customers.customer_id
),
upgrades AS (
    SELECT
        customers.customer_id,
        COALESCE(name_fix.customer_name, customers.customer_name) AS customer_name,
        customers.country_code,
        title_case(changes.new_value) AS customer_segment,
        CAST(changes.effective_from AS DATE) AS effective_from,
        2 AS version_number,
        changes.reason AS change_reason
    FROM silver_customers AS customers
    JOIN customer_changes AS changes
      ON changes.customer_id = customers.customer_id
     AND changes.change_type = 'type2'
     AND changes.attribute = 'customer_segment'
    LEFT JOIN name_fix ON name_fix.customer_id = customers.customer_id
),
arrived AS (
    SELECT
        customer_id,
        title_case(customer_name) AS customer_name,
        UPPER(TRIM(country_code)) AS country_code,
        title_case(customer_segment) AS customer_segment,
        CAST(effective_from AS DATE) AS effective_from,
        1 AS version_number,
        reason AS change_reason
    FROM new_customers
),
combined AS (
    SELECT * FROM initial
    UNION ALL
    SELECT * FROM upgrades
    UNION ALL
    SELECT * FROM arrived
),
sequenced AS (
    SELECT
        *,
        LEAD(effective_from) OVER (
            PARTITION BY customer_id
            ORDER BY version_number
        ) AS next_effective_from
    FROM combined
)
SELECT
    customer_id,
    customer_name,
    country_code,
    customer_segment,
    effective_from,
    CAST(next_effective_from - INTERVAL 1 DAY AS DATE) AS effective_to,
    next_effective_from IS NULL AS is_current,
    version_number,
    change_reason
FROM sequenced;

CREATE TABLE IF NOT EXISTS surrogate_registry (
    entity_name VARCHAR NOT NULL,
    business_key VARCHAR NOT NULL,
    version_number INTEGER NOT NULL,
    surrogate_key INTEGER NOT NULL,
    PRIMARY KEY (entity_name, business_key, version_number),
    UNIQUE (entity_name, surrogate_key)
);

-- Phase 1: the customers Silver already published, in business-key order.
-- On an empty registry this is C100 = 1 through C107 = 8.
CREATE OR REPLACE TEMP TABLE customer_keys_phase1 AS
SELECT
    customers.customer_id AS business_key,
    1 AS version_number,
    base.max_key + ROW_NUMBER() OVER (ORDER BY customers.customer_id) AS surrogate_key
FROM silver_customers AS customers
CROSS JOIN (
    SELECT COALESCE(MAX(surrogate_key), 0) AS max_key
    FROM surrogate_registry
    WHERE entity_name = 'customer'
) AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM surrogate_registry AS registry
    WHERE registry.entity_name = 'customer'
      AND registry.business_key = customers.customer_id
      AND registry.version_number = 1
);

INSERT INTO surrogate_registry
SELECT 'customer', business_key, version_number, surrogate_key
FROM customer_keys_phase1;

-- Phase 2: versions and customers that were not in that first set.
-- C101 version 2 and C050 receive the next keys. Nobody already stored moves.
CREATE OR REPLACE TEMP TABLE customer_keys_phase2 AS
SELECT
    plan.customer_id AS business_key,
    plan.version_number,
    base.max_key + ROW_NUMBER() OVER (
        ORDER BY plan.effective_from, plan.customer_id, plan.version_number
    ) AS surrogate_key
FROM customer_version_plan AS plan
CROSS JOIN (
    SELECT COALESCE(MAX(surrogate_key), 0) AS max_key
    FROM surrogate_registry
    WHERE entity_name = 'customer'
) AS base
WHERE NOT EXISTS (
    SELECT 1
    FROM surrogate_registry AS registry
    WHERE registry.entity_name = 'customer'
      AND registry.business_key = plan.customer_id
      AND registry.version_number = plan.version_number
);

INSERT INTO surrogate_registry
SELECT 'customer', business_key, version_number, surrogate_key
FROM customer_keys_phase2;

CREATE OR REPLACE TABLE dim_customer AS
SELECT
    registry.surrogate_key AS customer_key,
    plan.customer_id,
    plan.customer_name,
    plan.country_code,
    plan.customer_segment,
    plan.effective_from,
    plan.effective_to,
    plan.is_current,
    plan.version_number,
    plan.change_reason
FROM customer_version_plan AS plan
JOIN surrogate_registry AS registry
  ON registry.entity_name = 'customer'
 AND registry.business_key = plan.customer_id
 AND registry.version_number = plan.version_number
UNION ALL
SELECT
    -1,
    'UNKNOWN',
    'Unknown customer',
    'ZZ',
    'Unknown',
    DATE '1900-01-01',
    NULL,
    TRUE,
    0,
    'unknown_member';

-- The original eight still match a row number. The comparison is only honest
-- while the member set is the set those numbers were computed on.
CREATE OR REPLACE VIEW cmp_original_customer_keys AS
SELECT
    customers.customer_id,
    ROW_NUMBER() OVER (ORDER BY customers.customer_id) AS row_number_key,
    registry.surrogate_key AS durable_key
FROM silver_customers AS customers
JOIN surrogate_registry AS registry
  ON registry.entity_name = 'customer'
 AND registry.business_key = customers.customer_id
 AND registry.version_number = 1;

-- C050 sorts before C100. A rebuild with ROW_NUMBER() renumbers the warehouse.
CREATE OR REPLACE VIEW cmp_fragile_customer_keys AS
SELECT
    ids.customer_id,
    ROW_NUMBER() OVER (ORDER BY ids.customer_id) AS row_number_if_rebuilt,
    registry.surrogate_key AS durable_key
FROM (
    SELECT customer_id FROM silver_customers
    UNION ALL
    SELECT customer_id FROM new_customers
) AS ids
JOIN surrogate_registry AS registry
  ON registry.entity_name = 'customer'
 AND registry.business_key = ids.customer_id
 AND registry.version_number = 1;
