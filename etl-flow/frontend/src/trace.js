import { outcomeLabel } from "./rows";

export function storyLines(run, sources) {
  const lines = [];
  if (sources?.records?.length) {
    const ready = sources.records.filter((row) => row.outcome !== "stays").length;
    lines.push({
      id: "sources",
      text: `${sources.records.length} source rows · ${ready} are after 4 July 2026`,
    });
  }
  for (const step of run?.steps ?? []) {
    lines.push({ id: step.id, text: step.hint });
  }
  return lines;
}

export function buildTrace({ catalog, run, sources, key }) {
  return (catalog?.stages ?? []).map((spec) => {
    const revealed = spec.id === "sources" || run?.steps.some((step) => step.id === spec.id);
    if (!revealed) {
      return { ...spec, state: "waiting", headline: "Waiting", detail: "This step has not run.", chips: [], json: null };
    }
    const pool = spec.id === "sources" ? sources?.records ?? [] : run.steps.find((step) => step.id === spec.id)?.records ?? [];
    const row = pool.find((item) => item.business_key === key);
    if (!row) {
      return { ...spec, state: "stopped", headline: "Not in this step", detail: `${key} was not written here.`, chips: [], json: null };
    }
    return {
      ...spec,
      state: row.outcome === "stays" ? "stopped" : "ready",
      headline: outcomeLabel(row.outcome),
      detail: row.detail,
      chips: [],
      json: row.payload,
    };
  });
}
