-- One read. Rows strictly after the watermark.

SELECT
    email_address,
    full_name,
    country,
    region,
    customer_segment,
    account_plan,
    account_status,
    preferred_currency,
    updated_at
FROM ops.customer_account
WHERE (updated_at, email_address) > (%s, %s)
ORDER BY updated_at, email_address
LIMIT %s;
