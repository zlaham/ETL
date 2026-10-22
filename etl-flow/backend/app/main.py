"""HTTP API for the short ETL lesson. Interactive docs live at /docs."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.catalog import fetch_catalog_page, parse_iso
from app.db import DatabaseUnavailable, database_status, prepare_database
from app.lesson import (
    DESCRIPTION,
    PIPELINE,
    LessonFinished,
    advance,
    catalog_view,
    customer_stage,
    database_info,
    destination,
    ensure_seed,
    get_run,
    add_source_row,
    insert_after,
    latest_run,
    lake_view,
    live_sources,
    reset_lesson,
    SourceRejected,
    stage_board,
    stage_feed,
    publish_model,
    summaries,
)
from app.lesson_data import CUTOFF, PAGE_LIMIT
from app.mongo_src import ping
from app.schemas import (
    DatabaseInfo,
    CustomerStage,
    Destination,
    ExtractRequest,
    Health,
    SourceAdd,
    InsertResult,
    LakeSnapshot,
    LessonRun,
    PipelineCatalog,
    RunSummary,
    SourceView,
    StageBoard,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        prepare_database()
        ensure_seed()
    except DatabaseUnavailable:
        pass
    yield


app = FastAPI(title="ETL lesson", version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")


def _down(exc: DatabaseUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    try:
        status = database_status()
    except DatabaseUnavailable as exc:
        return Health(status="database_unavailable", pipeline=PIPELINE, message=str(exc))
    mongo_error = ping()
    return Health(
        status="ok",
        pipeline=PIPELINE,
        mongo="unavailable" if mongo_error else "ok",
        message=mongo_error,
        **status,
    )


@router.get("/database", response_model=DatabaseInfo, tags=["database"])
def read_database() -> DatabaseInfo:
    try:
        return DatabaseInfo.model_validate(database_info())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/sources", response_model=SourceView, tags=["source"])
async def read_sources() -> SourceView:
    try:
        return SourceView.model_validate(await live_sources())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/sources/{feed_id}", response_model=SourceView, tags=["source"])
async def write_source(feed_id: str, body: SourceAdd) -> SourceView:
    """Add one source row. It stays in the source until Insert loads it."""
    try:
        add_source_row(feed_id, body.model_dump())
        return SourceView.model_validate(await live_sources())
    except SourceRejected as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/sources/catalog", tags=["source"])
def read_catalog(
    cursor_updated_at: str | None = None,
    cursor_key: str = "",
    limit: int = Query(default=PAGE_LIMIT, ge=1, le=PAGE_LIMIT),
) -> dict:
    """Omit cursor_updated_at to read the whole catalog. Pass the watermark to read changes."""
    try:
        entire = cursor_updated_at is None
        cursor = CUTOFF if entire else parse_iso(cursor_updated_at)
        records = fetch_catalog_page(entire, cursor, cursor_key, limit)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": "catalog_api", "records": records}


@router.get("/lake", response_model=LakeSnapshot, tags=["lake"])
def read_lake() -> LakeSnapshot:
    try:
        return LakeSnapshot.model_validate(lake_view())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/extract/{feed_id}", response_model=InsertResult, tags=["lake"])
async def extract_feed(feed_id: str, body: ExtractRequest) -> InsertResult:
    """Insert rows newer than body.updated_at. Stored rows are not updated."""
    if feed_id not in ("accounts", "catalog", "orders"):
        raise HTTPException(status_code=404, detail="Unknown source")
    try:
        parse_iso(body.updated_at)
        return InsertResult.model_validate(await insert_after(feed_id, body.updated_at))
    except DatabaseUnavailable as exc:
        status = 400 if str(exc).startswith("Use a UTC") else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/stage/customer", response_model=CustomerStage, tags=["stage"])
def read_customer_stage() -> CustomerStage:
    try:
        return CustomerStage.model_validate(customer_stage(write=False))
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/stage/customer", response_model=CustomerStage, tags=["stage"])
def write_customer_stage() -> CustomerStage:
    """Insert raw accounts into stg.stg_customer and index them in reportingdw."""
    try:
        return CustomerStage.model_validate(customer_stage(write=True))
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/stage", response_model=StageBoard, tags=["stage"])
def read_stage() -> StageBoard:
    try:
        return StageBoard.model_validate(stage_board())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/stage/{feed_id}", response_model=StageBoard, tags=["stage"])
def write_stage(feed_id: str) -> StageBoard:
    """Copy one source landing table into its stg_ table. Keys come out of the jsonb payload. No join."""
    if feed_id not in ("accounts", "catalog", "orders"):
        raise HTTPException(status_code=404, detail="Unknown source")
    try:
        return StageBoard.model_validate(stage_feed(feed_id))
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/model", response_model=StageBoard, tags=["stage"])
def write_model() -> StageBoard:
    """Insert dim_ from each stg_ table, then fct_order. A stored key is left as it is."""
    try:
        return StageBoard.model_validate(publish_model())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/pipeline", response_model=PipelineCatalog, tags=["pipeline"])
def read_pipeline() -> PipelineCatalog:
    return PipelineCatalog.model_validate(catalog_view())


@router.post("/pipeline/steps", response_model=LessonRun, tags=["pipeline"])
async def next_step() -> LessonRun:
    """Run the next lesson step and stop."""
    try:
        return LessonRun.model_validate(await advance())
    except LessonFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.post("/pipeline/reset", response_model=SourceView, tags=["pipeline"])
async def reset() -> SourceView:
    """Put the sources and the watermark back to the start of the lesson."""
    try:
        reset_lesson()
        return SourceView.model_validate(await live_sources())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/pipeline/runs", response_model=list[RunSummary], tags=["pipeline"])
def read_runs() -> list[RunSummary]:
    try:
        return [RunSummary.model_validate(row) for row in summaries()]
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


@router.get("/pipeline/runs/latest", response_model=LessonRun, tags=["pipeline"])
def read_latest() -> LessonRun:
    try:
        run = latest_run()
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="No lesson yet")
    return LessonRun.model_validate(run)


@router.get("/pipeline/runs/{run_id}", response_model=LessonRun, tags=["pipeline"])
def read_run(run_id: str) -> LessonRun:
    try:
        run = get_run(run_id)
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc
    if run is None:
        raise HTTPException(status_code=404, detail=f"No lesson named {run_id}")
    return LessonRun.model_validate(run)


@router.get("/destination", response_model=Destination, tags=["destination"])
def read_destination() -> Destination:
    try:
        return Destination.model_validate(destination())
    except DatabaseUnavailable as exc:
        raise _down(exc) from exc


app.include_router(router)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": "ETL lesson", "docs": "/docs", "ui": "http://127.0.0.1:5173"}
