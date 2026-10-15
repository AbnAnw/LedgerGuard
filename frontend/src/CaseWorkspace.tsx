import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  assignCase,
  commentOnCase,
  createCase,
  fetchCase,
  fetchCases,
  fetchFraudMonitor,
  transitionCase,
  type AuthUser,
  type CaseFilters,
  type CasePriority,
  type CaseStatus,
  type CaseSummary,
  type FraudAlert,
  type InvestigationCase,
} from "./api";

type WorkspaceState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      cases: CaseSummary[];
      selected: InvestigationCase | null;
      openAlerts: FraudAlert[];
      message?: string;
    };

const nextStatuses: Record<CaseStatus, CaseStatus[]> = {
  open: ["in_review", "escalated"],
  in_review: ["escalated", "resolved"],
  escalated: ["in_review", "resolved"],
  resolved: ["reopened"],
  reopened: ["in_review", "escalated", "resolved"],
};

const titleCase = (value: string) => value.replaceAll("_", " ");

export function CaseWorkspace({ token, user }: { token: string; user: AuthUser }) {
  const [state, setState] = useState<WorkspaceState>({ kind: "loading" });
  const [filters, setFilters] = useState<CaseFilters>({});
  const [busy, setBusy] = useState(false);
  const canWrite = user.permissions.includes("cases:write");

  async function load(activeFilters: CaseFilters = filters, selectedId?: string) {
    try {
      const [cases, monitor] = await Promise.all([
        fetchCases(token, activeFilters),
        fetchFraudMonitor(token),
      ]);
      const wanted = selectedId ?? cases[0]?.id;
      const selected = wanted ? await fetchCase(token, wanted) : null;
      setState({
        kind: "ready",
        cases,
        selected,
        openAlerts: monitor.alerts.filter((alert) => alert.status === "open"),
      });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Case workspace is unavailable.",
      });
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.all([fetchCases(token), fetchFraudMonitor(token)])
      .then(async ([cases, monitor]) => {
        const selected = cases[0] ? await fetchCase(token, cases[0].id) : null;
        if (active) {
          setState({
            kind: "ready",
            cases,
            selected,
            openAlerts: monitor.alerts.filter((alert) => alert.status === "open"),
          });
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            kind: "error",
            message: error instanceof ApiError ? error.message : "Case workspace is unavailable.",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function mutate(action: () => Promise<InvestigationCase>, message: string) {
    setBusy(true);
    try {
      const selected = await action();
      const cases = await fetchCases(token, filters);
      const monitor = await fetchFraudMonitor(token);
      setState({
        kind: "ready",
        cases,
        selected,
        openAlerts: monitor.alerts.filter((alert) => alert.status === "open"),
        message,
      });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "The case change failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function selectCase(caseId: string) {
    if (state.kind !== "ready") return;
    setBusy(true);
    try {
      const selected = await fetchCase(token, caseId);
      setState({ ...state, selected, message: undefined });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Case evidence could not be loaded.",
      });
    } finally {
      setBusy(false);
    }
  }

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const updated: CaseFilters = {};
    const status = form.get("status");
    const priority = form.get("priority");
    const owner = form.get("owner");
    const ruleCode = form.get("rule_code");
    const age = form.get("age");
    if (status) updated.status = status as CaseStatus;
    if (priority) updated.priority = priority as CasePriority;
    if (owner === "mine") updated.owner_user_id = user.id;
    if (owner === "unassigned") updated.unassigned = true;
    if (typeof ruleCode === "string" && ruleCode.trim()) updated.rule_code = ruleCode.trim();
    if (typeof age === "string" && age) updated.min_age_hours = Number(age);
    setFilters(updated);
    setState({ kind: "loading" });
    void load(updated);
  }

  function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.kind !== "ready" || !state.selected) return;
    const form = new FormData(event.currentTarget);
    const comment = form.get("comment");
    if (typeof comment !== "string") return;
    const body = comment;
    const current = state.selected;
    void mutate(
      () => commentOnCase(token, current.id, current.version, body),
      "Comment added to the investigation timeline.",
    );
    event.currentTarget.reset();
  }

  function changeStatus(target: CaseStatus) {
    if (state.kind !== "ready" || !state.selected) return;
    const current = state.selected;
    const isResolution = target === "resolved";
    void mutate(
      () =>
        transitionCase(
          token,
          current,
          target,
          isResolution ? "Investigation completed with stored evidence" : `Case moved to ${target}`,
          isResolution
            ? { code: "confirmed_issue", summary: "Linked alert evidence was reviewed and confirmed." }
            : undefined,
        ),
      `Case moved to ${titleCase(target)}.`,
    );
  }

  return (
    <section aria-labelledby="cases-heading" className="dashboard" id="case-workspace">
      <div className="section-heading dashboard-heading">
        <div>
          <p className="eyebrow">INVESTIGATION QUEUE</p>
          <h2 id="cases-heading">Decisions stay attached to evidence.</h2>
          <p>All timeline times are UTC. Version checks protect concurrent analyst work.</p>
        </div>
        {!canWrite ? <span className="access-mode">Read only</span> : null}
      </div>

      {state.kind === "loading" ? <p role="status">Loading investigation cases…</p> : null}
      {state.kind === "error" ? (
        <div className="form-error" role="alert">
          <p>{state.message}</p>
          <button className="text-button" onClick={() => void load()} type="button">Retry</button>
        </div>
      ) : null}
      {state.kind === "ready" ? (
        <>
          {state.message ? <p className="notice" role="status">{state.message}</p> : null}
          <form className="case-filters" onSubmit={submitFilters}>
            <label>Status<select name="status" defaultValue=""><option value="">All</option>{Object.keys(nextStatuses).map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}</select></label>
            <label>Priority<select name="priority" defaultValue=""><option value="">All</option>{["critical", "high", "medium", "low"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Owner<select name="owner" defaultValue=""><option value="">All</option><option value="mine">Mine</option><option value="unassigned">Unassigned</option></select></label>
            <label>Rule<input name="rule_code" placeholder="velocity_10m" /></label>
            <label>Minimum age<input min="0" name="age" placeholder="hours" type="number" /></label>
            <button className="secondary-button" type="submit">Apply filters</button>
          </form>

          {canWrite && state.openAlerts.length > 0 ? (
            <div className="case-alert-tray">
              <strong>Unclaimed alerts</strong>
              {state.openAlerts.slice(0, 5).map((alert) => (
                <button
                  className="text-button"
                  disabled={busy}
                  key={alert.id}
                  onClick={() => void mutate(
                    () => createCase(token, alert.id, `${alert.rule_code}: ${alert.source_record_id}`, alert.severity),
                    "Case created from alert evidence.",
                  )}
                  type="button"
                >
                  Create case for {alert.source_record_id}
                </button>
              ))}
            </div>
          ) : null}

          {state.cases.length === 0 ? (
            <div className="empty-state"><h3>No cases match</h3><p>Adjust the filters or create a case from an unclaimed alert.</p></div>
          ) : (
            <div className="case-layout">
              <div className="case-list" aria-label="Case queue">
                {state.cases.map((item) => (
                  <button className={state.selected?.id === item.id ? "case-card case-card--active" : "case-card"} disabled={busy} key={item.id} onClick={() => void selectCase(item.id)} type="button">
                    <span>CASE-{item.case_number} · {item.priority}</span>
                    <strong>{item.title}</strong>
                    <small>{titleCase(item.status)} · {item.owner_display_name ?? "Unassigned"} · {item.alert_count} alert(s)</small>
                  </button>
                ))}
              </div>
              {state.selected ? (
                <article className="case-detail">
                  <div className="case-detail-heading">
                    <div><span>CASE-{state.selected.case_number}</span><h3>{state.selected.title}</h3></div>
                    <span className={`classification-badge severity-badge--${state.selected.priority}`}>{titleCase(state.selected.status)}</span>
                  </div>
                  <p>{state.selected.description ?? "No additional description."}</p>
                  <p><strong>Owner:</strong> {state.selected.owner_display_name ?? "Unassigned"}</p>
                  {canWrite ? (
                    <div className="case-actions">
                      <button className="secondary-button" disabled={busy} onClick={() => void mutate(
                        () => assignCase(token, state.selected!.id, state.selected!.version, state.selected!.owner_user_id === user.id ? null : user.id),
                        state.selected!.owner_user_id === user.id ? "Case unassigned." : "Case assigned to you.",
                      )} type="button">{state.selected.owner_user_id === user.id ? "Unassign" : "Assign to me"}</button>
                      {nextStatuses[state.selected.status].map((target) => <button className="secondary-button" disabled={busy} key={target} onClick={() => changeStatus(target)} type="button">{target === "resolved" ? "Resolve confirmed" : titleCase(target)}</button>)}
                    </div>
                  ) : null}
                  <h4>Linked alert evidence</h4>
                  <ul>{state.selected.alerts.map((alert) => <li key={alert.id}><strong>{alert.rule_code}</strong> · {alert.source_record_id} · {alert.reason_code} · {alert.status}</li>)}</ul>
                  <h4>Comments</h4>
                  {state.selected.comments.length === 0 ? <p>No comments yet.</p> : <ol>{state.selected.comments.map((comment) => <li key={comment.id}><strong>{comment.author_display_name}</strong>: {comment.body}</li>)}</ol>}
                  {canWrite ? <form className="comment-form" onSubmit={submitComment}><label htmlFor="case-comment">Add investigation note</label><textarea id="case-comment" maxLength={4000} name="comment" required /><button className="primary-button" disabled={busy} type="submit">Add comment</button></form> : null}
                  <h4>Status history</h4>
                  <ol className="case-history">{state.selected.history.map((entry) => <li key={entry.id}><strong>{titleCase(entry.to_status)}</strong> by {entry.changed_by_display_name}<small>{new Date(entry.changed_at).toLocaleString("en-GB", { timeZone: "UTC" })} UTC · {entry.reason} · {entry.correlation_id.slice(0, 8)}</small></li>)}</ol>
                </article>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
