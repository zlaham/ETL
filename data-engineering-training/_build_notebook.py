"""Generate the Session 2 instructor notebook. Not part of the training runtime."""

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


def md(source: str):
    return new_markdown_cell(source.strip() + "\n")


def code(source: str):
    return new_code_cell(source.strip() + "\n")


cells = []

cells.append(md("""
# Session 2 - Data Extraction and Ingestion

**60 minutes. Instructor-led. Attendees do not write code.**

The business wants daily revenue, order volume, sales trends, and customer behavior. Those questions cannot run against the production orders database. This hour builds the first piece of the data platform: a reliable copy of operational orders in the Bronze layer.

By the end of the hour the room should be able to defend one sentence:

**A successful extraction is one that can show completeness, recover from failure, and name its consistency guarantee.**
"""))

cells.append(md("""
## How to deliver this hour

Run the notebook from the top. Pause on every **Ask the room** prompt and let two people answer before you continue.

| Clock | Section | Do not drop if you are behind |
| --- | --- | --- |
| 0:00-0:05 | Why extraction is harder than an HTTP call | The architecture picture |
| 0:05-0:13 | The Orders API contract | The dirty order and the tie on `updated_at` |
| 0:13-0:23 | The naive one-call extract | The missing-row chart |
| 0:23-0:35 | Pagination and Bronze | The offset skip of order 1101 |
| 0:35-0:45 | Failure and recovery | The duplicate page after resume |
| 0:45-0:53 | Full versus incremental | The backdated update that disappears |
| 0:53-1:00 | What we actually built | The closing sentence and the Silver handoff |

> **Instructor note.** If the clock slips, shorten the contract reading and the second 429 cell. Keep the skip, the crash, and the backdated update.

> **Instructor note.** The implementation lives in `src/`. This notebook only orchestrates it. When you show code, you are opening the real module.
"""))

cells.append(code("""
%matplotlib inline

from pathlib import Path
import html
import json
import logging
import sys

import matplotlib.pyplot as plt
import pandas as pd
from IPython.display import Code, HTML, SVG, display

ROOT = Path.cwd().resolve()
for candidate in [ROOT, *ROOT.parents]:
    if (candidate / "src" / "ingestion" / "reliable_extractor.py").exists():
        ROOT = candidate
        break
else:
    raise RuntimeError("Open this notebook from the data-engineering-training project.")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from src.ingestion import ExtractionError, SimulatedProcessCrash
from src.ingestion.checkpoints import CheckpointStore, Cursor, WatermarkStore
from src.ingestion.incremental_extractor import IncrementalExtractor
from src.ingestion.naive_extractor import NaiveExtractor
from src.ingestion.paginated_extractor import PaginatedExtractor
from src.ingestion.reliable_extractor import CrashPlan, ReliableExtractor
from src.ingestion.retry_policy import RetryPolicy
from src.source.generate_orders import (
    SEED,
    example_orders,
    generate_additional_orders,
    generate_orders,
    imperfection_report,
    save_orders,
)
from src.source.mock_orders_api import OrdersApi
from src.storage.bronze_writer import BronzeWriter

PAGE_SIZE = 50
C_SOURCE = "#243e73"
C_OK = "#1e7a4d"
C_BAD = "#8f2d3a"
C_WARN = "#8a5a12"
POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_seconds=0.02,
    max_delay_seconds=0.2,
    min_interval_seconds=0.0,
)


def reset_outputs() -> None:
    for relative in ("data/bronze", "data/state"):
        folder = ROOT / relative
        folder.mkdir(parents=True, exist_ok=True)
        for child in folder.rglob("*"):
            if child.is_file() and child.name != ".gitkeep":
                child.unlink()
        for child in sorted((path for path in folder.rglob("*") if path.is_dir()), reverse=True):
            if not any(child.iterdir()):
                child.rmdir()


def show_banner(title: str, tone: str, lines: list[str]) -> None:
    palette = {
        "failed": ("#8f2d3a", "#fdecee"),
        "success": ("#1e7a4d", "#eef8f2"),
        "recovered": ("#163e6b", "#eef3f9"),
        "incomplete": ("#8a5a12", "#fbf6ec"),
    }
    ink, paper = palette[tone]
    body = "<br>".join(html.escape(line) for line in lines)
    display(HTML(
        f"<div style='border-left:6px solid {ink};background:{paper};"
        f"padding:12px 16px;margin:8px 0 14px 0'>"
        f"<div style='color:{ink};font-weight:700;font-size:17px'>{html.escape(title)}</div>"
        f"<div style='margin-top:6px;font-family:Consolas,monospace;font-size:14px'>{body}</div>"
        f"</div>"
    ))


def show_result(result, tone: str) -> None:
    lines = [f"{key}: {value}" for key, value in result.summary().items()]
    show_banner(f"{result.status.upper()}   {result.run_id}", tone, lines)
    if result.attempts:
        display(pd.DataFrame(result.attempts))


def bar_compare(rows: list[tuple[str, int, str]], title: str) -> None:
    labels = [row[0] for row in rows]
    values = [row[1] for row in rows]
    colors = [row[2] for row in rows]
    fig, ax = plt.subplots(figsize=(9.2, 3.3), layout="constrained")
    bars = ax.barh(labels, values, color=colors, height=0.62)
    ceiling = max(values) if max(values) > 0 else 1
    for bar, value in zip(bars, values):
        ax.text(
            value + ceiling * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,}",
            va="center",
            fontsize=12,
        )
    ax.set_xlim(0, ceiling * 1.2)
    ax.set_xlabel("Orders")
    ax.set_title(title, loc="left", fontsize=14, pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.invert_yaxis()
    plt.show()


def show_source(relative: str) -> None:
    display(Code(filename=str(ROOT / relative), language="python"))


def show_excerpt(relative: str, start: str, end: str) -> None:
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    start_at = next(i for i, line in enumerate(lines) if start in line)
    end_at = next(i for i, line in enumerate(lines) if i > start_at and end in line)
    snippet = "\\n".join(f"{i + 1:4d} | {lines[i]}" for i in range(start_at, end_at))
    display(Code(snippet, language="python"))


reset_outputs()
orders = generate_orders()
api = OrdersApi.from_orders(orders)
client = api.client()
save_orders(orders, ROOT / "data" / "source" / "orders_seed.json")
print(f"Ready. {len(orders)} orders. seed={SEED}.")
print("Source endpoint:", api.contract()["endpoint"])
"""))

cells.append(md("""
# 1 - Why Is Extracting Data Harder Than Calling an API?

**0:00-0:05**

**What we're solving.** The commerce application stores orders in its own transactional database and exposes them through a REST API. Finance and product want daily revenue, order volume, trends, and customer purchasing behavior, including how an order changed over time. They also want the production database left alone.

**The engineering problem.** Copying orders into a data platform sounds like a script. The requirement underneath that script is stricter: synchronize operational orders into Bronze without losing records.

**Requirement for this hour.** Extract operational orders from the Orders API and persist them, raw, into Bronze.
"""))

cells.append(code("""
display(SVG(filename=str(ROOT / "docs" / "extraction_architecture.svg")))
"""))

cells.append(md("""
### Walk the diagram once, top to bottom

1. **Operational application.** Owns the orders database. Analytical load does not belong here. A read replica is still an operational store: it couples the platform to the application schema and still gives you no Bronze history.
2. **Orders REST API.** The extraction boundary. The contract is `GET /api/orders`, with pages, a snapshot id, and an incremental cursor.
3. **Data extraction service.** The code in this session. It pages, retries, and checkpoints. It runs. It is not a data layer.
4. **Pagination.** A full load walks a frozen `order_id` snapshot. An incremental load walks `(updated_at, order_id)`. Offset pages on a live, mutating list can skip rows.
5. **Retries.** HTTP 500 backs off. HTTP 429 honors `Retry-After`. Extra concurrency makes a rate limit worse. Attempts are capped.
6. **Checkpoints.** The cursor advances only after Bronze has been flushed. A dead process resumes from that cursor. A replay can append a duplicate page. That is at-least-once delivery.
7. **Bronze storage.** A logical layer of raw JSONL. Each line carries `source_system`, `ingested_at`, `run_id`, `source_record_id`, and the untouched `payload`.
8. **Silver and Gold.** Dashed on purpose. Validation and business models are later sessions.
9. **Source API contract.** What the API promises, including the promises it refuses to make.
10. **Failure handling.** Transient HTTP failures, process death, and the duplicate window.
11. **Metadata and execution logs.** Logs explain a run. The checkpoint and the watermark are state. The Bronze file is the data. Those three artifacts answer different questions.

The copper box is storage. The navy box is the service. Bronze is the place data lands. It is not the program that fetched it.

> **Ask the room.** Would a scheduled Python script calling `requests.get()` be sufficient?

> **Instructor note.** Do not answer yet. Write their answers on the board. You will come back to them in the last five minutes. Expect "add a cron" and "check the status code." Both miss completeness and recovery.

> **If someone asks about CDC now.** Say "hold that until the incremental section." Change data capture is a real alternative. It is not the first design.
"""))

cells.append(md("""
# 2 - Understanding the Source

**0:05-0:13**

**What we're solving.** Before writing a pipeline, name the source and the contract it will actually keep.

**The engineering problem.** Extraction design is downstream of the source. An API that can page a snapshot supports a different pipeline than an API that only returns "the latest 50 orders."
"""))

cells.append(code("""
response = client.get("/api/orders", params={"page": 1, "page_size": 2})
body = response.json()
print("HTTP", response.status_code, " request-id", response.headers.get("x-request-id"))
preview = {
    "page": body["page"],
    "page_size": body["page_size"],
    "total": body["total"],
    "has_more": body["has_more"],
    "snapshot_id": body["snapshot_id"],
    "ordering": body["ordering"],
    "consistent_snapshot": body["consistent_snapshot"],
    "data": body["data"],
}
print(json.dumps(preview, indent=2))
display(pd.DataFrame(api.recent_requests()))
"""))

cells.append(code("""
report = imperfection_report(orders)
samples = example_orders(orders)
print("Source population")
display(pd.Series(report).to_frame("count"))
print("Order 1001, as the API returned it")
print(json.dumps(samples["messy"], indent=2))
print("A clean neighbor, order", samples["clean"]["order_id"])
print(json.dumps(samples["clean"], indent=2))
tied = sorted(order["order_id"] for order in orders if order["updated_at"] == "2026-09-15T12:00:00Z")
print("Orders sharing one updated_at:", tied)
"""))

cells.append(code("""
empty = client.get(
    "/api/orders",
    params={"updated_after": "2099-01-01T00:00:00Z", "after_id": 0, "limit": 50},
)
print("Empty incremental query:", empty.status_code)
print(json.dumps(empty.json(), indent=2))
"""))

cells.append(md("""
> **Ask the room.** What guarantees does this API actually give us?

> **Instructor note.** Let them answer from the response they just saw. Then run the next cell. Spend the remaining time on `does_not_guarantee`. The unsafe proof of offset pagination is in section 4. Do not spoil the missing order id yet.

Point at order 1001 while you talk:

- `customer_id` and `product_id` and `currency` are null.
- `status` is `COMPLETED`, while other rows use `completed`.
- `total_amount` is 70.38 and `unit_price` is 69.27. One times the other is not the total.
- `updated_at` is earlier than `created_at`.
- `channel` is an extra key the happy-path schema never mentioned.

Two orders share `2026-09-15T12:00:00Z`. A cursor made of the timestamp alone cannot tell them apart. The tie-breaker is `order_id`. We keep the two values separate. Gluing them into one string would sort `order_id` 999 after 1000.

An empty match is HTTP 200 with `data: []`. "No rows" is a successful response.
"""))

cells.append(code("""
contract = api.contract()
print(json.dumps(contract, indent=2))
"""))

cells.append(md("""
**What you should observe.** The response already told us `total` is 500 and `has_more` is true. The population contains nulls, inconsistent statuses and currencies, amount mismatches, a backwards timestamp, and one tied `updated_at`. The contract gives us a stable `order_id`, a snapshot for full pages, and a strict composite cursor. It does not give us deletes, trustworthy backdated corrections, intermediate states, or exactly-once delivery.

**Production lesson.** Write the source contract down before choosing pagination, retries, or a watermark. A pipeline cannot invent a guarantee the source refused to make. Money here is a JSON number. Floating-point money is itself a source defect. Bronze keeps it. Silver will have to decide whether to carry it as a scaled integer.

> **Instructor note.** "Why not SELECT from the replica?" A replica can be the source. The problems in the rest of this hour still exist: pages or keysets, partial failure, restart, and a cursor. The API makes that contract visible.
"""))

cells.append(md("""
# 3 - The Naive Approach

**0:13-0:23**

**What we're solving.** Put the one-call script on the table and measure it.

**The engineering problem.** HTTP success and data completeness are different measurements.
"""))

cells.append(code("""
show_source("src/ingestion/naive_extractor.py")
"""))

cells.append(code("""
naive = NaiveExtractor(client, page_size=PAGE_SIZE).extract()
show_banner(
    "HTTP SUCCEEDED",
    "incomplete",
    [
        f"status_code: {naive.status_code}",
        f"page: {naive.page}   page_size: {naive.page_size}",
        f"records in the body: {len(naive.records)}",
        f"total reported by the API: {naive.total}",
        f"has_more: {naive.has_more}",
        f"missing: {naive.missing}",
    ],
)
bar_compare(
    [
        ("Available at source", naive.total, C_SOURCE),
        ("Retrieved", len(naive.records), C_WARN),
        ("Missing", naive.missing, C_BAD),
    ],
    "One successful request",
)
"""))

cells.append(md("""
> **Ask the room.** The request succeeded. Does that mean the extraction succeeded?

**What you should observe.** Status 200. Fifty orders in memory. The same body says `total` is 500 and `has_more` is true. Four hundred and fifty orders never left the source. The naive module reads `data` and stops. It also ignores the signals the API already provided.

**Weaknesses of this implementation.**

- It stops on page 1.
- It holds the page in a list and writes nothing to Bronze, so a crash keeps zero durable rows and also keeps no progress marker.
- It has no retry. A single 500 fails the job.
- It cannot resume, and it cannot tell a later run which orders were new.
- A green exit code would hide a 10 percent extract just as easily as this 10 percent extract. Fifty out of five hundred is obvious. Fifty thousand out of five hundred thousand is the same bug.

**Production lesson.** Completeness is `retrieved` compared with the population you intended to copy. Publish both numbers on the run. A scheduler that only alerts on exceptions will stay quiet through this failure.

> **Instructor note.** We use `httpx` so the demo can exercise real HTTP semantics against an in-process transport. The mistake is the same one line a `requests.get` script would make.
"""))

cells.append(md("""
# 4 - Pagination and Bronze Ingestion

**0:23-0:35**

**What we're solving.** Read the source to the end and land every record in Bronze, raw.

**The engineering problem.** The extractor has to respect page boundaries, keep a stable view while it pages, and write each page without holding the whole source in memory. Cleaning is a later layer.
"""))

cells.append(code("""
show_excerpt("src/ingestion/paginated_extractor.py", "def extract", "def _result")
show_excerpt("src/storage/bronze_writer.py", "def write_records", "def read_envelopes")
"""))

cells.append(md("""
> **Instructor note.** In the extractor, point at three things. There is no `all_orders` list. Each page is written before the next page is requested. `snapshot_id` from page 1 is sent on every later page. In the writer, point at the envelope and at `flush` plus `fsync`. Five hundred orders would fit in RAM. The loop is shaped for a source that will not.
"""))

cells.append(code("""
api.restore()
full_writer = BronzeWriter(ROOT / "data" / "bronze" / "section4")
full_result = PaginatedExtractor(client, full_writer, page_size=PAGE_SIZE).extract("paginated_full")
show_result(full_result, "success")
bar_compare(
    [
        ("Available at source", naive.total, C_SOURCE),
        ("Naive extract", len(naive.records), C_WARN),
        ("Paginated extract", full_result.records_written, C_OK),
    ],
    "Naive call versus a full paged extract",
)
"""))

cells.append(code("""
envelopes = full_writer.read_envelopes("paginated_full")
print(f"Bronze lines: {len(envelopes)}")
print(json.dumps(envelopes[0], indent=2))
payloads = [envelope["payload"] for envelope in envelopes]
dirt = pd.Series(imperfection_report(payloads)).to_frame("still_in_bronze")
display(dirt)
print("High watermark from this full extract:")
print(json.dumps(full_result.high_watermark, indent=2))
"""))

cells.append(md("""
**What you should observe.** Ten pages, 500 lines, one JSON object per line. Order 1001 is still dirty inside `payload`. The envelope adds `source_system`, `ingested_at`, `run_id`, and `source_record_id` without editing the order. The imperfection counts match the source. The high watermark is the maximum `(updated_at, order_id)` seen in the snapshot, which is the cursor an incremental run will need.

**Why each envelope field exists.**

- **Raw payload.** Silver can be rebuilt from Bronze. Bronze cannot be rebuilt from a cleaned table.
- **ingested_at.** When the platform accepted the row. Independent of the source clock.
- **source_system.** Which contract produced the payload, when a second source arrives later.
- **run_id.** Groups lines from one execution so a bad run can be found and replayed.
- **source_record_id.** The source identity, lifted out so operators can count without parsing every payload.

**Production lesson.** This stage has one job: durable, attributable, raw capture. Uppercasing `COMPLETED`, filling null currencies, or "fixing" the total here destroys the evidence Silver needs. Cleaning belongs to Silver.

> **Ask the room.** The first response includes `total`. Would you fan out the remaining pages concurrently?

> **Instructor note.** On a snapshot id, the pages do not depend on each other, so parallelism is possible. It spends the rate-limit budget faster, and a checkpoint becomes harder when page 7 finishes before page 3. Hear the answers. The failure section comes back to this.
"""))

cells.append(md("""
### Mutable offset pages

The full extract passed `snapshot_id` on every page after the first. Drop that token, delete one already-returned order, and the next offset shifts.

Page size here is 100 so the arithmetic is easy to say out loud. Page 1 returns orders 1001 through 1100. The demo then deletes 1050, which was on page 1. Watch what happens to 1101, which nobody deleted.
"""))

cells.append(code("""
def collect(run_id: str, writer: BronzeWriter) -> set[int]:
    return {envelope["source_record_id"] for envelope in writer.read_envelopes(run_id)}


api.restore()
api.delete_after_request(1, 1050)
unsafe_writer = BronzeWriter(ROOT / "data" / "bronze" / "section4")
unsafe = PaginatedExtractor(
    client,
    unsafe_writer,
    page_size=100,
    consistent_snapshot=False,
).extract("unsafe_offset")
unsafe_ids = collect("unsafe_offset", unsafe_writer)

api.restore()
api.delete_after_request(1, 1050)
safe_writer = BronzeWriter(ROOT / "data" / "bronze" / "section4")
safe = PaginatedExtractor(client, safe_writer, page_size=100).extract("safe_snapshot")
safe_ids = collect("safe_snapshot", safe_writer)

comparison = pd.DataFrame(
    [
        {
            "mode": "live offset",
            "bronze_rows": unsafe.records_written,
            "has_1050": 1050 in unsafe_ids,
            "has_1101": 1101 in unsafe_ids,
            "live_orders_after_run": 499,
        },
        {
            "mode": "snapshot",
            "bronze_rows": safe.records_written,
            "has_1050": 1050 in safe_ids,
            "has_1101": 1101 in safe_ids,
            "live_orders_after_run": api.order_count,
        },
    ]
)
display(comparison)

print("After the unsafe run, order 1101 was still in the source and absent from Bronze.")
print("unsafe has 1101:", 1101 in unsafe_ids, "  snapshot has 1101:", 1101 in safe_ids)
print("1050 was deleted after page 1. unsafe kept the copy it had already read:", 1050 in unsafe_ids)
"""))

cells.append(md("""
**What you should observe.** The live offset extract has 499 rows. It contains 1050, which is fine: that row had already been read. It does not contain 1101. Nothing deleted 1101. Deleting an earlier row shifted the offset, and page 2 started one row too late.

The snapshot extract has all 500 original ids, including 1101 and the already-deleted 1050. It is complete relative to the moment the snapshot opened. It is slightly stale relative to the live delete. A later delete still has no event. The incremental cursor will not emit one either.

**Production lesson.** Offset pagination is safe only while the ordered set is frozen. A `snapshot_id`, a keyset, or a true export is that freeze. "We paginate" is not a completeness strategy until you know what happens when a row is inserted or deleted halfway through the run.

> **Ask the room.** You have 499 rows and a successful exit. Which alert fires?
"""))

cells.append(md("""
# 5 - Things Go Wrong

**0:35-0:45**

**What we're solving.** Show three production failures on the same pipeline: a transient 500, a 429, and a process that dies mid-run.

**The engineering problem.** Retries cover a failed call. A checkpoint covers a dead process. Neither one, by itself, is exactly-once delivery.

Delays below are compressed. A production `Retry-After` is often 30 seconds. The policy shape is the same. Jitter is omitted so the classroom run stays repeatable. Add it in production to avoid a thundering herd.
"""))

cells.append(code("""
show_excerpt("src/ingestion/retry_policy.py", "class RetryPolicy", "class RetryExecutor")
show_excerpt("src/ingestion/retry_policy.py", "def _retry_delay", "def _backoff")
show_excerpt(
    "src/ingestion/reliable_extractor.py",
    "self._writer.write_records(records, run_id=run_id)",
    "logger.info(",
)
"""))

cells.append(md("""
> **Instructor note.** Read the comment in the reliable extractor out loud: the page is on disk, and the checkpoint does not know that yet. That gap is the whole of scenario C. `min_interval_seconds` on the policy is the client-side pace. It is zero here so the notebook stays fast. In production it comes from the API's published budget.
"""))

cells.append(md("""
### Scenario A - HTTP 500

The API fails on page 2, once. The first run has no retry. The second run uses the same failure with a capped backoff.
"""))

cells.append(code("""
api.restore()
failed_writer = BronzeWriter(ROOT / "data" / "bronze" / "scenario_500")
api.fail_request(500, page=2, times=1)
try:
    PaginatedExtractor(client, failed_writer, page_size=PAGE_SIZE).extract("noretry")
except ExtractionError as exc:
    show_result(exc.result, "failed")
print("Bronze lines left behind:", len(failed_writer.read_envelopes("noretry")))
"""))

cells.append(code("""
api.reset_session()
api.fail_request(500, page=2, times=1)
recovered = ReliableExtractor(
    client,
    failed_writer,
    CheckpointStore(ROOT / "data" / "state" / "scenario_500"),
    POLICY,
    page_size=PAGE_SIZE,
).extract("with_retry")
show_result(recovered, "recovered")
print("Bronze lines:", len(failed_writer.read_envelopes("with_retry")))
"""))

cells.append(md("""
**What you should observe.** Without a retry, page 1 is durable and page 2 raises HTTP 500. Fifty lines are on disk. Four hundred and fifty orders are missing. The run is red. With the retry policy, page 2 is attempted, receives 500, waits, and then receives 200. The attempt table shows both statuses. The run finishes at 500 lines.

Retries are capped at 3. A permanent 500 still fails the run and leaves the checkpoint on the last committed page, so an operator can resume after the source is healthy.

### Scenario B - HTTP 429

The first call is rate-limited and carries `Retry-After: 0.02`. One path ignores it. The other waits and continues.
"""))

cells.append(code("""
api.reset_session()
limited_writer = BronzeWriter(ROOT / "data" / "bronze" / "scenario_429")
api.fail_request(429, page=1, times=1, retry_after="0.02")
try:
    PaginatedExtractor(client, limited_writer, page_size=PAGE_SIZE).extract("noretry")
except ExtractionError as exc:
    show_result(exc.result, "failed")

api.reset_session()
api.fail_request(429, page=1, times=1, retry_after="0.02")
limited = ReliableExtractor(
    client,
    limited_writer,
    CheckpointStore(ROOT / "data" / "state" / "scenario_429"),
    POLICY,
    page_size=PAGE_SIZE,
).extract("with_retry")
show_result(limited, "recovered")
print("Recent HTTP log for the recovered run:")
display(pd.DataFrame(api.recent_requests()).head(4))
"""))

cells.append(md("""
**What you should observe.** The unretriable client stops on the first response with zero Bronze rows. The reliable client records a retry, sleeps for the server's delay, and then completes the extract. The HTTP log shows 429 followed by 200 for the same page.

**Why extra concurrency makes a 429 worse.** A 429 means the source is already refusing work. Opening more workers spends the same budget faster and lengthens the outage. The client-side response is to honor `Retry-After`, keep a minimum interval, and leave the worker count where it is. Parallel page fetches can still be the right design behind a snapshot and a shared limiter. They are a bad reaction to this status code.

> **Ask the room.** Who owns the rate-limit budget when three pipelines share this API?
"""))

cells.append(md("""
### Scenario C - the process dies halfway

Page size is 50, so page 4 is orders 1151 through 1200. The worker writes that page, flushes it, and is killed before the checkpoint advances. The checkpoint must stay on page 3.

> **Instructor note.** After the crash cell, stop. Open the checkpoint JSON and the line count before you run resume.
"""))

cells.append(code("""
api.restore()
crash_writer = BronzeWriter(ROOT / "data" / "bronze" / "scenario_crash")
crash_store = CheckpointStore(ROOT / "data" / "state" / "scenario_crash")
crash_extractor = ReliableExtractor(
    client,
    crash_writer,
    crash_store,
    POLICY,
    page_size=PAGE_SIZE,
)
try:
    crash_extractor.extract(
        "crash_run",
        crash=CrashPlan(after_write_before_checkpoint_page=4),
    )
except SimulatedProcessCrash as crashed:
    show_result(crashed.result, "incomplete")

checkpoint = crash_store.load("crash_run")
partial_ids = [row["source_record_id"] for row in crash_writer.read_envelopes("crash_run")]
show_banner(
    "DISK VERSUS CHECKPOINT",
    "incomplete",
    [
        f"bronze lines: {len(partial_ids)}",
        f"first id: {partial_ids[0]}   last id: {partial_ids[-1]}",
        f"checkpoint page: {checkpoint.last_completed_page}",
        f"checkpoint committed rows: {checkpoint.records_committed}",
        f"rows on disk that the checkpoint has not accepted: {len(partial_ids) - checkpoint.records_committed}",
        f"snapshot_id kept for resume: {checkpoint.snapshot_id}",
    ],
)
print((crash_store.path_for("crash_run")).read_text(encoding="utf-8"))
"""))

cells.append(code("""
resumed = crash_extractor.extract("crash_run", resume=True)
final_ids = [row["source_record_id"] for row in crash_writer.read_envelopes("crash_run")]
duplicated = sorted(order_id for order_id in set(final_ids) if final_ids.count(order_id) > 1)
completed = crash_store.load("crash_run")
show_result(resumed, "recovered")
show_banner(
    "RESUME COMPLETE",
    "recovered",
    [
        f"resumed from page: {resumed.resumed_from_page}",
        f"bronze lines: {len(final_ids)}",
        f"distinct orders: {len(set(final_ids))}",
        f"checkpoint committed: {completed.records_committed}",
        f"duplicated range: {duplicated[0]} through {duplicated[-1]} ({len(duplicated)} orders)",
    ],
)
bar_compare(
    [
        ("Bronze lines", len(final_ids), C_WARN),
        ("Distinct orders", len(set(final_ids)), C_OK),
        ("Checkpoint committed", completed.records_committed, C_SOURCE),
    ],
    "Recovery left a duplicate page in raw Bronze",
)
"""))

cells.append(md("""
**What you should observe.** After the crash the file holds orders 1001 through 1200 (200 lines). The checkpoint says page 3 and 150 committed rows. The extra 50 lines are page 4, durable and unacknowledged. Resume starts at page 4, using the same `snapshot_id`, and appends the rest. The file ends at 550 lines and 500 distinct orders. Orders 1151 through 1200 appear twice. The checkpoint ends at 500 because it counts committed pages, not physical lines.

If the snapshot id had expired, resume would raise HTTP 409 and refuse to open a fresh offset window. Continuing with a new snapshot after a gap is how the skip from section 4 comes back.

**At-least-once, stated plainly.** The checkpoint advances only after `fsync`. That rule prevents the cursor from claiming a page the disk does not have. It cannot close the opposite window: the page is durable, then the process dies, then resume writes it again. Two files on one machine are not one atomic commit. Exactly-once needs an idempotent write (for example, replacing `page_0004.jsonl`) or a transactional store that commits the data and the cursor together. This Bronze file is append-only JSONL, which is how many lakes are built, and it makes the duplicate visible.

A duplicate raw page is acceptable when Silver dedupes on a deterministic key such as `(source_record_id, payload hash)` or the latest `(order_id, updated_at)` inside a run. It is not acceptable to pretend the checkpoint removed that obligation. Checkpointing does not create exactly-once ingestion.

> **Ask the room.** Finance reports revenue from Gold. Where must the duplicate page die, and what key makes that dedupe deterministic?

> **Instructor note.** A page-number checkpoint is valid here because resume reuses the snapshot and the source set does not move. If the snapshot is gone, or the source is live, a page number is a brittle cursor. The incremental path in the next section uses a keyset for that reason.
"""))

cells.append(md("""
# 6 - Full versus Incremental Extraction

**0:45-0:53**

**What we're solving.** Stop copying all 500 orders on every refresh. Pull what changed.

**The engineering problem.** "What changed" requires a cursor the source actually maintains. Ours is `(updated_at, order_id)`, stored in a watermark file that outlives a single run. The watermark moves only after the sync finishes.
"""))

cells.append(code("""
from datetime import datetime, timezone

CHANGE_AT = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
UPDATED_IDS = [1001, 1010, 1100, 1200, 1300]

api.restore()
section6_writer = BronzeWriter(ROOT / "data" / "bronze" / "section6")
watermarks = WatermarkStore(ROOT / "data" / "state" / "section6")
baseline = PaginatedExtractor(client, section6_writer, page_size=PAGE_SIZE).extract("baseline")
watermarks.save(Cursor(**baseline.high_watermark), run_id=baseline.run_id)
print("Watermark saved after the full extract:")
print((watermarks.path).read_text(encoding="utf-8"))

for order_id in UPDATED_IDS:
    api.update_order(order_id, status="refunded", updated_at="2026-10-15T09:00:00Z")
new_orders = generate_additional_orders(start_id=1501, count=8, at=CHANGE_AT)
api.add_orders(new_orders)
print(f"Source now holds {api.order_count} orders. Updated {len(UPDATED_IDS)}. Added {len(new_orders)}.")
print("New order 1501 currency:", new_orders[0]["currency"])
"""))

cells.append(code("""
incremental = IncrementalExtractor(
    client,
    section6_writer,
    watermarks,
    POLICY,
    page_size=PAGE_SIZE,
)
delta = incremental.extract("delta")
show_result(delta, "success")
rows = []
for envelope in section6_writer.read_envelopes("delta"):
    payload = envelope["payload"]
    rows.append(
        {
            "order_id": payload["order_id"],
            "change": "updated" if payload["order_id"] in UPDATED_IDS else "new",
            "status": payload["status"],
            "currency": payload["currency"],
            "updated_at": payload["updated_at"],
        }
    )
display(pd.DataFrame(rows))
again = incremental.extract("delta_again")
show_banner(
    "SECOND SYNC",
    "success",
    [
        f"full extract rows: {baseline.records_written}",
        f"incremental rows: {delta.records_written}",
        f"immediate rerun rows: {again.records_written}",
        f"source orders now: {api.order_count}",
    ],
)
bar_compare(
    [
        ("Initial full extract", baseline.records_written, C_SOURCE),
        ("Incremental sync", delta.records_written, C_OK),
        ("Immediate rerun", again.records_written, C_WARN),
    ],
    "Rows moved across the network",
)
"""))

cells.append(md("""
**What you should observe.** The baseline copied 500 orders. Five existing orders were marked `refunded`, and eight new orders were inserted. The sync returned 13 rows: the five updates and the eight inserts. Order 1001 kept its null currency. Order 1501 arrived as `usd`. Incremental extraction does not clean. A second sync, with no further source changes, returned zero rows. The watermark file moved forward on the first sync and stayed put on the empty one.

Updated orders now exist twice in Bronze: the original version from the full extract, and the refunded version from the sync. That is history, and it is also another dedupe problem for Silver. New orders exist only in the incremental file.

The first response's `total_matching` is a convenience of this mock. Do not use a live count as your completeness proof. The source can change between page one and page two. The cursor is the contract.
"""))

cells.append(code("""
api.update_order(1400, status="cancelled", updated_at="2026-08-01T00:00:00Z")
live = api.get_order(1400)
missed = incremental.extract("backdated")
show_banner(
    "SOURCE CHANGED. THE SYNC DID NOT SEE IT.",
    "failed",
    [
        f"order 1400 status in the API: {live['status']}",
        f"order 1400 updated_at: {live['updated_at']}",
        f"incremental rows returned: {missed.records_written}",
    ],
)

api.update_order(1400, status="cancelled", updated_at="2026-10-15T09:30:00Z")
caught = incremental.extract("forward_fix")
show_banner(
    "SAME CHANGE WITH A FORWARD TIMESTAMP",
    "recovered",
    [
        f"order 1400 updated_at now: {api.get_order(1400)['updated_at']}",
        f"incremental rows returned: {caught.records_written}",
        f"order id: {section6_writer.read_envelopes('forward_fix')[0]['source_record_id']}",
    ],
)
"""))

cells.append(md("""
**What you should observe.** The source really did change order 1400 to `cancelled`. Because `updated_at` moved backward, behind the watermark, the sync returned nothing. The same business change, stamped after the watermark, came through as one row. The pipeline followed the cursor. The cursor did not follow the business event.

**Limits of this cursor.**

- **Watermark.** The high `(updated_at, order_id)` saved only after a successful sync. A failed sync leaves the old cursor, so the next run rereads the same window and can append duplicates. Same at-least-once rule as the page checkpoint.
- **Change tracking.** We see the latest row after the cursor. Intermediate statuses between two polls are gone.
- **Late and backdated updates.** A correction that rewrites history behind the watermark is invisible. Teams sometimes reread an overlap, such as the last 10 minutes, and accept more duplicates. Overlap reduces the window. It does not give you a true history.
- **Source timestamps.** Equal timestamps need `order_id`. A null `updated_at` cannot be ordered. Clocks that jump backward hide work.
- **Deletes.** A removed order leaves no row to extract.
- **Full-load race.** If rows change during the initial snapshot, a watermark taken from the snapshot's maximum cursor can miss a change whose new timestamp is still below that maximum. Run the mutations after the baseline, or overlap the first incremental cursor. This demo does the first.
- **CDC.** A log reader can emit deletes and the in-between versions. It needs log access and its own operational design. Use it when those events are requirements. Keep the API watermark when the source gives you an API and a moving timestamp and the consumers can accept the limits above.

**Production lesson.** Incremental extraction cuts repeated transfer. Thirteen rows moved instead of 500, and the idle rerun moved zero. The price is a written list of the changes you cannot see.

> **Ask the room.** Finance restates last month's order with an `updated_at` in August. Who notices, and when?

> **Instructor note.** Show the module docstring in `incremental_extractor.py` if you want the limits in the code as well as on this slide. Do not build a CDC connector in the room.
"""))

cells.append(md("""
# 7 - What Have We Actually Built?

**0:53-1:00**

**What we're solving.** Name the boundary of this hour so Silver starts from a true description of Bronze.

**The engineering problem.** Extraction, ingestion, transformation, modeling, and orchestration are different jobs. Treating them as synonyms is how cleaning leaks into the extractor and how a scheduler gets mistaken for a consistency guarantee.
"""))

cells.append(code("""
display(SVG(filename=str(ROOT / "docs" / "extraction_architecture.svg")))
inventory = []
for path in sorted((ROOT / "data").rglob("*")):
    if path.suffix not in {".jsonl", ".json"} or "_preview" in str(path):
        continue
    if path.suffix == ".jsonl":
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        kind = f"{count} bronze lines"
    else:
        kind = "state"
    inventory.append({"artifact": str(path.relative_to(ROOT)), "contents": kind})
display(pd.DataFrame(inventory))
"""))

cells.append(md("""
### Where the modules sit

| Concern | Module | In this session |
| --- | --- | --- |
| Operational contract, pages, failures | `src/source/mock_orders_api.py` | Source |
| Deterministic dirty orders | `src/source/generate_orders.py` | Source |
| One HTTP call | `src/ingestion/naive_extractor.py` | The insufficient script |
| Full read, page by page | `src/ingestion/paginated_extractor.py` | Extraction |
| Backoff and Retry-After | `src/ingestion/retry_policy.py` | Extraction |
| Resume cursor | `src/ingestion/checkpoints.py`, `reliable_extractor.py` | Extraction |
| Changes after a watermark | `src/ingestion/incremental_extractor.py` | Extraction |
| Raw JSONL envelopes | `src/storage/bronze_writer.py` | Ingestion into Bronze |
| Validation, dedupe, conformed types | not built | Silver, next session |
| Revenue, volume, customer behavior | not built | Gold |
| A scheduler and alerting | not built | Orchestration |

The flow we can defend today is:

**Source API, then extraction service, then Bronze.**

Silver and Gold are drawn so the room can see where this stops. They are not implemented.

### These words are not interchangeable

- **Extraction.** Reading the source under its real contract: pages or a keyset, retries, cursors, and a definition of "done."
- **Ingestion.** Landing those records in platform storage with enough metadata to audit and replay them.
- **Transformation.** Changing values. That work starts in Silver. Doing it here deletes the raw record.
- **Data modeling.** The shape Gold exposes to a business question, such as daily revenue by customer. We have not modeled anything.
- **Orchestration.** When a run starts, what it depends on, and who is paged when it fails. This notebook is the orchestrator for the classroom. It is not a scheduler.

### The answer to the opening question

A scheduled `requests.get()` is sufficient when one page is the whole population, the call never fails, the process never dies, and nobody asks for changes later. That is not this orders API. The script we measured retrieved 50 of 500 rows and called that success.

### The lesson

**A successful extraction pipeline is not one that merely runs. It is one that delivers source data with measurable completeness, recoverability, and known consistency guarantees.**

Today those guarantees are concrete:

- A snapshot page-through is complete for the snapshot, and stale for later deletes.
- A live offset page-through can skip a row that still exists.
- HTTP 429 and 500 are retried, with a cap.
- A crash resumes from the last checkpoint that does not outrun Bronze.
- Raw Bronze is at-least-once. Duplicates are expected. Exactly-once is Silver's dedupe, or a different write scheme.
- The incremental cursor sees forward changes. It misses deletes, backdated corrections, and states between polls.

> **Ask the room.** Which of those failure modes would silently corrupt daily revenue if Silver and Gold trusted every Bronze line as a new sale?

> **Ask the room.** What would you require from the Orders team before you agreed to run this every five minutes?

We now have raw orders in Bronze. But what if some orders are duplicated, amounts are invalid, statuses are inconsistent, or customer IDs are missing? That's what we'll tackle when we build the Silver layer.
"""))


notebook = new_notebook(
    cells=cells,
    metadata={
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "pygments_lexer": "ipython3",
        },
    },
)
destination = Path("notebooks") / "02_data_extraction_and_ingestion.ipynb"
destination.parent.mkdir(parents=True, exist_ok=True)
nbformat.write(notebook, destination)
print(f"wrote {destination} with {len(cells)} cells")
