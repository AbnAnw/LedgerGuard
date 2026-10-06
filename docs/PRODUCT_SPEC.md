# LedgerGuard Product Specification

## Problem statement

Operations teams often receive transaction and settlement data from separate systems. Invalid files, duplicate delivery, ambiguous matches, and unexplained activity create financial and operational risk. LedgerGuard will provide one evidence-preserving workflow from ingestion through reconciliation, alert investigation, case resolution, reporting, and audit review.

## Product outcomes

LedgerGuard should make each accepted or rejected record traceable, each reconciliation result reproducible, each fraud alert explainable, and each investigation reconstructable. It is decision-support software: analysts make final investigation decisions, and no automated output should imply guilt or independently move money.

## Personas and workflows

### Administrator

1. Signs in and reviews system health and security-relevant events.
2. Creates, disables, and assigns least-privilege roles to users.
3. Configures versioned fraud rules and system settings.
4. Reviews configuration changes in the append-only audit history.
5. Cannot erase evidence through the normal application interface.

### Operations analyst

1. Signs in and uploads a transaction or settlement batch, or submits records through the API.
2. Reviews batch validation, accepted and rejected counts, and individual rejection reasons.
3. Starts or observes reconciliation and fraud evaluation without blocking the browser.
4. Prioritises discrepancies and alerts using amount, age, severity, rule, status, and ownership filters.
5. Opens a record to see source fields, matching candidates, applied rule versions, evidence, and reason codes.
6. Creates or updates a case, adds comments, assigns ownership, escalates, resolves, or reopens it under valid transitions.
7. Exports explicitly permitted reports and verifies their scope and generation time.

### Auditor

1. Signs in with read-only access.
2. Searches transactions, batches, reconciliation results, alerts, cases, reports, and audit events.
3. Reconstructs a decision from source ingestion through case outcome using timestamps and correlation IDs.
4. Exports approved read-only reports.
5. Cannot mutate records or trigger processing.

## Functional acceptance criteria

### Ingestion

- CSV upload and JSON API submission use a published, versioned transaction schema.
- Each submission receives a stable batch identifier and processing status.
- Required fields, identifiers, decimal amounts, ISO currency codes, timestamps, and batch metadata are validated deterministically.
- Accepted and rejected source rows remain attributable to their batch and source row; each rejection contains a machine-readable code and human-readable reason.
- A retry with the same idempotency key and unchanged payload returns the original outcome without creating another financial record.
- Reuse of an idempotency key with a conflicting payload is rejected explicitly.
- Batch summaries report source, accepted, rejected, duplicate, and conflicted counts.
- Only administrators and operations analysts may ingest; auditors receive a forbidden response even if they call the API directly.

### Reconciliation

- A versioned run matches eligible transactions and settlements by reference, decimal amount, currency, and documented UTC time window.
- Results distinguish exact match, partial match, missing settlement, duplicate candidate, and unexplained settlement.
- Every result stores the run/version, candidate identifiers, compared values, reason code, and enough evidence to reproduce the classification.
- Running the same reconciliation inputs and configuration produces the same classifications.
- Retrying a run or receiving a duplicate worker delivery does not create duplicate results.
- Summary totals are calculated with decimal arithmetic and reconcile to the underlying records.
- Auditors may read results but cannot start, cancel, or mutate runs.

### Alerts

- Versioned deterministic rules support transaction velocity, unusual amount, repeated failure, duplicate instrument, and suspicious timing scenarios.
- Each alert records the rule version, evaluated inputs, evidence, score or severity, output, creation time, and correlation ID.
- A rule evaluation with the same rule version and evidence is deterministic and idempotent.
- Seeded positive and negative scenarios demonstrate that rules can both alert and decline to alert.
- Analysts can distinguish an alert from a confirmed case outcome; the interface never labels an alert as proven fraud.
- Auditors have read-only access, analysts investigate, and only administrators manage rule definitions.

### Investigations and cases

- An analyst can link alerts, assign an owner, comment, escalate, resolve, and reopen a case.
- State transitions are explicitly defined and invalid transitions are rejected by the API.
- Each change records actor, prior and new state, timestamp, reason where required, and correlation ID.
- Case searches can filter by owner, priority, status, rule, and age.
- Concurrent updates use conflict detection so one analyst cannot silently overwrite another analyst's change.
- Comments and history cannot be edited or deleted through the normal interface.
- Auditors can reconstruct the lifecycle but cannot alter it.

### Reports and exports

- Daily reconciliation summaries include source totals, matched and unresolved counts and values, validation failures, and match rate, with scope and UTC cutoff shown.
- Unresolved-case reports include only authorised, explicit fields and identify generation time and filters.
- Exported CSV values are protected against spreadsheet formula injection.
- Report totals are independently recalculated from stored records and fail closed when verification differs.
- Every report generation and export is audited with actor, filters, result, and correlation ID.
- Tests prove that role and tenant/scope boundaries (if introduced) cannot be bypassed by changing request parameters.

## Cross-cutting acceptance criteria

- Monetary values never pass through binary floating point in application or persistence layers.
- PostgreSQL constraints reinforce identifiers, uniqueness, lifecycle values, and referential integrity.
- All persisted and API timestamps are timezone-aware UTC; displayed local time is labelled with its time zone.
- Structured logs include request or job correlation IDs and exclude credentials, tokens, and raw sensitive payloads.
- Critical paths cover success, validation failure, forbidden access, duplicate delivery, retry, and partial-failure behaviour.
- Synthetic fixtures are clearly labelled and contain no real financial or personal information.

## Scope

### Included in version 1

- Synthetic transaction and settlement ingestion through CSV and JSON
- Validation, duplicate prevention, and data-quality summaries
- Versioned deterministic reconciliation and fraud rules
- Role-based analyst interface and API
- Cases, comments, status history, evidence, and audit history
- Operational and reconciliation reports with safe CSV export
- Background processing, observability, testing, security review, and resilience measurement
- Optional evidence-grounded AI explanations with deterministic fallback and abstention
- Repeatable local operation and GCP Cloud Run deployment documentation

### Excluded from version 1

- Movement, settlement, refund, or authorisation of real funds
- Direct connections to banks, card networks, payment processors, or identity providers
- Production use of real personal, card, bank-account, or merchant data
- Automated accusation, account suspension, regulatory filing, or final fraud determination
- General-purpose ledger/accounting, tax, chargeback, or sanctions-screening functions
- Multi-region active-active deployment and formal regulatory certification
- Native mobile applications and public customer-facing workflows

## Success metrics and measurement plan

Targets are engineering acceptance targets, not measured achievements. Day 17 will publish observed results and test conditions.

| Area | Initial target | Measurement |
| --- | --- | --- |
| Determinism | 100% identical outcomes for repeated seeded reconciliation and rule scenarios | Hash or compare results across repeated automated runs |
| Duplicate safety | 0 duplicate financial records across retry and duplicate-delivery tests | Database counts and uniqueness assertions |
| Explainability | 100% of reconciliation outcomes and alerts have a reason code and evidence reference | Database invariant/integration test |
| Authorization | 100% of tested forbidden role/action combinations denied by the API | Permission matrix tests |
| Data integrity | Report totals equal independent database calculations for all fixtures | Independent query assertions |
| Reliability | Critical user journeys pass in CI from a clean checkout | CI test results |
| Batch scale | Process a synthetic batch of at least 10,000 transactions | Day 17 benchmark with environment recorded |
| Performance | Publish measured throughput plus p50/p95 API and worker timing; no target invented before baseline | Reproducible Day 17 benchmark |
| Investigation usability | Analyst can identify the seeded highest-priority discrepancy in the scripted demo | Playwright journey and Day 20 demo |
| Auditability | Seeded decision trace reconstructable from batch to case outcome | Auditor end-to-end test |

## Risks and mitigations

| Risk | Impact | Planned mitigation |
| --- | --- | --- |
| Incorrect or ambiguous matching | False resolution or operational loss | Conservative classifications, versioned algorithm, candidate evidence, deterministic fixtures, manual review |
| Duplicate or reordered delivery | Double-counted records/results | Idempotency keys, source identifiers, payload fingerprints, database uniqueness, retry tests |
| Decimal or currency mistakes | Incorrect totals | Decimal types, fixed precision, explicit currency, database checks, independent totals |
| Privilege escalation | Unauthorised access or mutation | API-enforced RBAC, deny-by-default matrix, permission tests, audit events |
| Malicious or oversized uploads | Resource exhaustion or injection | File/type/row limits, streaming parsing, formula-safe exports, rate limits, isolated workers |
| Sensitive data in logs/exports | Privacy and secret exposure | Synthetic-only policy, allowlisted export fields, redaction, security review, repository scan |
| Audit history tampering | Loss of evidentiary trust | Append-only application interface, constrained DB permissions, immutable event schema and monitoring |
| Rule drift or false positives | Alert fatigue and inconsistent decisions | Versioned rules, evidence, replayable evaluation set, thresholds based on measured fixtures |
| Worker failure and partial processing | Stalled or inconsistent jobs | Explicit states, transactions, retries, idempotent tasks, timeouts, dead-letter/failure visibility |
| AI explanation hallucination | Misleading analysts | Evidence-only provider contract, citations to stored fields, deterministic fallback, abstention tests |
| Cloud dependency coupling | Local development or portability failure | Adapters and configuration boundaries; Docker Compose remains the local reference |
| Scope growth | Delayed reliable core | Daily completion gates and documented exclusions |

## Assumptions and open decisions

- Version 1 is a single-organisation system; a tenant boundary is not assumed without an explicit product decision.
- Base currency conversion is out of scope. Values in different currencies are never summed as if equivalent.
- Retention periods and deletion/legal-hold policy require an owner decision during the data-model and security work; evidence will not be silently deleted meanwhile.
- Thresholds for fraud rules are demonstration configuration, not validated financial-risk policy.
- Authentication starts as locally managed demonstration users, while the boundary should permit a future identity-provider adapter.
