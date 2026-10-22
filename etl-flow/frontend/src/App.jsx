import { useEffect, useState } from "react";
import { DOCS_URL, fetchHealth, fetchLake, fetchSources, fetchStages } from "./api";
import Flow from "./Extract";

const API_ERROR =
  "The API is not reachable at http://127.0.0.1:8020. From etl-flow/backend, run: python -m uvicorn app.main:app --port 8020";

export default function App() {
  const [feeds, setFeeds] = useState(null);
  const [cutoff, setCutoff] = useState("");
  const [tables, setTables] = useState(null);
  const [stage, setStage] = useState(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const [health, sources, lake, customerStage] = await Promise.all([
          fetchHealth(),
          fetchSources(),
          fetchLake(),
          fetchStages(),
        ]);
        if (cancel) return;
        setFeeds(sources.feeds);
        setCutoff(sources.cutoff);
        setTables(lake.tables);
        setStage(customerStage);
        if (health.status !== "ok") setError(health.message || "PostgreSQL is unavailable.");
        else if (health.mongo !== "ok") setError(health.message || "MongoDB is unavailable.");
        else setError("");
      } catch (err) {
        if (!cancel) setError(err instanceof TypeError ? API_ERROR : err.message || API_ERROR);
      }
    }
    load();
    return () => {
      cancel = true;
    };
  }, [nonce]);

  if (!feeds || !tables || !stage) {
    return (
      <main className="app">
        <p className="kicker">Medallion lesson · incremental load</p>
        <h1>Follow one identity from PII to Gold</h1>
        {error ? (
          <div className="error">
            <p>{error}</p>
            <button type="button" onClick={() => setNonce((value) => value + 1)}>Retry</button>
          </div>
        ) : (
          <p className="lede">Reading accounts, catalog, and orders…</p>
        )}
      </main>
    );
  }

  return (
    <main className="app">
      <header className="top">
        <div className="identity">
          <p className="kicker">Medallion lesson · incremental load</p>
          <h1>Follow one identity from PII to Gold</h1>
          <p className="lede">Bronze keeps the name and email. Silver keeps segment, plan, status, region, and currency, and replaces the email with customer_email_pk_id. Gold joins customers to orders through that token.</p>
        </div>
        <div className="actions">
          <a className="ghost" href={DOCS_URL} target="_blank" rel="noreferrer">API reference ↗</a>
        </div>
      </header>
      {error ? <div className="error"><p>{error}</p></div> : null}
      <div className="studio">
        <Flow
          feeds={feeds}
          cutoff={cutoff}
          tables={tables}
          stage={stage}
          onSources={(next) => {
            setFeeds(next.feeds);
            setCutoff(next.cutoff);
          }}
        />
      </div>
    </main>
  );
}
