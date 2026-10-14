import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createReconciliationRun,
  fetchDashboard,
  fetchBackgroundJob,
  type AuthUser,
  type BackgroundJob,
  type DashboardOverview,
  type ReconciliationClassification,
  type ReconciliationResult,
} from "./api";
import { absoluteMoney, compareMoney, formatMoney, maximumMoney } from "./money";

type DashboardState =
  | { kind: "loading" }
  | { kind: "ready"; data: DashboardOverview }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

type RunState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "job"; job: BackgroundJob }
  | { kind: "error"; message: string }
  | { kind: "success"; message: string };

const classificationLabels: Record<ReconciliationClassification, string> = {
  exact_match: "Exact match",
  partial_match: "Partial match",
  missing_settlement: "Missing settlement",
  duplicate_candidate: "Duplicate candidate",
  unexplained_settlement: "Unexplained settlement",
};

function resultSearchText(result: ReconciliationResult): string {
  return [
    result.classification,
    result.reason_code,
    ...result.transactions.flatMap((item) => [item.source_record_id, item.source_reference]),
    ...result.settlements.flatMap((item) => [item.source_record_id, item.source_reference]),
  ]
    .join(" ")
    .toLowerCase();
}

function exposure(result: ReconciliationResult): string {
  return maximumMoney(result.transaction_total, result.settlement_total);
}

function defaultPriority(left: ReconciliationResult, right: ReconciliationResult): number {
  const leftExact = left.classification === "exact_match";
  const rightExact = right.classification === "exact_match";
  if (leftExact !== rightExact) return leftExact ? 1 : -1;
  const byExposure = compareMoney(exposure(right), exposure(left));
  if (byExposure !== 0) return byExposure;
  const byClassification = left.classification.localeCompare(right.classification);
  return byClassification || left.id.localeCompare(right.id);
}

function MetricCard({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{note}</p>
    </article>
  );
}

function EmptyDashboard({ canRun }: { canRun: boolean }) {
  return (
    <section className="dashboard-state dashboard-state--empty" aria-labelledby="empty-heading">
      <span className="state-icon" aria-hidden="true">00</span>
      <h3 id="empty-heading">No completed reconciliation run yet.</h3>
      <p>
        {canRun
          ? "Start reconciliation to create the first evidence-backed dashboard snapshot."
          : "An operations analyst must complete a reconciliation run before evidence appears here."}
      </p>
    </section>
  );
}

function EvidenceDetails({ result }: { result: ReconciliationResult }) {
  const facts = [
    ...result.transactions.map((item) => ({ ...item, kind: "Transaction" as const })),
    ...result.settlements.map((item) => ({ ...item, kind: "Settlement" as const })),
  ];
  return (
    <aside className="evidence-panel" aria-labelledby="evidence-heading" id="evidence-detail">
      <div className="evidence-heading-row">
        <div>
          <p className="eyebrow">DECISION EVIDENCE</p>
          <h3 id="evidence-heading">{classificationLabels[result.classification]}</h3>
        </div>
        <span className={`classification-badge classification-badge--${result.classification}`}>
          {result.reason_code.replaceAll("_", " ")}
        </span>
      </div>
      <dl className="evidence-summary">
        <div><dt>Transaction total</dt><dd>{formatMoney(result.transaction_total, result.currency)}</dd></div>
        <div><dt>Settlement total</dt><dd>{formatMoney(result.settlement_total, result.currency)}</dd></div>
        <div><dt>Difference</dt><dd>{formatMoney(result.difference_amount, result.currency)}</dd></div>
        <div><dt>Evidence digest</dt><dd className="mono-value">{result.evidence_sha256}</dd></div>
      </dl>
      <div className="fact-list">
        {facts.map((item) => (
          <article className="fact-card" key={`${item.kind}-${item.id}`}>
            <span>{item.kind} · {item.item_role}</span>
            <strong>{item.source_reference}</strong>
            <p>{item.source_record_id}</p>
            <p>{formatMoney(item.amount, item.currency)}</p>
            <time dateTime={item.occurred_at ?? item.settled_at ?? undefined}>
              {new Date(item.occurred_at ?? item.settled_at ?? "").toLocaleString("en-GB", {
                timeZone: "UTC",
              })} UTC
            </time>
          </article>
        ))}
      </div>
      <details className="raw-evidence">
        <summary>View canonical comparison evidence</summary>
        <pre>{JSON.stringify(result.evidence, null, 2)}</pre>
      </details>
    </aside>
  );
}

export function Dashboard({ token, user }: { token: string; user: AuthUser }) {
  const [state, setState] = useState<DashboardState>({ kind: "loading" });
  const [search, setSearch] = useState("");
  const [classification, setClassification] = useState<"all" | ReconciliationClassification>(
    "all",
  );
  const [sort, setSort] = useState<"priority" | "difference" | "classification">("priority");
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [windowHours, setWindowHours] = useState("72");
  const [runState, setRunState] = useState<RunState>({ kind: "idle" });
  const canRun = user.permissions.includes("reconciliation:write");
  const isAuditor = user.roles.includes("auditor") && !canRun;

  const fetchData = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await fetchDashboard(token, signal);
        setState({ kind: "ready", data });
      } catch (error) {
        if (signal?.aborted) return;
        if (error instanceof ApiError && error.status === 403) {
          setState({ kind: "forbidden" });
        } else {
          setState({
            kind: "error",
            message: error instanceof ApiError ? error.message : "Dashboard data could not be loaded.",
          });
        }
      }
    },
    [token],
  );

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    await fetchData();
  }, [fetchData]);

  useEffect(() => {
    const controller = new AbortController();
    fetchDashboard(token, controller.signal)
      .then((data) => setState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 403) {
          setState({ kind: "forbidden" });
        } else {
          setState({
            kind: "error",
            message:
              error instanceof ApiError ? error.message : "Dashboard data could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [token]);

  const results = useMemo(
    () => (state.kind === "ready" ? (state.data.latest_run?.results ?? []) : []),
    [state],
  );
  const filteredResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    return [...results]
      .filter((result) => classification === "all" || result.classification === classification)
      .filter((result) => !query || resultSearchText(result).includes(query))
      .sort((left, right) => {
        if (sort === "classification") {
          return left.classification.localeCompare(right.classification) || left.id.localeCompare(right.id);
        }
        if (sort === "difference") {
          return (
            compareMoney(absoluteMoney(right.difference_amount), absoluteMoney(left.difference_amount)) ||
            left.id.localeCompare(right.id)
          );
        }
        return defaultPriority(left, right);
      });
  }, [classification, results, search, sort]);
  const selectedResult =
    filteredResults.find((result) => result.id === selectedResultId) ?? filteredResults[0] ?? null;

  async function handleRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedWindow = Number(windowHours);
    if (!Number.isInteger(parsedWindow) || parsedWindow < 1 || parsedWindow > 168) {
      setRunState({ kind: "error", message: "Match window must be a whole number from 1 to 168." });
      return;
    }
    setRunState({ kind: "submitting" });
    try {
      const job = await createReconciliationRun(token, parsedWindow);
      setRunState({ kind: "job", job });
    } catch (error) {
      setRunState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Reconciliation could not be completed.",
      });
    }
  }

  async function handleRefreshJob(jobId: string) {
    try {
      const job = await fetchBackgroundJob(token, jobId);
      if (job.status === "succeeded") {
        setRunState({ kind: "success", message: "Background reconciliation completed." });
        await load();
      } else if (job.status === "failed" || job.status === "cancelled") {
        setRunState({
          kind: "error",
          message: job.failure_detail ?? job.status_message ?? `Job ${job.status}.`,
        });
      } else {
        setRunState({ kind: "job", job });
      }
    } catch (error) {
      setRunState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Job status could not be loaded.",
      });
    }
  }

  if (state.kind === "loading") {
    return (
      <section className="dashboard-state" id="dashboard" aria-live="polite" aria-busy="true">
        <span className="loading-mark" aria-hidden="true" />
        <h2>Loading reconciliation workspace…</h2>
        <p>Retrieving stored financial evidence and batch quality.</p>
      </section>
    );
  }
  if (state.kind === "forbidden") {
    return (
      <section className="dashboard-state" id="dashboard" role="alert">
        <h2>Dashboard access is not assigned.</h2>
        <p>Your current role does not have permission to read transaction and reconciliation evidence.</p>
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="dashboard-state" id="dashboard" role="alert">
        <h2>Dashboard unavailable.</h2>
        <p>{state.message}</p>
        <button className="secondary-button" onClick={() => void load()} type="button">Try again</button>
      </section>
    );
  }

  const { data } = state;
  return (
    <section className="dashboard" id="dashboard" aria-labelledby="dashboard-heading">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">{isAuditor ? "READ-ONLY EVIDENCE" : "OPERATIONS OVERVIEW"}</p>
          <h2 id="dashboard-heading">Reconciliation workspace</h2>
          <p>{data.display_name} · {data.source_account_id}</p>
        </div>
        {isAuditor ? <span className="read-only-badge">Auditor · read only</span> : null}
        {canRun ? (
          <form className="run-controls" onSubmit={(event) => void handleRun(event)}>
            <label htmlFor="window-hours">Match window</label>
            <div>
              <input
                id="window-hours"
                inputMode="numeric"
                min="1"
                max="168"
                onChange={(event) => setWindowHours(event.target.value)}
                value={windowHours}
              />
              <span>hours</span>
              <button
                className="primary-button"
                disabled={runState.kind === "submitting" || runState.kind === "job"}
                type="submit"
              >
                {runState.kind === "submitting" ? "Queueing…" : "Run reconciliation"}
              </button>
            </div>
            {runState.kind === "error" ? <p className="form-error" role="alert">{runState.message}</p> : null}
            {runState.kind === "success" ? <p className="form-success" role="status">{runState.message}</p> : null}
            {runState.kind === "job" ? (
              <div className="job-progress" role="status">
                <span>{runState.job.status_message ?? `Job ${runState.job.status}`}</span>
                <progress max="100" value={runState.job.progress_percent}>
                  {runState.job.progress_percent}%
                </progress>
                <small>
                  {runState.job.progress_percent}% · attempt {runState.job.attempt_count} of{" "}
                  {runState.job.max_attempts}
                </small>
                <button
                  className="row-action"
                  onClick={() => void handleRefreshJob(runState.job.job_id)}
                  type="button"
                >
                  Refresh status
                </button>
              </div>
            ) : null}
          </form>
        ) : null}
      </header>

      <div className="metric-grid" aria-label="Reconciliation summary">
        <MetricCard
          label="Transaction value"
          value={formatMoney(data.metrics.transaction_value, data.currency)}
          note={`${data.metrics.transaction_count} eligible transactions`}
        />
        <MetricCard
          label="Exact matched value"
          value={formatMoney(data.metrics.exact_matched_value, data.currency)}
          note="Conclusive one-to-one matches"
        />
        <MetricCard
          label="Unresolved value"
          value={formatMoney(data.metrics.unresolved_value, data.currency)}
          note="Review exposure across non-exact results"
        />
        <MetricCard
          label="Match rate"
          value={`${data.metrics.match_rate_percent}%`}
          note={`${data.metrics.validation_failure_count} validation failures`}
        />
      </div>

      {data.latest_run === null ? (
        <EmptyDashboard canRun={canRun} />
      ) : (
        <>
          <section className="batch-section" id="batches" aria-labelledby="batch-heading">
            <div className="panel-heading">
              <div><p className="eyebrow">INGESTION QUALITY</p><h3 id="batch-heading">Related batches</h3></div>
              <span>{data.batches.length} shown</span>
            </div>
            {data.batches.length ? (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Kind</th><th>Status</th><th>Accepted</th><th>Rejected</th><th>Duplicate</th><th>Conflict</th><th>Finished UTC</th></tr></thead>
                  <tbody>
                    {data.batches.map((batch) => (
                      <tr key={batch.id}>
                        <td>{batch.record_kind}</td>
                        <td><span className={`status-pill status-pill--${batch.status}`}>{batch.status.replaceAll("_", " ")}</span></td>
                        <td>{batch.accepted_count}</td><td>{batch.rejected_count}</td><td>{batch.duplicate_count}</td><td>{batch.conflict_count}</td>
                        <td>{batch.finished_at ? `${new Date(batch.finished_at).toLocaleString("en-GB", { timeZone: "UTC" })} UTC` : "In progress"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="inline-empty">No related ingestion batches were found.</p>}
          </section>

          <section className="results-section" id="evidence" aria-labelledby="results-heading">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">PRIORITISED EXCEPTIONS</p>
                <h3 id="results-heading">Reconciliation results</h3>
              </div>
              <span>Run cutoff {new Date(data.latest_run.input_cutoff_at).toLocaleString("en-GB", { timeZone: "UTC" })} UTC</span>
            </div>
            <div className="filter-bar" aria-label="Result filters">
              <label>Search<input type="search" placeholder="Reference, source ID, reason…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
              <label>Classification<select value={classification} onChange={(event) => setClassification(event.target.value as "all" | ReconciliationClassification)}><option value="all">All outcomes</option>{Object.entries(classificationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label>Sort<select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="priority">Review priority</option><option value="difference">Largest difference</option><option value="classification">Classification</option></select></label>
            </div>
            {filteredResults.length ? (
              <div className="results-layout">
                <div className="table-scroll">
                  <table className="results-table">
                    <thead><tr><th>Priority</th><th>Outcome</th><th>Reference</th><th>Transaction</th><th>Settlement</th><th>Difference</th><th><span className="sr-only">Action</span></th></tr></thead>
                    <tbody>
                      {filteredResults.map((result, index) => {
                        const reference = result.transactions[0]?.source_reference ?? result.settlements[0]?.source_reference ?? "—";
                        return (
                          <tr className={selectedResult?.id === result.id ? "is-selected" : undefined} key={result.id}>
                            <td>{result.classification === "exact_match" ? "Matched" : `P${String(index + 1).padStart(2, "0")}`}</td>
                            <td><span className={`classification-badge classification-badge--${result.classification}`}>{classificationLabels[result.classification]}</span></td>
                            <td className="mono-value">{reference}</td>
                            <td>{formatMoney(result.transaction_total, result.currency)}</td>
                            <td>{formatMoney(result.settlement_total, result.currency)}</td>
                            <td>{formatMoney(result.difference_amount, result.currency)}</td>
                            <td><button className="row-action" aria-controls="evidence-detail" onClick={() => setSelectedResultId(result.id)} type="button">Review</button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {selectedResult ? <EvidenceDetails result={selectedResult} /> : null}
              </div>
            ) : (
              <div className="inline-empty" role="status">
                <strong>No results match these filters.</strong>
                <span>Clear the search or choose another classification.</span>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  );
}
