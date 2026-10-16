import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  downloadDailyReconciliationCsv,
  downloadUnresolvedCasesCsv,
  fetchDailyReconciliationReport,
  fetchUnresolvedCaseReport,
  type DailyReconciliationReport,
  type UnresolvedCaseReport,
} from "./api";

type ReportState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; daily: DailyReconciliationReport; unresolved: UnresolvedCaseReport };

const classificationLabels: Record<string, string> = {
  exact_match: "Exact match",
  partial_match: "Partial match",
  missing_settlement: "Missing settlement",
  duplicate_candidate: "Duplicate candidate",
  unexplained_settlement: "Unexplained settlement",
};

function todayUtc() {
  return new Date().toISOString().slice(0, 10);
}

function utcLabel(value: string) {
  return `${new Date(value).toLocaleString("en-GB", { timeZone: "UTC" })} UTC`;
}

function saveDownload(result: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(result.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = result.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ReportWorkspace({ token }: { token: string }) {
  const [draftDate, setDraftDate] = useState(todayUtc);
  const [reportDate, setReportDate] = useState(todayUtc);
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<ReportState>({ kind: "loading" });
  const [exporting, setExporting] = useState<"daily" | "unresolved" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const cutoff = new Date().toISOString();
    void Promise.all([
      fetchDailyReconciliationReport(token, reportDate, controller.signal),
      fetchUnresolvedCaseReport(token, cutoff, controller.signal),
    ])
      .then(([daily, unresolved]) => setState({ kind: "ready", daily, unresolved }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof ApiError ? error.message : "Reports are temporarily unavailable.";
        setState({ kind: "error", message });
      });
    return () => controller.abort();
  }, [refresh, reportDate, token]);

  function selectDate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState({ kind: "loading" });
    if (draftDate === reportDate) {
      setRefresh((value) => value + 1);
    } else {
      setReportDate(draftDate);
    }
  }

  function retryReports() {
    setState({ kind: "loading" });
    setRefresh((value) => value + 1);
  }

  async function exportDaily() {
    setExportError(null);
    setExporting("daily");
    try {
      saveDownload(await downloadDailyReconciliationCsv(token, reportDate));
    } catch (error) {
      setExportError(error instanceof ApiError ? error.message : "CSV export failed.");
    } finally {
      setExporting(null);
    }
  }

  async function exportUnresolved() {
    if (state.kind !== "ready") return;
    setExportError(null);
    setExporting("unresolved");
    try {
      saveDownload(await downloadUnresolvedCasesCsv(token, state.unresolved.cutoff_at));
    } catch (error) {
      setExportError(error instanceof ApiError ? error.message : "CSV export failed.");
    } finally {
      setExporting(null);
    }
  }

  return (
    <section aria-labelledby="reports-heading" className="dashboard report-workspace" id="reports">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">VERIFIED OPERATIONAL OUTPUTS</p>
          <h2 id="reports-heading">Reports and safe exports</h2>
          <p className="dashboard-subtitle">
            UTC-scoped totals are independently recalculated before any report or CSV is released.
          </p>
        </div>
        <form className="report-date-form" onSubmit={selectDate}>
          <label htmlFor="report-date">UTC report date</label>
          <div>
            <input
              id="report-date"
              max={todayUtc()}
              onChange={(event) => setDraftDate(event.target.value)}
              required
              type="date"
              value={draftDate}
            />
            <button className="secondary-button" type="submit">Load date</button>
          </div>
        </form>
      </header>

      {state.kind === "loading" ? (
        <div className="dashboard-state" role="status">
          <span className="loading-mark" aria-hidden="true" />
          <h3>Verifying report totals</h3>
          <p>Comparing row-level Decimal sums with independent database aggregates.</p>
        </div>
      ) : null}

      {state.kind === "error" ? (
        <div className="dashboard-state" role="alert">
          <span className="state-icon">REPORT HELD</span>
          <h3>The report was not released</h3>
          <p>{state.message}</p>
          <button className="secondary-button" onClick={retryReports} type="button">
            Retry verification
          </button>
        </div>
      ) : null}

      {state.kind === "ready" ? (
        <div className="report-grid">
          <article className="dashboard-panel report-panel">
            <div className="panel-heading">
              <div>
                <span className="verified-badge">✓ Independently verified</span>
                <h3>Daily reconciliation summary</h3>
                <p>{state.daily.report_date} UTC · {state.daily.source_account_id}</p>
              </div>
              <button
                className="secondary-button"
                disabled={exporting !== null}
                onClick={() => void exportDaily()}
                type="button"
              >
                {exporting === "daily" ? "Preparing…" : "Export safe CSV"}
              </button>
            </div>

            {state.daily.currency_totals.length === 0 ? (
              <div className="inline-empty">
                <strong>No eligible facts for this UTC date</strong>
                <span>Both independent calculations returned zero rows.</span>
              </div>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Currency</th>
                      <th>Transactions</th>
                      <th>Transaction value</th>
                      <th>Settlements</th>
                      <th>Settlement value</th>
                      <th>Difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.daily.currency_totals.map((item) => (
                      <tr key={item.currency}>
                        <td><strong>{item.currency}</strong></td>
                        <td>{item.transaction_count}</td>
                        <td className="mono-value">{item.transaction_total}</td>
                        <td>{item.settlement_count}</td>
                        <td className="mono-value">{item.settlement_total}</td>
                        <td className="mono-value">{item.difference}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {state.daily.reconciliation_snapshot ? (
              <details className="report-snapshot">
                <summary>
                  Latest reconciliation snapshot · {state.daily.reconciliation_snapshot.result_count} results
                </summary>
                <p>
                  Cutoff {utcLabel(state.daily.reconciliation_snapshot.input_cutoff_at)} · {state.daily.reconciliation_snapshot.algorithm_version}
                </p>
                <ul>
                  {state.daily.reconciliation_snapshot.classifications.map((item) => (
                    <li key={item.classification}>
                      <span>{classificationLabels[item.classification]}</span>
                      <strong>{item.result_count}</strong>
                    </li>
                  ))}
                </ul>
              </details>
            ) : (
              <p className="inline-note">No completed reconciliation snapshot exists before this date cutoff.</p>
            )}
          </article>

          <article className="dashboard-panel report-panel">
            <div className="panel-heading">
              <div>
                <span className="access-mode">CURRENT QUEUE</span>
                <h3>Unresolved cases</h3>
                <p>{state.unresolved.case_count} cases · cutoff {utcLabel(state.unresolved.cutoff_at)}</p>
              </div>
              <button
                className="secondary-button"
                disabled={exporting !== null}
                onClick={() => void exportUnresolved()}
                type="button"
              >
                {exporting === "unresolved" ? "Preparing…" : "Export safe CSV"}
              </button>
            </div>

            {state.unresolved.cases.length === 0 ? (
              <div className="inline-empty">
                <strong>No unresolved cases</strong>
                <span>The current queue is clear at this cutoff.</span>
              </div>
            ) : (
              <ul className="report-case-list">
                {state.unresolved.cases.map((item) => (
                  <li key={item.case_id}>
                    <div>
                      <span className={`priority-tag priority-tag--${item.priority}`}>{item.priority}</span>
                      <strong>Case #{item.case_number} · {item.title}</strong>
                    </div>
                    <p>{item.status.replace("_", " ")} · {item.age_hours}h old · {item.alert_count} alerts</p>
                    <small>{item.owner_display_name ?? "Unassigned"} · {item.rule_codes.join(", ") || "No linked rules"}</small>
                  </li>
                ))}
              </ul>
            )}
          </article>
          {exportError ? <p className="form-error report-export-error" role="alert">{exportError}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
