"""Response models for the lesson. Swagger renders these directly."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LessonRow(BaseModel):
    business_key: str
    source: str
    entity: str
    outcome: str
    detail: str
    source_updated_at: str | None = None
    payload_hash: str | None = None
    prior_hash: str | None = None
    page: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class LakeRow(BaseModel):
    table_name: str
    landing_id: str
    run_id: str
    batch_id: str
    business_key: str
    source_updated_at: str
    extracted_at: str
    payload: dict[str, Any]


class StepView(BaseModel):
    id: str
    index: int
    title: str
    layer: str
    summary: str
    rules: list[str]
    script: str | None = None
    script_sql: str | None = None
    status: Literal["succeeded"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    input_count: int
    output_count: int
    held_count: int
    hint: str
    tone: Literal["neutral", "warn", "bad"]
    logs: list[str]
    records: list[LessonRow]
    cursor_updated_at: str | None = None
    cursor_key: str = ""
    lake_table: str | None = None
    lake_rows: list[LakeRow] = Field(default_factory=list)


class LessonRun(BaseModel):
    run_id: str
    pipeline: str
    status: Literal["running", "succeeded"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int
    database: str
    host: str
    port: int
    mongo_database: str
    completed_steps: int
    step_count: int
    next_step_id: str | None = None
    steps: list[StepView]


class StageSpec(BaseModel):
    id: str
    index: int
    title: str
    layer: str
    summary: str
    rules: list[str]
    script: str | None = None
    script_sql: str | None = None


class PipelineCatalog(BaseModel):
    pipeline: str
    description: str
    database: str
    mongo_database: str
    cutoff: str
    watch_keys: list[str]
    stages: list[StageSpec]


class RunSummary(BaseModel):
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    steps_completed: int
    step_count: int


class SourceFeed(BaseModel):
    id: str
    name: str
    technology: str
    location: str
    columns: list[str]
    rows: list[dict[str, Any]]


class ReportingIndex(BaseModel):
    schema_name: str
    index_name: str
    definition: str


class StgCustomerRow(BaseModel):
    batch_id: str
    customer_email_pk_id: str
    country: str
    region: str
    customer_segment: str
    account_plan: str
    account_status: str
    preferred_currency: str
    source_updated_at: str


class StageField(BaseModel):
    name: str
    value: str


class StageLine(BaseModel):
    key: str
    detail: str
    batch_id: str
    columns: list[StageField] = Field(default_factory=list)


class ModelTable(BaseModel):
    table_name: str
    kind: Literal["dimension", "fact"]
    rows: list[StageLine]


class StgFeedView(BaseModel):
    feed_id: str
    stg_table: str
    lake_table: str
    rows: list[StageLine]


class StageBoard(BaseModel):
    feeds: list[StgFeedView]
    inserted_keys: list[str] = Field(default_factory=list)
    reporting_rows: list[StageLine]
    indexes: list[ReportingIndex]
    model: list[ModelTable] = Field(default_factory=list)
    model_indexes: list[ReportingIndex] = Field(default_factory=list)
    unresolved_orders: list[str] = Field(default_factory=list)
    skipped_products: list[str] = Field(default_factory=list)


class CustomerStage(BaseModel):
    stg_table: str
    inserted_stg: list[StgCustomerRow]
    stg_rows: list[StgCustomerRow]
    reporting_table: str
    inserted_reporting: list[StgCustomerRow]
    reporting_rows: list[StgCustomerRow]
    indexes: list[ReportingIndex]


class InsertResult(BaseModel):
    feed_id: str
    lake_table: str
    cursor_updated_at: str
    inserted: list[LakeRow]
    already_stored: list[str]
    rows: list[LakeRow]


class LakeTable(BaseModel):
    feed_id: str
    lake_table: str
    rows: list[LakeRow]


class LakeSnapshot(BaseModel):
    tables: list[LakeTable]


class ExtractRequest(BaseModel):
    updated_at: str


class SourceAdd(BaseModel):
    updated_at: str
    email_address: str | None = None
    full_name: str | None = None
    country: str | None = None
    region: str | None = None
    customer_segment: str | None = None
    account_plan: str | None = None
    account_status: str | None = None
    preferred_currency: str | None = None
    category: str | None = None
    product_id: str | None = None
    sku: str | None = None
    list_price: str | None = None
    order_id: str | None = None
    status: str | None = None
    quantity: int | None = None


class SourceView(BaseModel):
    cutoff: str
    records: list[LessonRow]
    logs: list[str]
    customers: int
    products: int
    orders: int
    feeds: list[SourceFeed] = Field(default_factory=list)


class Destination(BaseModel):
    schema_name: str
    tables: list[str]
    run_id: str | None = None
    rows: list[LessonRow] = Field(default_factory=list)


class TableCount(BaseModel):
    schema_name: str
    table_name: str
    rows: int


class DatabaseInfo(BaseModel):
    host: str
    port: int
    database: str
    user: str
    tables: list[TableCount]


class Health(BaseModel):
    status: Literal["ok", "database_unavailable"]
    pipeline: str
    database: str | None = None
    host: str | None = None
    port: int | None = None
    schemas: list[str] = Field(default_factory=list)
    mongo: Literal["ok", "unavailable"] = "unavailable"
    message: str | None = None
