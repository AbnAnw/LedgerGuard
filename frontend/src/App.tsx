import { type FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  fetchLiveness,
  loginUser,
  logoutUser,
  type AuthUser,
  type LivenessResponse,
} from "./api";
import { Dashboard } from "./Dashboard";
import { FraudMonitor } from "./FraudMonitor";
import "./styles.css";

type ConnectionState =
  | { kind: "checking" }
  | { kind: "online"; health: LivenessResponse }
  | { kind: "offline" };

type AuthState =
  | { kind: "signed_out"; message?: string }
  | { kind: "submitting" }
  | { kind: "signed_in"; token: string; expiresAt: string; user: AuthUser };

const foundation = [
  ["API", "FastAPI", "Request and authorization boundary"],
  ["Database", "PostgreSQL", "Authoritative financial and session data"],
  ["Jobs", "Redis + Celery", "Retryable background processing"],
] as const;

const roleLabels: Record<string, string> = {
  administrator: "Administrator",
  operations_analyst: "Operations analyst",
  auditor: "Auditor",
};

function availableWorkspaces(user: AuthUser) {
  const roles = new Set(user.roles);
  return [
    roles.has("administrator")
      ? { name: "Administration", detail: "Manage users, rules, and configuration", mode: "Manage" }
      : null,
    roles.has("administrator") || roles.has("operations_analyst")
      ? { name: "Operations", detail: "Ingest, reconcile, investigate, and manage cases", mode: "Manage" }
      : null,
    roles.has("administrator") || roles.has("auditor")
      ? { name: "Audit evidence", detail: "Review records, reports, cases, and history", mode: "Read only" }
      : null,
  ].filter((workspace) => workspace !== null);
}

export function App() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "checking" });
  const [auth, setAuth] = useState<AuthState>({ kind: "signed_out" });

  useEffect(() => {
    const controller = new AbortController();
    void fetchLiveness(controller.signal)
      .then((health) => setConnection({ kind: "online", health }))
      .catch(() => {
        if (!controller.signal.aborted) setConnection({ kind: "offline" });
      });
    return () => controller.abort();
  }, []);

  const statusLabel =
    connection.kind === "online"
      ? `API online · v${connection.health.version}`
      : connection.kind === "offline"
        ? "API unavailable"
        : "Checking API";

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const emailValue = form.get("email");
    const passwordValue = form.get("password");
    const email = typeof emailValue === "string" ? emailValue : "";
    const password = typeof passwordValue === "string" ? passwordValue : "";
    setAuth({ kind: "submitting" });
    try {
      const result = await loginUser(email, password);
      setAuth({
        kind: "signed_in",
        token: result.access_token,
        expiresAt: result.expires_at,
        user: result.user,
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The API is unavailable.";
      setAuth({ kind: "signed_out", message });
    }
  }

  async function handleLogout() {
    if (auth.kind !== "signed_in") return;
    const token = auth.token;
    setAuth({ kind: "signed_out" });
    try {
      await logoutUser(token);
    } catch {
      setAuth({
        kind: "signed_out",
        message: "Signed out locally; server sign-out could not be confirmed.",
      });
    }
  }

  return (
    <main>
      <nav aria-label="Primary navigation" className="topbar">
        <a className="brand" href="#top" aria-label="LedgerGuard home">
          <span className="brand-mark" aria-hidden="true">LG</span>
          <span>LedgerGuard</span>
        </a>
        <div className="topbar-actions">
          {auth.kind === "signed_in" ? (
            <>
              <div className="nav-links">
                {auth.user.permissions.includes("reconciliation:read") ? <a href="#dashboard">Dashboard</a> : null}
                {auth.user.permissions.includes("reconciliation:read") ? <a href="#evidence">Evidence</a> : null}
                {auth.user.permissions.includes("alerts:read") ? <a href="#fraud-monitor">Fraud alerts</a> : null}
                {auth.user.roles.includes("administrator") ? <a href="#access-heading">Administration</a> : null}
              </div>
              <button className="text-button" onClick={() => void handleLogout()} type="button">
                Sign out
              </button>
            </>
          ) : null}
          <span className={`service-status service-status--${connection.kind}`} role="status">
            <span className="status-dot" aria-hidden="true" />
            {statusLabel}
          </span>
        </div>
      </nav>

      <section className="hero" id="top">
        <p className="eyebrow">RECONCILIATION CONTROL PLANE</p>
        <h1>Every financial exception deserves an evidence trail.</h1>
        <p className="hero-copy">
          LedgerGuard validates transaction data, prevents duplicate processing, explains
          reconciliation outcomes, and supports auditable investigations.
        </p>
        <div className="notice" role="note">
          <strong>Protected environment</strong>
          <span>Role-based access · synthetic demonstration data only</span>
        </div>
      </section>

      <section aria-labelledby="access-heading" className="access-section">
        {auth.kind === "signed_in" ? (
          <div className="workspace-panel">
            <div className="identity-row">
              <div>
                <p className="eyebrow">AUTHENTICATED WORKSPACE</p>
                <h2 id="access-heading">Welcome, {auth.user.display_name}.</h2>
              </div>
              <div className="identity-meta">
                <strong>{auth.user.roles.map((role) => roleLabels[role] ?? role).join(", ")}</strong>
                <span>{auth.user.email}</span>
                <span>
                  Session expires {new Date(auth.expiresAt).toLocaleString("en-GB", { timeZone: "UTC" })} UTC
                </span>
              </div>
            </div>
            <div className="workspace-grid">
              {availableWorkspaces(auth.user).map((workspace) => (
                <article className="workspace-card" key={workspace.name}>
                  <span className="access-mode">{workspace.mode}</span>
                  <h3>{workspace.name}</h3>
                  <p>{workspace.detail}</p>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <div className="login-layout">
            <div>
              <p className="eyebrow">LEAST-PRIVILEGE ACCESS</p>
              <h2 id="access-heading">Sign in to your assigned workspace.</h2>
              <p className="access-copy">
                Administrator, operations analyst, and auditor views are separated. The API
                independently checks every protected action.
              </p>
            </div>
            <form className="login-card" onSubmit={(event) => void handleLogin(event)}>
              <label htmlFor="email">Email</label>
              <input autoComplete="username" id="email" name="email" required type="email" />
              <label htmlFor="password">Password</label>
              <input autoComplete="current-password" id="password" name="password" required type="password" />
              {auth.kind === "signed_out" && auth.message ? (
                <p className="form-error" role="alert">{auth.message}</p>
              ) : null}
              <button className="primary-button" disabled={auth.kind === "submitting"} type="submit">
                {auth.kind === "submitting" ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </div>
        )}
      </section>

      {auth.kind === "signed_in" && auth.user.permissions.includes("reconciliation:read") ? (
        <Dashboard token={auth.token} user={auth.user} />
      ) : null}

      {auth.kind === "signed_in" && auth.user.permissions.includes("alerts:read") ? (
        <FraudMonitor token={auth.token} user={auth.user} />
      ) : null}

      <section aria-labelledby="foundation-heading" className="foundation">
        <div className="section-heading">
          <p className="eyebrow">SYSTEM FOUNDATION</p>
          <h2 id="foundation-heading">One cohesive platform, clear boundaries.</h2>
        </div>
        <div className="service-grid">
          {foundation.map(([label, technology, purpose], index) => (
            <article className="service-card" key={label}>
              <span className="service-number">0{index + 1}</span>
              <p>{label}</p>
              <h3>{technology}</h3>
              <span>{purpose}</span>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
