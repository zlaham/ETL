export const DOCS_URL = "http://127.0.0.1:8020/docs";

async function readJson(path, options) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* the body was not JSON */
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export function fetchHealth() {
  return readJson("/health");
}

export function fetchCatalog() {
  return readJson("/pipeline");
}

export function fetchSources() {
  return readJson("/sources");
}

export async function fetchLatest() {
  const runs = await readJson("/pipeline/runs");
  if (!runs.length) return null;
  return readJson(`/pipeline/runs/${runs[0].run_id}`);
}

export function advanceLesson() {
  return readJson("/pipeline/steps", { method: "POST" });
}

export function fetchLake() {
  return readJson("/lake");
}

export function stageCustomer() {
  return readJson("/stage/customer", { method: "POST" });
}

export function fetchStages() {
  return readJson("/stage");
}

export function stageFeed(feedId) {
  return readJson(`/stage/${feedId}`, { method: "POST" });
}

export function publishModel() {
  return readJson("/model", { method: "POST" });
}

export function addSourceRow(feedId, body) {
  return readJson(`/sources/${feedId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function insertFeed(feedId, updatedAt) {
  return readJson(`/extract/${feedId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updated_at: updatedAt }),
  });
}
