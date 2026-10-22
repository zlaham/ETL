-- Short lesson. Raw tables keep the document. stg_ keeps the typed change.

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS lesson;

CREATE TABLE IF NOT EXISTS ops.customer_account (
    email_address text PRIMARY KEY,
    full_name text NOT NULL,
    country text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL,
    account_plan text NOT NULL,
    account_status text NOT NULL,
    preferred_currency text NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.catalog_product (
    product_id text PRIMARY KEY,
    sku text NOT NULL,
    category text NOT NULL,
    list_price numeric(12, 2) NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion.watermark (
    source_system text NOT NULL,
    entity_name text NOT NULL,
    last_updated_at timestamptz NOT NULL,
    last_business_key text NOT NULL,
    batch_id text NOT NULL,
    PRIMARY KEY (source_system, entity_name)
);

CREATE TABLE IF NOT EXISTS ingestion.extract_request (
    batch_id text NOT NULL,
    page_number integer NOT NULL,
    source_system text NOT NULL,
    method text NOT NULL,
    url text NOT NULL,
    status_code integer NOT NULL,
    row_count integer NOT NULL,
    PRIMARY KEY (batch_id, page_number)
);

CREATE TABLE IF NOT EXISTS ingestion.staged_batch (
    batch_id text PRIMARY KEY,
    stage_step text NOT NULL,
    staged_at timestamptz NOT NULL
);

CREATE SCHEMA IF NOT EXISTS accounts;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS orders;

CREATE TABLE IF NOT EXISTS accounts.raw_customer (
    landing_id text PRIMARY KEY,
    run_id text NOT NULL,
    batch_id text NOT NULL,
    business_key text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    extracted_at timestamptz NOT NULL,
    UNIQUE (batch_id, business_key)
);

CREATE TABLE IF NOT EXISTS catalog.raw_catalog (
    landing_id text PRIMARY KEY,
    run_id text NOT NULL,
    batch_id text NOT NULL,
    business_key text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    extracted_at timestamptz NOT NULL,
    UNIQUE (batch_id, business_key)
);

CREATE TABLE IF NOT EXISTS orders.raw_order (
    landing_id text PRIMARY KEY,
    run_id text NOT NULL,
    batch_id text NOT NULL,
    business_key text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    extracted_at timestamptz NOT NULL,
    UNIQUE (batch_id, business_key)
);

CREATE TABLE IF NOT EXISTS stg.stg_customer (
    batch_id text NOT NULL,
    landing_id text NOT NULL REFERENCES accounts.raw_customer (landing_id),
    customer_email_pk_id text NOT NULL,
    country text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL,
    account_plan text NOT NULL,
    account_status text NOT NULL,
    preferred_currency text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    PRIMARY KEY (batch_id, customer_email_pk_id)
);

CREATE TABLE IF NOT EXISTS stg.stg_catalog (
    batch_id text NOT NULL,
    product_id text NOT NULL,
    sku text NOT NULL,
    category text NOT NULL,
    list_price numeric(12, 2) NOT NULL,
    source_updated_at timestamptz NOT NULL,
    PRIMARY KEY (batch_id, product_id),
    FOREIGN KEY (batch_id, product_id)
        REFERENCES catalog.raw_catalog (batch_id, business_key)
);

CREATE TABLE IF NOT EXISTS stg.stg_order (
    batch_id text NOT NULL,
    order_id text NOT NULL,
    customer_email_pk_id text NOT NULL,
    sku text NOT NULL,
    status text NOT NULL,
    quantity integer NOT NULL,
    source_updated_at timestamptz NOT NULL,
    PRIMARY KEY (batch_id, order_id),
    FOREIGN KEY (batch_id, order_id)
        REFERENCES orders.raw_order (batch_id, business_key)
);

CREATE SCHEMA IF NOT EXISTS reportingdw;

CREATE TABLE IF NOT EXISTS reportingdw.stg_customer (
    customer_email_pk_id text PRIMARY KEY,
    country text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL,
    account_plan text NOT NULL,
    account_status text NOT NULL,
    preferred_currency text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    batch_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS reportingdw.dim_customer (
    customer_key text PRIMARY KEY,
    customer_email_pk_id text NOT NULL UNIQUE,
    country text NOT NULL,
    region text NOT NULL,
    customer_segment text NOT NULL,
    account_plan text NOT NULL,
    account_status text NOT NULL,
    preferred_currency text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    batch_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS reportingdw.dim_product (
    product_key text PRIMARY KEY,
    product_id text NOT NULL UNIQUE,
    sku text NOT NULL UNIQUE,
    category text NOT NULL,
    list_price numeric(12, 2) NOT NULL,
    source_updated_at timestamptz NOT NULL,
    batch_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS reportingdw.dim_date (
    date_key text PRIMARY KEY,
    calendar_date date NOT NULL UNIQUE,
    year_number integer NOT NULL,
    month_number integer NOT NULL,
    day_number integer NOT NULL
);

CREATE TABLE IF NOT EXISTS reportingdw.fct_order (
    order_id text PRIMARY KEY,
    customer_key text NOT NULL REFERENCES reportingdw.dim_customer (customer_key),
    product_key text NOT NULL REFERENCES reportingdw.dim_product (product_key),
    order_date_key text NOT NULL REFERENCES reportingdw.dim_date (date_key),
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    extended_amount numeric(12, 2) NOT NULL,
    status text NOT NULL,
    batch_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson.run (
    run_id text PRIMARY KEY,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    batch_seq integer NOT NULL DEFAULT 0,
    CONSTRAINT lesson_run_status_ck CHECK (status IN ('running', 'succeeded'))
);

CREATE TABLE IF NOT EXISTS lesson.step (
    run_id text NOT NULL REFERENCES lesson.run (run_id),
    step_index integer NOT NULL,
    step_id text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    batch_id text,
    source_system text,
    input_count integer NOT NULL,
    output_count integer NOT NULL,
    held_count integer NOT NULL,
    detail jsonb NOT NULL,
    PRIMARY KEY (run_id, step_index),
    UNIQUE (run_id, step_id),
    CONSTRAINT lesson_step_status_ck CHECK (status = 'succeeded')
);
