import { useCallback, useEffect, useMemo, useState } from "react";

import { classifyViewerState, rowsFromData } from "./viewerState.js";

const readLocation = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    caseId: params.get("case_id") || "",
    page: Math.max(1, Number(params.get("page") || 1)),
  };
};

const formatValue = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

function StatusPanel({ health }) {
  const ready = Boolean(health?.ok);
  const data = health?.data || {};
  const issues = data.readiness_issues || health?.error?.details || [];
  return (
    <section className="card status-card">
      <div className="card-heading">
        <div>
          <span className="eyebrow">Runtime status</span>
          <h2>{ready ? "Ready for read-only SAP queries" : "Configuration required"}</h2>
        </div>
        <span className={`status-pill ${ready ? "ready" : "warning"}`}>{ready ? "READY" : "NOT READY"}</span>
      </div>
      <div className="status-grid">
        <div><span>Indexed services</span><strong>{data.indexed_service_count ?? 0}</strong></div>
        <div><span>Executable services</span><strong>{data.executable_service_count ?? 0}</strong></div>
        <div><span>SAP URL</span><strong>{data.sap_base_url_configured ? "Configured" : "Missing"}</strong></div>
        <div><span>Viewer</span><strong>{data.viewer_enabled ? "Enabled" : "Disabled"}</strong></div>
      </div>
      {issues.length ? (
        <ul className="issue-list">
          {issues.map((issue) => <li key={issue.code || issue.message}>{issue.message || String(issue)}</li>)}
        </ul>
      ) : null}
    </section>
  );
}

function ResultTable({ data, presentation }) {
  const rows = rowsFromData(data);
  const columns = useMemo(() => {
    const preferred = Array.isArray(presentation?.columns) ? presentation.columns : [];
    if (preferred.length) return preferred;
    return [...new Set(rows.flatMap((row) => Object.keys(row).filter((key) => key !== "__metadata")))];
  }, [presentation, rows]);

  if (!rows.length) return <div className="empty-state">No result rows were saved for this case.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [{ caseId, page }] = useState(readLocation);
  const [health, setHealth] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [pagePayload, setPagePayload] = useState(null);
  const [loading, setLoading] = useState(Boolean(caseId));
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/health", { cache: "no-store" })
      .then((response) => response.json())
      .then(setHealth)
      .catch((reason) => setHealth({ ok: false, error: { details: [{ message: reason.message }] } }));
  }, []);

  const loadPage = useCallback(async (targetSkip) => {
    const response = await fetch("/api/v1/runtime/page", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: caseId, skip: targetSkip }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || "Unable to load this result page.");
    setPagePayload(payload);
    const pageNumber = Math.floor((payload.pagination?.skip || 0) / Math.max(1, payload.pagination?.page_size || 50)) + 1;
    const url = new URL(window.location.href);
    url.searchParams.set("page", String(pageNumber));
    window.history.replaceState({}, "", url);
  }, [caseId]);

  useEffect(() => {
    if (!caseId) return;
    let active = true;
    (async () => {
      try {
        const response = await fetch(`/api/v1/runtime/cases/${encodeURIComponent(caseId)}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || "Case not found.");
        if (!active) return;
        setSnapshot(payload.result_snapshot);
        const pagination = payload.result_snapshot?.pagination || {};
        const targetSkip = (page - 1) * Math.max(1, pagination.page_size || 50);
        if (targetSkip > 0) await loadPage(targetSkip);
      } catch (reason) {
        if (active) setError(reason.message || "Unable to load the SAPClaw case.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [caseId, page, loadPage]);

  const data = pagePayload?.data || snapshot?.data || {};
  const presentation = pagePayload?.data?.presentation || snapshot?.presentation || {};
  const pagination = pagePayload?.pagination || snapshot?.pagination || {};
  const viewerState = classifyViewerState({ caseId, loading, error, health, data, pagination });

  return (
    <div className="app-shell" data-viewer-state={viewerState}>
      <header className="hero">
        <div>
          <span className="eyebrow">SAPClaw Runtime · v2.0.0</span>
          <h1>Read-only SAP OData evidence for Codex</h1>
          <p>Codex plans the query. SAPClaw validates the schema, executes guarded GET requests, and preserves auditable results.</p>
        </div>
      </header>

      <main>
        {!caseId ? (
          <>
            <StatusPanel health={health} />
            <section className="card">
              <span className="eyebrow">Get started</span>
              <h2>Connect the SAPClaw Runtime MCP server</h2>
              <pre>sapclaw-runtime-mcp --base-url http://127.0.0.1:8000</pre>
              <p>Run a query through the <code>sapclaw_runtime</code> MCP server. Saved multi-row results open here automatically.</p>
            </section>
          </>
        ) : (
          <section className="card result-card">
            <div className="card-heading">
              <div><span className="eyebrow">SAPClaw case</span><h2>{caseId}</h2></div>
              <a href="/">Runtime status</a>
            </div>
            {loading ? <div className="empty-state">Loading result…</div> : null}
            {error ? <div className="error-state">{error}</div> : null}
            {!loading && !error ? (
              <>
                {presentation?.text ? <p className="summary">{presentation.text}</p> : null}
                <ResultTable data={data} presentation={presentation} />
                <div className="pagination">
                  <button disabled={(pagination.skip || 0) <= 0} onClick={() => loadPage(Math.max(0, (pagination.skip || 0) - (pagination.page_size || 50)))}>Previous</button>
                  <span>{pagination.total_count ?? rowsFromData(data).length} total · offset {pagination.skip || 0}</span>
                  <button disabled={!pagination.has_next} onClick={() => loadPage(pagination.next_skip ?? ((pagination.skip || 0) + (pagination.page_size || 50)))}>Next</button>
                </div>
              </>
            ) : null}
          </section>
        )}
      </main>
    </div>
  );
}
