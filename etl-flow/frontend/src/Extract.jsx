import { useEffect, useRef, useState } from "react";
import { addSourceRow, insertFeed, publishModel, stageFeed } from "./api";

const STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

const LANDING = {
  accounts: "accounts.raw_customer",
  catalog: "catalog.raw_catalog",
  orders: "orders.raw_order",
};

const STG = {
  accounts: "stg.stg_customer",
  catalog: "stg.stg_catalog",
  orders: "stg.stg_order",
};

const EXTRACTED = {
  accounts: [
    ["customer_email_pk_id", "md5(lower(trim(payload->>'email_address')))"],
    ["customer_segment", "payload->>'customer_segment'"],
    ["account_plan", "payload->>'account_plan'"],
    ["account_status", "payload->>'account_status'"],
    ["region", "payload->>'region'"],
    ["country", "payload->>'country'"],
    ["preferred_currency", "payload->>'preferred_currency'"],
  ],
  catalog: [
    ["product_id", "payload->>'product_id'"],
    ["sku", "payload->>'sku'"],
    ["category", "payload->>'category'"],
    ["list_price", "(payload->>'list_price')::numeric(12,2)"],
  ],
  orders: [
    ["order_id", "payload->>'order_id'"],
    ["customer_email_pk_id", "md5(lower(trim(payload->>'email_address')))"],
    ["sku", "payload->>'sku'"],
    ["status", "payload->>'status'"],
    ["quantity", "(payload->>'quantity')::integer"],
  ],
};

const DIM = {
  accounts: "reportingdw.dim_customer",
  catalog: "reportingdw.dim_product",
  orders: "reportingdw.dim_date",
};

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function planRow(feed, row, cursor, stored) {
  const key = row[feed.columns[0]];
  const after = STAMP.test(cursor) && String(row.updated_at) > cursor;
  let fate = "stays";
  if (after && stored.has(key)) fate = "stored";
  else if (after) fate = "insert";
  return { key, fate, updated: row.updated_at, detail: detail(feed.id, row) };
}

function detail(feedId, row) {
  if (feedId === "accounts") return row.email_address;
  if (feedId === "catalog") return row.sku;
  return `${row.email_address} · ${row.status}`;
}

export default function Flow({ feeds, cutoff, tables, stage, onSources }) {
  const [cursor, setCursor] = useState(cutoff);
  const [stored, setStored] = useState(() => byFeed(tables));
  const [playing, setPlaying] = useState(false);
  const [active, setActive] = useState("");
  const [packet, setPacket] = useState("");
  const [hop, setHop] = useState("");
  const [fresh, setFresh] = useState([]);
  const [board, setBoard] = useState(stage);
  const [note, setNote] = useState("Bronze keeps the name and email. Silver keeps segment, plan, status, region, and currency, and replaces the email with one md5 token.");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState({ object: "pipeline", key: "" });
  const token = useRef(0);
  const valid = STAMP.test(cursor);

  useEffect(() => {
    setStored(byFeed(tables));
  }, [tables]);

  useEffect(() => {
    setBoard(stage);
  }, [stage]);

  function choose(event) {
    const node = event.target.closest("[data-object]");
    if (!node) return;
    setSelected({ object: node.dataset.object, key: node.dataset.key || "" });
  }

  async function run() {
    if (!valid) return;
    const mine = ++token.current;
    setPlaying(true);
    setError("");
    setFresh([]);
    try {
      for (const feed of feeds) {
        if (token.current !== mine) return;
        const keys = new Set((stored[feed.id] ?? []).map((row) => row.business_key));
        const planned = feed.rows.map((row) => planRow(feed, row, cursor, keys));
        const inserting = planned.filter((row) => row.fate === "insert");
        setActive(feed.id);
        setHop("filter");
        setPacket(inserting[0]?.key || "—");
        setNote(
          inserting.length
            ? `${feed.id}: insert ${inserting.map((row) => row.key).join(", ")} into ${LANDING[feed.id]}.`
            : `${feed.id}: no new business_key after ${cursor}.`,
        );
        await delay(500);
        if (token.current !== mine) return;
        setHop("insert");
        const result = await insertFeed(feed.id, cursor);
        if (token.current !== mine) return;
        setStored((current) => ({ ...current, [feed.id]: result.rows }));
        setFresh(result.inserted.map((row) => row.business_key));
        for (const row of result.inserted) {
          setPacket(row.business_key);
          await delay(280);
          if (token.current !== mine) return;
        }
        setHop("stg");
        setNote(`${STG[feed.id]} reads ${result.lake_table}.payload.`);
        const staged = await stageFeed(feed.id);
        if (token.current !== mine) return;
        setBoard(staged);
        await delay(280);
      }
      if (token.current !== mine) return;
      setActive("");
      setHop("conform");
      setPacket("");
      const modeled = await publishModel();
      if (token.current !== mine) return;
      const skipped = modeled.skipped_products || [];
      setNote(
        skipped.length
          ? `dim_ keys are md5 of the staged values. ${skipped.join(", ")} stayed out of dim_product because that sku already has a key.`
          : "Silver dropped the name and email, kept the customer attributes, and Gold joined on customer_email_pk_id.",
      );
      setBoard(modeled);
      setSelected({ object: "fct-order", key: "" });
      setHop("");
    } catch (err) {
      if (token.current === mine) setError(err.message || "The insert failed.");
    } finally {
      if (token.current === mine) setPlaying(false);
    }
  }

  const meta = describe(selected, { feeds, stored, board, cursor });

  return (
    <>
      <section className="flow-board" data-testid="extract" onClick={choose} data-object="pipeline">
        <div className="lesson-toolbar">
          <div className="toolbar-title">
            <span>Run lesson</span>
            <strong>Incremental load</strong>
          </div>
          <div className="run-controls">
            <label className="date-field">
              <span>Watermark · source_updated_at &gt;</span>
              <input
                data-testid="last-extract"
                value={cursor}
                spellCheck={false}
                onChange={(event) => setCursor(event.target.value.trim())}
                disabled={playing}
              />
            </label>
            <button type="button" data-testid="run-insert" onClick={run} disabled={playing || !valid}>
              {playing ? "Inserting…" : "Insert new rows"}
            </button>
          </div>
          <p
            className={`extract-note${error || !valid ? " is-error" : ""}`}
            data-testid="extract-note"
            aria-live="polite"
          >
            <span className="status-dot" aria-hidden="true" />
            {error || (valid ? note : "Use a UTC timestamp, 2026-07-04T00:00:00Z.")}
          </p>
        </div>
        <div className="flow-scroll">
          <div className="diagram">
            <div className="lanes">
              <div className="lane head">
                <StageHead number="01" label="Source" hint="rows or JSON" />
                <span aria-hidden="true" />
                <StageHead number="02" label="Filter" hint="watermark" />
                <span aria-hidden="true" />
                <StageHead number="03" label="Bronze" hint="raw jsonb + PII" />
                <span aria-hidden="true" />
                <StageHead number="04" label="Silver" hint="typed · PII removed" />
                <span aria-hidden="true" />
                <StageHead number="05" label="Gold dimension" hint="conformed keys" />
                <span aria-hidden="true" />
              </div>
              {feeds.map((feed) => (
                <Lane
                  key={feed.id}
                  feed={feed}
                  cursor={cursor}
                  rows={stored[feed.id] ?? []}
                  board={board}
                  hot={active === feed.id}
                  hop={hop}
                  packet={packet}
                  fresh={fresh}
                  selected={selected}
                  onAdded={onSources}
                />
              ))}
            </div>
            <div className="colhead fact-head">
              <span className="stage-number">06</span>
              <strong>Gold fact</strong>
              <small>joined grain</small>
            </div>
            <FactNode board={board} selected={selected} hot={hop === "conform"} />
          </div>
        </div>
      </section>
      <aside className="inspector" data-testid="metadata">
        <div className="inspector-title">
          <p className="tech">Lesson notes · {meta.layer}</p>
          <h2 data-testid="metadata-name">{meta.name}</h2>
        </div>
        <p className="talk" data-testid="metadata-talk">{meta.talk}</p>
        <dl className="meta-list">
          {meta.facts.map((fact) => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
        {meta.sql ? (
          <details className="query">
            <summary>query</summary>
            <pre>{meta.sql}</pre>
          </details>
        ) : null}
        {meta.row.length ? (
          <dl className="meta-list picked">
            {meta.row.map((field) => (
              <div key={field.name}>
                <dt>{field.name}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </aside>
    </>
  );
}

function StageHead({ number, label, hint }) {
  return (
    <div className="colhead">
      <span className="stage-number">{number}</span>
      <strong>{label}</strong>
      <small>{hint}</small>
    </div>
  );
}

function Lane({ feed, cursor, rows, board, hot, hop, packet, fresh, selected, onAdded }) {
  const keys = new Set(rows.map((row) => row.business_key));
  const planned = feed.rows.map((row) => planRow(feed, row, cursor, keys));
  const moving = planned.filter((row) => row.fate !== "stays");
  const staged = stageRows(board, feed.id);
  const dimension = modelRows(board, DIM[feed.id]);
  const jsonSource = feed.id !== "accounts";
  const landingColumns = jsonSource
    ? ["business_key", "landing_id", "payload"]
    : ["business_key", "landing_id", "source_updated_at"];
  return (
    <div className={`lane${hot ? " is-active" : ""}`} data-testid={`flow-${feed.id}`}>
      <div className={`node${mark(selected, `source-${feed.id}`)}`} data-object={`source-${feed.id}`}>
        <p className="tech">{feed.technology}</p>
        <h2>{feed.name}</h2>
        <p className="location">{feed.location.replace(/^etl_flow\./, "")}</p>
        {jsonSource ? (
          <JsonDocs feed={feed} planned={planned} selected={selected} />
        ) : (
          <Grid
            columns={feed.columns}
            rows={planned.map((row) => ({
              key: row.key,
              fate: row.fate,
              testId: `row-${row.key}`,
              cells: Object.fromEntries(feed.columns.map((name) => [name, feed.rows.find((item) => item[feed.columns[0]] === row.key)?.[name] ?? ""])),
            }))}
            objectId={`source-${feed.id}`}
            selected={selected}
          />
        )}
        <AddRow feed={feed} onAdded={onAdded} />
        <Query sql={SPECS[`source-${feed.id}`].sql} />
      </div>
      <Arrow hot={hot && hop === "filter"} packet={hot && hop === "filter" ? packet : ""} objectId={`edge-filter-${feed.id}`} />
      <div className={`node${mark(selected, `predicate-${feed.id}`)}`} data-object={`predicate-${feed.id}`}>
        <p className="tech">predicate</p>
        <h2>source_updated_at</h2>
        <p className="location">&gt; {cursor}</p>
        <Grid
          columns={["business_key", "action"]}
          rows={moving.map((row) => ({
            key: row.key,
            fate: row.fate,
            testId: `pick-${row.key}`,
            cells: { business_key: row.key, action: row.fate === "stored" ? "already stored" : "insert" },
          }))}
          objectId={`predicate-${feed.id}`}
          selected={selected}
        />
        <Query sql={SPECS[`predicate-${feed.id}`].sql} />
      </div>
      <Arrow hot={hot && hop === "insert"} word="INSERT" packet={hot && hop === "insert" ? packet : ""} objectId={`edge-insert-${feed.id}`} />
      <div className={`node bronze-node${mark(selected, `landing-${feed.id}`)}`} data-object={`landing-${feed.id}`} data-testid={`lake-${feed.id}`}>
        <p className="tech">Bronze · raw · PII retained</p>
        <h2>{LANDING[feed.id]}</h2>
        <p className="location">insert only · payload jsonb</p>
        <Grid
          columns={landingColumns}
          rows={rows.map((row) => ({
            key: row.business_key,
            fate: fresh.includes(row.business_key) && hot ? "landing" : "stored",
            testId: `lake-row-${row.business_key}`,
            cells: jsonSource
              ? {
                business_key: row.business_key,
                landing_id: row.landing_id,
                payload: JSON.stringify(row.payload),
              }
              : {
                business_key: row.business_key,
                landing_id: row.landing_id,
                source_updated_at: row.source_updated_at,
              },
          }))}
          objectId={`landing-${feed.id}`}
          selected={selected}
        />
        <Query sql={SPECS[`landing-${feed.id}`].sql} />
      </div>
      <Arrow
        hot={hot && hop === "stg"}
        word={feed.id === "catalog" ? "TYPE" : "HASH PII"}
        packet={hot && hop === "stg" ? packet : ""}
        objectId={`edge-stage-${feed.id}`}
      />
      <div className={`node silver-node${mark(selected, `stg-${feed.id}`)}`} data-object={`stg-${feed.id}`} data-testid={`stg-${feed.id}`}>
        <p className="tech">Silver · typed · PII removed</p>
        <h2>{STG[feed.id]}</h2>
        <Grid
          columns={EXTRACTED[feed.id].map(([name]) => name)}
          rows={staged.map((row) => ({
            key: row.key,
            fate: "stored",
            testId: `stg-row-${feed.id}-${row.key}`,
            cells: Object.fromEntries(row.columns.map((field) => [field.name, field.value])),
          }))}
          objectId={`stg-${feed.id}`}
          selected={selected}
        />
        <Query sql={SPECS[`stg-${feed.id}`].sql} />
      </div>
      <Arrow hot={hop === "conform"} word="DIM" objectId={`edge-dim-${feed.id}`} />
      <div className={`node gold-node${mark(selected, `dim-${feed.id}`)}`} data-object={`dim-${feed.id}`} data-testid={feed.id === "accounts" ? "dim-customer" : feed.id === "catalog" ? "dim-product" : "dim-date"}>
        <p className="tech">Gold · dimension</p>
        <h2>{DIM[feed.id]}</h2>
        <Grid
          columns={visibleDim(feed.id)}
          rows={dimension.map((row) => ({
            key: row.key,
            fate: "stored",
            testId: `dim-row-${feed.id}-${row.key}`,
            cells: Object.fromEntries(row.columns.map((field) => [field.name, field.value])),
          }))}
          objectId={`dim-${feed.id}`}
          selected={selected}
        />
        <Query sql={SPECS[`dim-${feed.id}`].sql} />
      </div>
      <Arrow hot={hop === "conform"} word="FK" objectId={`edge-fact-${feed.id}`} />
    </div>
  );
}

function FactNode({ board, selected, hot }) {
  const rows = modelRows(board, "reportingdw.fct_order");
  return (
    <div className={`node gold-node fact-span${hot ? " is-hot" : ""}${mark(selected, "fct-order")}`} data-object="fct-order" data-testid="fct-order">
      <p className="tech">Gold · fact · grain order_id</p>
      <h2>reportingdw.fct_order</h2>
      <Grid
        columns={["order_id", "customer_key", "product_key", "order_date_key", "quantity", "extended_amount", "status"]}
        rows={rows.map((row) => ({
          key: row.key,
          fate: "stored",
          testId: `fct-row-${row.key}`,
          cells: Object.fromEntries(row.columns.map((field) => [field.name, field.value])),
        }))}
        objectId="fct-order"
        selected={selected}
      />
      <Query sql={SPECS["fct-order"].sql} />
    </div>
  );
}

function Query({ sql }) {
  if (!sql) return null;
  return (
    <details className="query">
      <summary>query</summary>
      <pre>{sql}</pre>
    </details>
  );
}

function JsonDocs({ feed, planned, selected }) {
  return (
    <div className="json-stack" data-testid={`json-${feed.id}`}>
      {planned.map((row) => {
        const doc = feed.rows.find((item) => item[feed.columns[0]] === row.key) || {};
        return (
          <pre
            key={row.key}
            data-object={`source-${feed.id}`}
            data-key={row.key}
            data-testid={`row-${row.key}`}
            className={`json-doc ${rowClass(row.fate, selected, `source-${feed.id}`, row.key)}`}
          >
            {JSON.stringify(doc)}
          </pre>
        );
      })}
    </div>
  );
}

const ADD = {
  accounts: [
    ["email_address", "eva.lind@field.test"],
    ["full_name", "Eva Lind"],
    ["country", "SE"],
    ["region", "Europe"],
    ["customer_segment", "Retail"],
    ["account_plan", "Field"],
    ["account_status", "active"],
    ["preferred_currency", "SEK"],
    ["updated_at", "2026-07-07T12:00:00Z"],
  ],
  catalog: [
    ["product_id", "P7009"],
    ["sku", "Brass ruler"],
    ["list_price", "15.00"],
    ["updated_at", "2026-07-07T12:00:00Z"],
  ],
  orders: [
    ["order_id", "O1009"],
    ["email_address", "cio@field.test"],
    ["sku", "Ink bottle"],
    ["status", "paid"],
    ["quantity", "1"],
    ["updated_at", "2026-07-07T12:00:00Z"],
  ],
};

function AddRow({ feed, onAdded }) {
  const fields = ADD[feed.id];
  const [values, setValues] = useState(() => Object.fromEntries(fields.map(([name, sample]) => [name, name === "updated_at" ? sample : ""])));
  const [problem, setProblem] = useState("");

  async function submit(event) {
    event.preventDefault();
    setProblem("");
    const body = {};
    for (const [name] of fields) {
      const value = String(values[name] ?? "").trim();
      body[name] = name === "quantity" ? Number(value) : value;
    }
    try {
      const view = await addSourceRow(feed.id, body);
      onAdded?.(view);
    } catch (err) {
      setProblem(err.message || "The source row was not added.");
    }
  }

  return (
    <details className="query">
      <summary>add source row</summary>
      <form className="add-row" onSubmit={submit}>
        {fields.map(([name, sample]) => (
          <label key={name}>
            {name}
            <input
              aria-label={`${feed.id} ${name}`}
              value={values[name]}
              placeholder={sample}
              spellCheck={false}
              onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.value }))}
            />
          </label>
        ))}
        <button type="submit">Add</button>
        {problem ? <p className="add-problem">{problem}</p> : null}
      </form>
    </details>
  );
}

function Grid({ columns, rows, objectId, selected }) {
  return (
    <div className="grid-scroll">
      <table className="grid">
        <thead>
          <tr>
            {columns.map((name) => <th key={name}>{name}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>No rows stored yet.</td>
            </tr>
          ) : rows.map((row) => (
            <tr
              key={row.key}
              data-object={objectId}
              data-key={row.key}
              data-testid={row.testId}
              className={rowClass(row.fate, selected, objectId, row.key)}
              aria-selected={selected.object === objectId && selected.key === row.key}
            >
              {columns.map((name) => <td key={name}>{row.cells[name] ?? ""}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Arrow({ hot, word, packet, objectId }) {
  return (
    <div className={`flow-arrow${hot ? " hot" : ""}`} data-object={objectId} role="button" tabIndex={0}>
      <span className="shaft" />
      {word ? <span className="arrow-word">{word}</span> : null}
      {packet ? <span className="packet">{packet}</span> : null}
    </div>
  );
}

function byFeed(tables) {
  return Object.fromEntries(tables.map((table) => [table.feed_id, table.rows]));
}

function stageRows(board, feedId) {
  return board?.feeds?.find((feed) => feed.feed_id === feedId)?.rows ?? [];
}

function modelRows(board, tableName) {
  return board?.model?.find((table) => table.table_name === tableName)?.rows ?? [];
}

function mark(selected, objectId) {
  return selected.object === objectId ? " is-selected" : "";
}

function rowClass(fate, selected, objectId, key) {
  const picked = selected.object === objectId && selected.key === key ? " is-picked" : "";
  return `${fate}${picked}`;
}

function visibleDim(feedId) {
  if (feedId === "accounts") {
    return ["customer_key", "customer_segment", "account_plan", "account_status", "region", "country", "preferred_currency"];
  }
  if (feedId === "catalog") return ["product_key", "product_id", "sku", "category", "list_price"];
  return ["date_key", "calendar_date"];
}

function describe(selected, ctx) {
  const spec = SPECS[selected.object] || SPECS.pipeline;
  const facts = spec.facts.map((fact) => ({ ...fact, value: typeof fact.value === "function" ? fact.value(ctx) : fact.value }));
  return {
    layer: spec.layer,
    name: spec.name,
    talk: spec.talk,
    facts,
    sql: spec.sql || "",
    row: pickedRow(selected, ctx),
  };
}

function pickedRow(selected, ctx) {
  if (!selected.key) return [];
  const feedId = selected.object.split("-").slice(1).join("-");
  if (selected.object.startsWith("landing-")) {
    const row = (ctx.stored[feedId] ?? []).find((item) => item.business_key === selected.key);
    if (!row) return [];
    return [
      { name: "landing_id", value: row.landing_id },
      { name: "run_id", value: row.run_id },
      { name: "batch_id", value: row.batch_id },
      { name: "business_key", value: row.business_key },
      { name: "source_updated_at", value: row.source_updated_at },
      { name: "extracted_at", value: row.extracted_at },
      { name: "payload", value: JSON.stringify(row.payload) },
    ];
  }
  if (selected.object.startsWith("stg-")) {
    return stageRows(ctx.board, feedId).find((row) => row.key === selected.key)?.columns ?? [];
  }
  if (selected.object.startsWith("dim-")) {
    return modelRows(ctx.board, DIM[feedId]).find((row) => row.key === selected.key)?.columns ?? [];
  }
  if (selected.object === "fct-order") {
    return modelRows(ctx.board, "reportingdw.fct_order").find((row) => row.key === selected.key)?.columns ?? [];
  }
  if (selected.object.startsWith("source-") || selected.object.startsWith("predicate-")) {
    const feed = ctx.feeds.find((item) => item.id === feedId);
    const row = feed?.rows?.find((item) => item[feed.columns[0]] === selected.key);
    if (!row) return [];
    return Object.entries(row).map(([name, value]) => ({ name, value: String(value) }));
  }
  return [];
}

const SPECS = {
  pipeline: {
    layer: "medallion map",
    name: "Source → Bronze → Silver → Gold",
    talk: "Bronze keeps the source document, including the customer name and email. Silver keeps segment, plan, status, region, and currency, and both customer and order become the same customer_email_pk_id. Gold joins those tokens.",
    facts: [
      { label: "Bronze", value: "accounts.raw_customer, catalog.raw_catalog, orders.raw_order" },
      { label: "Silver", value: "stg.stg_customer, stg.stg_catalog, stg.stg_order" },
      { label: "Gold", value: "reportingdw.dim_customer, dim_product, dim_date, fct_order" },
      { label: "PII boundary", value: "email_address → md5(lower(trim(email_address)))" },
      { label: "privacy note", value: "MD5 is a lesson token, not secure anonymization; production uses keyed HMAC-SHA-256." },
      { label: "load", value: "INSERT. A stored business key is not updated." },
    ],
  },
  "source-accounts": sourceSpec("accounts", "PostgreSQL", "ops.customer_account", "one email_address", "email_address, full_name, country, region, customer_segment, account_plan, account_status, preferred_currency, updated_at"),
  "source-catalog": sourceSpec("catalog", "HTTP", "GET /api/sources/catalog", "one product_id", "product_id, sku, category, list_price, updated_at"),
  "source-orders": sourceSpec("orders", "MongoDB", "etl_lesson.order_events", "one order_id", "order_id, email_address, sku, status, quantity, updated_at"),
  "predicate-accounts": predicateSpec("accounts"),
  "predicate-catalog": predicateSpec("catalog"),
  "predicate-orders": predicateSpec("orders"),
  "landing-accounts": landingSpec("accounts", "email_address"),
  "landing-catalog": landingSpec("catalog", "product_id"),
  "landing-orders": landingSpec("orders", "order_id"),
  "stg-accounts": stgSpec("accounts"),
  "stg-catalog": stgSpec("catalog"),
  "stg-orders": stgSpec("orders"),
  "dim-accounts": {
    layer: "Gold dimension",
    name: "reportingdw.dim_customer",
    talk: "One row per customer_email_pk_id. customer_key is that token. The dimension carries segment, plan, status, region, country, and currency. full_name and email_address stay in Bronze.",
    facts: [
      { label: "grain", value: "one customer_email_pk_id" },
      { label: "pk", value: "customer_key = customer_email_pk_id" },
      { label: "attributes", value: "segment, plan, status, region, country, currency" },
      { label: "source identity", value: "md5(lower(trim(email_address)))" },
      { label: "PII", value: "full_name and email_address omitted" },
      { label: "index", value: "dim_customer_segment_idx (customer_segment), dim_customer_country_idx (country)" },
      { label: "rows", value: (ctx) => String(modelRows(ctx.board, "reportingdw.dim_customer").length) },
    ],
    sql: "INSERT INTO reportingdw.dim_customer (\n       customer_key, customer_email_pk_id, country, region, customer_segment,\n       account_plan, account_status, preferred_currency, source_updated_at, batch_id)\nSELECT DISTINCT ON (customer_email_pk_id)\n       customer_email_pk_id, customer_email_pk_id, country, region, customer_segment,\n       account_plan, account_status, preferred_currency, source_updated_at, batch_id\nFROM stg.stg_customer\nWHERE customer_email_pk_id NOT IN (\n  SELECT customer_email_pk_id FROM reportingdw.dim_customer\n)\nORDER BY customer_email_pk_id, source_updated_at;",
  },
  "dim-catalog": {
    layer: "dimension",
    name: "reportingdw.dim_product",
    talk: "One row per product_id, taken from stg.stg_catalog. product_key is md5(product_id || '|' || sku || '|' || list_price). sku stays unique because fct_order resolves the product with stg_order.sku.",
    facts: [
      { label: "grain", value: "one product_id" },
      { label: "pk", value: "product_key text = md5(product_id, sku, list_price)" },
      { label: "natural key", value: "product_id" },
      { label: "unique", value: "sku. A second product_id with that sku is not inserted." },
      { label: "skipped", value: (ctx) => (ctx.board?.skipped_products || []).join(", ") || "none" },
      { label: "rows", value: (ctx) => String(modelRows(ctx.board, "reportingdw.dim_product").length) },
    ],
    sql: "INSERT INTO reportingdw.dim_product (product_key, product_id, sku, category, list_price, source_updated_at, batch_id)\nSELECT DISTINCT ON (product_id)\n       md5(product_id || '|' || sku || '|' || to_char(list_price, 'FM999999990.00')),\n       product_id, sku, category, list_price, source_updated_at, batch_id\nFROM stg.stg_catalog\nWHERE product_id NOT IN (SELECT product_id FROM reportingdw.dim_product)\nORDER BY product_id, source_updated_at;",
  },
  "dim-orders": {
    layer: "dimension",
    name: "reportingdw.dim_date",
    talk: "One row per calendar date from the earliest staged order date through the latest, in UTC. date_key is md5 of that date. A date in that span with no order is still a row.",
    facts: [
      { label: "grain", value: "one calendar date" },
      { label: "pk", value: "date_key text = md5(calendar date)" },
      { label: "role", value: "fct_order.order_date_key" },
      { label: "rows", value: (ctx) => String(modelRows(ctx.board, "reportingdw.dim_date").length) },
    ],
    sql: "INSERT INTO reportingdw.dim_date (date_key, calendar_date, year_number, month_number, day_number)\nSELECT md5(to_char(day::date, 'YYYY-MM-DD')), day::date,\n       EXTRACT(YEAR FROM day)::int, EXTRACT(MONTH FROM day)::int, EXTRACT(DAY FROM day)::int\nFROM generate_series(min(order date), max(order date), interval '1 day') AS day\nWHERE date_key IS NOT already stored;",
  },
  "fct-order": {
    layer: "Gold fact",
    name: "reportingdw.fct_order",
    talk: "One row per order_id. The customer join compares the PII-free customer_email_pk_id produced independently by both Silver tables. product_key still resolves through sku.",
    facts: [
      { label: "grain", value: "one order_id" },
      { label: "fk", value: "customer_key, product_key, order_date_key" },
      { label: "measures", value: "quantity, unit_price, extended_amount" },
      { label: "unresolved", value: (ctx) => (ctx.board?.unresolved_orders || []).join(", ") || "none" },
      { label: "rows", value: (ctx) => String(modelRows(ctx.board, "reportingdw.fct_order").length) },
    ],
    sql: "INSERT INTO reportingdw.fct_order (order_id, customer_key, product_key, order_date_key, quantity, unit_price, extended_amount, status, batch_id)\nSELECT o.order_id, c.customer_key, p.product_key,\n       md5(to_char((o.source_updated_at AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD')),\n       o.quantity, p.list_price, (o.quantity * p.list_price)::numeric(12,2), o.status, o.batch_id\nFROM stg.stg_order o\nJOIN reportingdw.dim_customer c\n  ON c.customer_email_pk_id = o.customer_email_pk_id\nJOIN reportingdw.dim_product p ON p.sku = o.sku\nWHERE NOT EXISTS (SELECT 1 FROM reportingdw.fct_order f WHERE f.order_id = o.order_id);",
  },
};

for (const feedId of ["accounts", "catalog", "orders"]) {
  SPECS[`edge-filter-${feedId}`] = {
    layer: "extract",
    name: `${feedId} → predicate`,
    talk: `Keep the ${feedId} row when source_updated_at is strictly after the timestamp in the box.`,
    facts: [{ label: "comparison", value: "(updated_at) > cursor" }],
  };
  SPECS[`edge-insert-${feedId}`] = {
    layer: "Bronze load",
    name: `INSERT ${LANDING[feedId]}`,
    talk: "Insert the source document unchanged into Bronze payload jsonb. If that business_key is already present, its landing_id and extracted_at stay.",
    facts: [{ label: "table", value: LANDING[feedId] }, { label: "mode", value: "insert only" }],
  };
  SPECS[`edge-stage-${feedId}`] = {
    layer: "Bronze → Silver",
    name: `${LANDING[feedId]} → ${STG[feedId]}`,
    talk: feedId === "catalog"
      ? "One Bronze catalog document becomes one typed Silver row."
      : "At this boundary, email_address becomes customer_email_pk_id. The clear email is omitted from Silver.",
    facts: EXTRACTED[feedId].map(([name, expr]) => ({ label: name, value: expr })),
  };
  SPECS[`edge-dim-${feedId}`] = {
    layer: "Silver → Gold",
    name: `${STG[feedId]} → ${DIM[feedId]}`,
    talk: feedId === "orders"
      ? "dim_date is generated from the UTC dates on stg.stg_order. It is not a copy of the order."
      : `One natural key from ${STG[feedId]} becomes one dimension row. A key that is already stored is skipped.`,
    facts: [{ label: "table", value: DIM[feedId] }],
  };
  SPECS[`edge-fact-${feedId}`] = {
    layer: "Gold foreign key",
    name: `${DIM[feedId]} → reportingdw.fct_order`,
    talk: feedId === "accounts"
      ? "fct_order.customer_key references dim_customer.customer_key. Customer and order match on the same customer_email_pk_id; the email itself is absent."
      : feedId === "catalog"
        ? "fct_order.product_key references dim_product.product_key. The match uses sku, because the order jsonb has sku and the catalog jsonb has product_id."
        : "fct_order.order_date_key references dim_date.date_key. The date is the order's source_updated_at in UTC.",
    facts: [{ label: "fact", value: "reportingdw.fct_order" }],
  };
}

function sourceSpec(feedId, technology, location, grain, columns) {
  const sql = feedId === "catalog"
    ? "GET /api/sources/catalog\n-- the body is a JSON array. Each object is stored as payload jsonb."
    : feedId === "orders"
      ? "db.getSiblingDB('etl_lesson').order_events.find().sort({ updated_at: 1, order_id: 1 })\n-- each document is stored as payload jsonb."
      : "SELECT email_address, full_name, country, region, customer_segment,\n       account_plan, account_status, preferred_currency, updated_at\nFROM ops.customer_account\nORDER BY updated_at, email_address;";
  const talk = feedId === "accounts"
    ? "PostgreSQL identifies the customer by email_address. The row also has a name and the attributes used for reporting. Bronze keeps all of them in payload."
    : feedId === "catalog"
      ? "The catalog API returns JSON. Ingestion stores that object in catalog.raw_catalog.payload. The landing table does not type the columns."
      : "MongoDB returns one JSON order containing email_address. Bronze stores the document unchanged; Silver hashes the address.";
  return {
    layer: technology,
    name: location,
    talk,
    facts: [
      { label: "grain", value: grain },
      { label: "return", value: feedId === "accounts" ? columns : "JSON" },
      { label: "landing", value: LANDING[feedId] },
    ],
    sql,
  };
}

function predicateSpec(feedId) {
  return {
    layer: "predicate",
    name: `${feedId}.source_updated_at > cursor`,
    talk: "The box is the last extraction timestamp. Rows on or before it stay in the source. Rows after it are candidates. A candidate whose business_key is already landed is not inserted again.",
    facts: [
      { label: "cursor", value: (ctx) => ctx.cursor },
      { label: "table", value: LANDING[feedId] },
    ],
    sql: "WHERE updated_at > :cursor\n  AND business_key NOT IN (SELECT business_key FROM landing);",
  };
}

function landingSpec(feedId, businessKey) {
  return {
    layer: "Bronze landing",
    name: LANDING[feedId],
    talk: `Physical Bronze table for the ${feedId} source. The raw document stays in payload jsonb, including source PII. business_key is ${businessKey}.`,
    facts: [
      { label: "pk", value: "landing_id" },
      { label: "unique", value: "(batch_id, business_key)" },
      { label: "columns", value: "landing_id, run_id, batch_id, business_key, source_updated_at, payload jsonb, extracted_at" },
      { label: "rows", value: (ctx) => String((ctx.stored[feedId] ?? []).length) },
    ],
    sql: `INSERT INTO ${LANDING[feedId]} (landing_id, run_id, batch_id, business_key, source_updated_at, payload, extracted_at)\nVALUES (batch_id || '-' || business_key, batch_id, batch_id, business_key, payload->>'updated_at', payload, now());`,
  };
}

function stgSpec(feedId) {
  const extracted = EXTRACTED[feedId].map(([name, expr]) => `${name} = ${expr}`).join(", ");
  const talk = feedId === "orders"
    ? "Silver hashes orders.raw_order.payload.email_address into customer_email_pk_id. The clear email is not selected. Gold uses that token to find the customer."
    : feedId === "catalog"
      ? "stg.stg_catalog extracts product_id, sku, category, and list_price from catalog.raw_catalog.payload. product_id is the catalog key. The fact uses sku to point an order at this product."
      : "Silver hashes accounts.raw_customer.payload.email_address into customer_email_pk_id. It keeps segment, plan, status, region, country, and currency. full_name and the clear email stay in Bronze.";
  return {
    layer: "Silver staging",
    name: STG[feedId],
    talk,
    facts: [
      { label: "from", value: LANDING[feedId] },
      { label: "extract", value: extracted },
      { label: "pk", value: feedId === "accounts" ? "(batch_id, customer_email_pk_id)" : feedId === "catalog" ? "(batch_id, product_id)" : "(batch_id, order_id)" },
      { label: "PII", value: feedId === "catalog" ? "none in source" : "full_name and email_address omitted" },
      { label: "rows", value: (ctx) => String(stageRows(ctx.board, feedId).length) },
    ],
    sql: feedId === "orders"
      ? "INSERT INTO stg.stg_order (batch_id, order_id, customer_email_pk_id, sku, status, quantity, source_updated_at)\nSELECT batch_id,\n       payload->>'order_id',\n       md5(lower(btrim(payload->>'email_address'))),\n       payload->>'sku',\n       payload->>'status',\n       (payload->>'quantity')::integer,\n       source_updated_at\nFROM orders.raw_order;"
      : feedId === "catalog"
        ? "INSERT INTO stg.stg_catalog (batch_id, product_id, sku, category, list_price, source_updated_at)\nSELECT batch_id,\n       payload->>'product_id',\n       payload->>'sku',\n       payload->>'category',\n       (payload->>'list_price')::numeric(12,2),\n       source_updated_at\nFROM catalog.raw_catalog;"
        : "INSERT INTO stg.stg_customer (\n       batch_id, landing_id, customer_email_pk_id, country, region,\n       customer_segment, account_plan, account_status, preferred_currency, source_updated_at)\nSELECT batch_id, landing_id,\n       md5(lower(btrim(payload->>'email_address'))),\n       payload->>'country', payload->>'region', payload->>'customer_segment',\n       payload->>'account_plan', payload->>'account_status', payload->>'preferred_currency',\n       source_updated_at\nFROM accounts.raw_customer;",
  };
}
