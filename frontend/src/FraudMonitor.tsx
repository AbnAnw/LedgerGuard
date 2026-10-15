import { useEffect, useState } from "react";

import {
  ApiError,
  fetchFraudMonitor,
  runFraudEvaluation,
  type AuthUser,
  type FraudAlert,
  type FraudRule,
} from "./api";

type MonitorState =
  | { kind: "loading" }
  | { kind: "ready"; rules: FraudRule[]; alerts: FraudAlert[]; message?: string }
  | { kind: "error"; message: string };

export function FraudMonitor({ token, user }: { token: string; user: AuthUser }) {
  const [state, setState] = useState<MonitorState>({ kind: "loading" });
  const [running, setRunning] = useState(false);
  const canEvaluate = user.permissions.includes("alerts:write");
  const canManageRules = user.permissions.includes("rules:manage");

  async function reload(signal?: AbortSignal) {
    try {
      const data = await fetchFraudMonitor(token, signal);
      setState({ kind: "ready", ...data });
    } catch (error) {
      if (signal?.aborted) return;
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Fraud monitor is unavailable.",
      });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void fetchFraudMonitor(token, controller.signal)
      .then((data) => setState({ kind: "ready", ...data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message: error instanceof ApiError ? error.message : "Fraud monitor is unavailable.",
        });
      });
    return () => controller.abort();
  }, [token]);

  async function evaluate() {
    setRunning(true);
    try {
      const result = await runFraudEvaluation(token);
      const data = await fetchFraudMonitor(token);
      setState({
        kind: "ready",
        ...data,
        message: `${result.created_count} new alert${result.created_count === 1 ? "" : "s"}; ${result.replayed_count} existing alert${result.replayed_count === 1 ? "" : "s"}.`,
      });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Fraud evaluation failed.",
      });
    } finally {
      setRunning(false);
    }
  }

  return (
    <section aria-labelledby="fraud-heading" className="dashboard" id="fraud-monitor">
      <div className="section-heading dashboard-heading">
        <div>
          <p className="eyebrow">DETERMINISTIC FRAUD MONITOR</p>
          <h2 id="fraud-heading">Every alert carries its evidence.</h2>
          <p>Times are shown in UTC. Scores are triage signals, not probabilities.</p>
        </div>
        {canEvaluate ? (
          <button className="primary-button" disabled={running} onClick={() => void evaluate()} type="button">
            {running ? "Evaluating…" : "Evaluate synthetic account"}
          </button>
        ) : (
          <span className="access-mode">Read only</span>
        )}
      </div>

      {state.kind === "loading" ? <p role="status">Loading fraud evidence…</p> : null}
      {state.kind === "error" ? (
        <div className="form-error" role="alert">
          <p>{state.message}</p>
          <button className="text-button" onClick={() => void reload()} type="button">Retry</button>
        </div>
      ) : null}
      {state.kind === "ready" ? (
        <>
          {state.message ? <p className="notice" role="status">{state.message}</p> : null}
          <div className="metric-grid">
            <article className="metric-card"><span>Active rules</span><strong>{state.rules.flatMap((item) => item.versions).filter((item) => item.status === "active").length}</strong></article>
            <article className="metric-card"><span>Open evidence alerts</span><strong>{state.alerts.filter((item) => item.status === "open").length}</strong></article>
            <article className="metric-card"><span>Rule access</span><strong>{canManageRules ? "Manage" : "Read only"}</strong></article>
          </div>
          {state.alerts.length === 0 ? (
            <div className="empty-state"><h3>No alerts yet</h3><p>No active rule has produced stored evidence for the synthetic scenario.</p></div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Severity</th><th>Rule</th><th>Transaction</th><th>Score</th><th>Reason</th><th>Evidence</th></tr></thead>
                <tbody>
                  {state.alerts.map((alert) => (
                    <tr key={alert.id}>
                      <td><span className={`classification-badge severity-badge--${alert.severity}`}>{alert.severity}</span></td>
                      <td>{alert.rule_code} v{alert.rule_version_number}</td>
                      <td>{alert.source_record_id}</td>
                      <td>{alert.score}</td>
                      <td>{alert.reason_code}</td>
                      <td><code>{alert.evidence_sha256.slice(0, 12)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
