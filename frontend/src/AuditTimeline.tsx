import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  fetchAuditEvents,
  fetchCaseAuditTrail,
  type AuditEvent,
  type AuthUser,
} from "./api";

type AuditState =
  | { kind: "loading" }
  | { kind: "ready"; events: AuditEvent[]; context?: string }
  | { kind: "error"; message: string };

export function AuditTimeline({ token, user }: { token: string; user: AuthUser }) {
  const [state, setState] = useState<AuditState>({ kind: "loading" });

  async function load() {
    try {
      setState({ kind: "loading" });
      setState({ kind: "ready", events: await fetchAuditEvents(token) });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Audit history is unavailable.",
      });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void fetchAuditEvents(token, {}, controller.signal)
      .then((events) => setState({ kind: "ready", events }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            kind: "error",
            message: error instanceof ApiError ? error.message : "Audit history is unavailable.",
          });
        }
      });
    return () => controller.abort();
  }, [token]);

  async function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const action = form.get("action");
    const targetType = form.get("target_type");
    const correlationId = form.get("correlation_id");
    setState({ kind: "loading" });
    try {
      const events = await fetchAuditEvents(token, {
        action: typeof action === "string" && action ? action : undefined,
        target_type: typeof targetType === "string" && targetType ? targetType : undefined,
        correlation_id:
          typeof correlationId === "string" && correlationId ? correlationId : undefined,
      });
      setState({ kind: "ready", events });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Audit filter failed.",
      });
    }
  }

  async function reconstruct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("case_id");
    if (typeof value !== "string" || !value) return;
    setState({ kind: "loading" });
    try {
      const trail = await fetchCaseAuditTrail(token, value);
      setState({
        kind: "ready",
        events: trail.events,
        context: `${trail.transaction_ids.length} transaction(s), ${trail.alert_ids.length} alert(s), case ${trail.case_id}`,
      });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Case reconstruction failed.",
      });
    }
  }

  return (
    <section aria-labelledby="audit-heading" className="dashboard" id="audit-timeline">
      <div className="section-heading dashboard-heading">
        <div>
          <p className="eyebrow">APPEND-ONLY AUDIT EVIDENCE</p>
          <h2 id="audit-heading">Reconstruct every material decision.</h2>
          <p>Database sequence controls ordering. Displayed timestamps are UTC.</p>
        </div>
        <span className="access-mode">{user.roles.includes("auditor") ? "Auditor" : "Administrator"}</span>
      </div>
      <div className="audit-controls">
        <form className="case-filters" onSubmit={(event) => void filter(event)}>
          <label>Action<input name="action" placeholder="case.transitioned" /></label>
          <label>Target type<input name="target_type" placeholder="case" /></label>
          <label>Correlation ID<input name="correlation_id" placeholder="UUID" /></label>
          <button className="secondary-button" type="submit">Filter history</button>
        </form>
        <form className="audit-case-form" onSubmit={(event) => void reconstruct(event)}>
          <label>Case decision trail<input name="case_id" placeholder="Case UUID" required /></label>
          <button className="secondary-button" type="submit">Reconstruct case</button>
        </form>
      </div>
      {state.kind === "loading" ? <p role="status">Loading append-only history…</p> : null}
      {state.kind === "error" ? <div className="form-error" role="alert"><p>{state.message}</p><button className="text-button" onClick={() => void load()} type="button">Retry</button></div> : null}
      {state.kind === "ready" ? (
        <>
          {state.context ? <p className="notice">{state.context}</p> : null}
          {state.events.length === 0 ? <div className="empty-state"><h3>No audit events match</h3><p>Change the filters or perform a synthetic workflow.</p></div> : (
            <ol className="audit-list">
              {state.events.map((item) => (
                <li key={item.id}>
                  <span>#{item.sequence_number} · {item.result}</span>
                  <strong>{item.action}</strong>
                  <p>{item.actor_display_name ?? item.actor_type} → {item.target_type}{item.target_id ? ` ${item.target_id}` : ""}</p>
                  <small>{new Date(item.occurred_at).toLocaleString("en-GB", { timeZone: "UTC" })} UTC · correlation {item.correlation_id}</small>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : null}
    </section>
  );
}
