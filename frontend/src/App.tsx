import { useEffect, useState } from "react";

import { fetchLiveness, type LivenessResponse } from "./api";
import "./styles.css";

type ConnectionState =
  | { kind: "checking" }
  | { kind: "online"; health: LivenessResponse }
  | { kind: "offline" };

const foundation = [
  ["API", "FastAPI", "Request and domain boundary"],
  ["Database", "PostgreSQL", "Authoritative financial and audit data"],
  ["Jobs", "Redis + Celery", "Retryable background processing"],
] as const;

export function App() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "checking" });

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

  return (
    <main>
      <nav aria-label="Primary navigation" className="topbar">
        <a className="brand" href="#top" aria-label="LedgerGuard home">
          <span className="brand-mark" aria-hidden="true">LG</span>
          <span>LedgerGuard</span>
        </a>
        <span className={`service-status service-status--${connection.kind}`} role="status">
          <span className="status-dot" aria-hidden="true" />
          {statusLabel}
        </span>
      </nav>

      <section className="hero" id="top">
        <p className="eyebrow">RECONCILIATION CONTROL PLANE</p>
        <h1>Every financial exception deserves an evidence trail.</h1>
        <p className="hero-copy">
          LedgerGuard is being built to validate transaction data, prevent duplicate processing,
          explain reconciliation outcomes, and support auditable investigations.
        </p>
        <div className="notice" role="note">
          <strong>Foundation environment</strong>
          <span>Day 3 platform shell · synthetic demonstration data only</span>
        </div>
      </section>

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
