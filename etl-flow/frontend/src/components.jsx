import { formatAmount, formatStamp } from "./format";
import { COLUMN_SET, matches, outcomeLabel, rowTone } from "./rows";

export function Rail({ stages, selectedStage, playhead, playing, onSelect }) {
  const width = stages.length <= 1 ? 0 : ((playhead - 1) / (stages.length - 1)) * 100;
  return (
    <section className="rail-wrap" aria-label="Pipeline stages">
      <div className="spine" aria-hidden="true">
        <div className="spine-base" />
        <div className="spine-hot" style={{ width: `${width}%` }} />
        {playing
          ? [0, 1, 2, 3].map((index) => (
              <span key={index} className="bead" style={{ animationDelay: `${index * 0.28}s` }} />
            ))
          : null}
      </div>
      <div className="stations">
        {stages.map(({ spec, stat, revealed }) => (
          <button
            key={spec.id}
            type="button"
            className="station"
            data-testid={`stage-${spec.id}`}
            data-layer={spec.layer}
            data-revealed={revealed ? "true" : "false"}
            aria-current={selectedStage === spec.id ? "step" : undefined}
            aria-disabled={!revealed}
            title={spec.summary}
            onClick={() => revealed && onSelect(spec.id)}
          >
            <span className="station-top">
              <span className="index">{String(spec.index).padStart(2, "0")}</span>
              <span className="layer">{spec.layer}</span>
            </span>
            <span className="station-title">{spec.title}</span>
            <span className="count">{stat.value}</span>
            <span className={`hint hint-${stat.tone}`}>{stat.hint}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function Story({ lines }) {
  if (!lines.length) return null;
  return (
    <ol className="story" data-testid="story" aria-live="polite">
      {lines.map((line) => (
        <li key={line.id}>{line.text}</li>
      ))}
    </ol>
  );
}

export function DataSheet({
  spec,
  rows,
  revealed,
  selectedOrder,
  onSelect,
  filter,
  onFilter,
  scriptSql,
  scriptPath,
  logs = [],
}) {
  const columns = COLUMN_SET[spec.id] ?? [];
  const query = filter.trim().toLowerCase();
  const shown = rows.filter((row) => matches(row, query));
  const countLabel = query ? `${shown.length} of ${rows.length} rows` : `${rows.length} rows`;

  return (
    <section className="sheet" data-testid="sheet">
      <div className="sheet-head">
        <div>
          <p className="sheet-kicker">{spec.layer}</p>
          <h2>{spec.title}</h2>
          <p>{spec.summary}</p>
        </div>
        <label className="filter">
          <span className="sr">Filter this stage</span>
          <input
            value={filter}
            onChange={(event) => onFilter(event.target.value)}
            placeholder="Filter by key"
          />
        </label>
      </div>
      <ul className="rules">
        {spec.rules.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
      {logs.length ? (
        <ul className="logs">
          {logs.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {scriptSql ? (
        <details className="sql">
          <summary>{scriptPath || "SQL"}</summary>
          <pre>{scriptSql}</pre>
        </details>
      ) : null}
      {!revealed ? (
        <p className="waiting">This stage fills when the run reaches it.</p>
      ) : rows.length === 0 ? (
        <p className="waiting">This stage produced no rows.</p>
      ) : shown.length === 0 ? (
        <p className="waiting">No rows in this stage match that filter.</p>
      ) : (
        <div className="table-wrap">
          <p className="count-label">{countLabel}</p>
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} scope="col" className={column.align === "end" ? "end" : undefined}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => {
                const tone = rowTone(row);
                const selected = row.business_key === selectedOrder;
                return (
                  <tr
                    key={row.business_key}
                    data-testid={`row-${row.business_key}`}
                    className={tone ? `tone-${tone}` : undefined}
                    aria-selected={selected}
                    tabIndex={0}
                    onClick={() => onSelect(row.business_key)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect(row.business_key);
                      }
                    }}
                  >
                    {columns.map((column) => (
                      <td key={column.key} className={column.align === "end" ? "end" : undefined}>
                        <Cell column={column} value={row[column.key]} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function Lineage({ orderId, keys = [], onKey, steps }) {
  return (
    <aside className="trace" data-testid="lineage">
      <p className="kicker">This row</p>
      <label className="key-pick">
        <span className="sr">Row to follow</span>
        <select value={orderId} onChange={(event) => onKey(event.target.value)}>
          {keys.map((key) => (
            <option key={key} value={key}>{key}</option>
          ))}
        </select>
      </label>
      <p className="trace-intro">Where this key is, after each step.</p>
      <ol>
        {steps.map((step) => (
          <li
            key={step.id}
            className="step"
            data-state={step.state}
            data-testid={`lineage-${step.id}`}
          >
            <p className="eyebrow">
              {String(step.index).padStart(2, "0")} · {step.layer}
            </p>
            <h3>{step.title}</h3>
            <p className="headline">{step.headline}</p>
            {step.detail ? <p className="detail">{step.detail}</p> : null}
            {step.chips.length ? (
              <div className="chips">
                {step.chips.map((chip) => (
                  <span key={`${chip.level}-${chip.text}`} className={`chip ${chip.level}`}>
                    {chip.text}
                  </span>
                ))}
              </div>
            ) : null}
            {step.json ? (
              <details>
                <summary>Record JSON</summary>
                <pre>{JSON.stringify(step.json, null, 2)}</pre>
              </details>
            ) : null}
          </li>
        ))}
      </ol>
    </aside>
  );
}

function Cell({ column, value }) {
  if (column.kind === "notes") return <Notes notes={value} />;
  if (column.kind === "chips") return <Chips values={value} level={column.chipLevel} />;
  if (column.kind === "outcome") {
    if (value == null || value === "") return <Empty />;
    return <span className={`pill pill-${value}`}>{outcomeLabel(value)}</span>;
  }
  if (column.kind === "money") {
    const amount = formatAmount(value);
    if (amount == null) return <span className="nil">null</span>;
    return amount;
  }
  if (column.kind === "stamp") {
    const stamp = formatStamp(value);
    if (!stamp) return <span className="nil">null</span>;
    return <span className="stamp">{stamp}</span>;
  }
  if (column.kind === "raw") return <RawValue value={value} />;
  if (value == null || value === "") return <span className="nil">null</span>;
  return String(value);
}

function Notes({ notes }) {
  if (!notes?.length) return <span className="quiet">Clean</span>;
  return (
    <span className="chips">
      {notes.map((note) => (
        <span key={`${note.level}-${note.message}`} className={`chip ${note.level}`}>
          {note.message}
        </span>
      ))}
    </span>
  );
}

function Chips({ values, level }) {
  if (!values?.length) return <Empty />;
  return (
    <span className="chips">
      {values.map((value) => (
        <span key={value} className={`chip ${level}`}>
          {value}
        </span>
      ))}
    </span>
  );
}

function RawValue({ value }) {
  if (value == null || value === "") return <span className="nil">null</span>;
  const text = String(value);
  const padded = text !== text.trim();
  return <code className={padded ? "raw raw-pad" : "raw"}>{text}</code>;
}

function Empty() {
  return <span className="quiet">—</span>;
}
