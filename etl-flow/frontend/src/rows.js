const COLUMNS = [
  { key: "business_key", label: "Key" },
  { key: "source", label: "Source" },
  { key: "outcome", label: "Decision", kind: "outcome" },
  { key: "detail", label: "Detail" },
  { key: "source_updated_at", label: "Updated", kind: "stamp" },
];

export const COLUMN_SET = {
  sources: COLUMNS,
  accounts: COLUMNS,
  catalog: COLUMNS,
  orders: COLUMNS,
  stage: COLUMNS,
};

const OUTCOMES = {
  stays: "Stays",
  will_load: "Will load",
  loaded: "In the lake",
  staged: "In stg_",
};

export function outcomeLabel(value) {
  return OUTCOMES[value] ?? value;
}

export function isRevealed(stageId, run) {
  if (stageId === "sources") return true;
  return Boolean(run?.steps.some((step) => step.id === stageId));
}

export function stationStat(spec, { run, sources }) {
  if (spec.id === "sources") {
    const rows = sources?.records ?? [];
    const ready = rows.filter((row) => row.outcome === "will_load" || row.outcome === "loaded").length;
    return { value: rows.length || "—", hint: rows.length ? `${ready} after 4 July` : "Waiting", tone: "neutral" };
  }
  const step = run?.steps.find((item) => item.id === spec.id);
  if (!step) return { value: "—", hint: "Waiting", tone: "neutral" };
  return { value: step.output_count, hint: step.hint, tone: step.tone || "neutral" };
}

export function recordsFor(stageId, { run, sources }) {
  if (stageId === "sources") return sources?.records ?? [];
  return run?.steps.find((step) => step.id === stageId)?.records ?? [];
}

export function rowTone(row) {
  if (row.outcome === "stays") return "stays";
  return "";
}

export function matches(row, query) {
  if (!query) return true;
  return haystack(row).includes(query);
}

function haystack(row) {
  const parts = [];
  const visit = (value) => {
    if (value == null) return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (typeof value === "object") {
      Object.values(value).forEach(visit);
      return;
    }
    parts.push(String(value));
  };
  Object.values(row).forEach(visit);
  return parts.join(" ").toLowerCase();
}
