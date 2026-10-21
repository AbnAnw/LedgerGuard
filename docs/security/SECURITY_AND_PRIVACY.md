# Security and privacy review

## Purpose and scope

This document is the Day 16 security design and review record for LedgerGuard. It covers the
local modular-monolith deployment, its intended Cloud Run boundary, and synthetic demonstration
data. It is not a certification, penetration-test report, or claim of regulatory compliance.

The review protects four primary assets:

1. authentication credentials and revocable sessions;
2. synthetic financial facts and the evidence used to reconcile them;
3. alert, case, report, and append-only audit evidence; and
4. availability of the API, worker, PostgreSQL, Redis, and operational telemetry.

Trust boundaries exist between the browser and API, API and PostgreSQL, API/worker and Redis,
uploaded content and the ingestion parser, the migration identity and runtime database identity,
and local observability endpoints and any future hosted ingress.

## Security contracts

### Request boundary

- Only configured hosts and CORS origins are accepted. Forwarded client-address headers are not
  trusted by the application; a future managed ingress must strip untrusted forwarding headers.
- Every API response receives `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, a restrictive `Permissions-Policy`, and a path-appropriate
  `Content-Security-Policy`. API and authentication responses are not cached.
- Production disables interactive API documentation and emits HSTS under the documented HTTPS
  ingress assumption.
- Requests with a declared or streamed body above the configured boundary fail with HTTP 413
  before domain processing. CSV content remains subject to the stricter ingestion byte limit.
- Redis-backed fixed-window limits apply to API traffic, with a stricter login bucket. Keys use
  an HMAC of the directly connected address rather than storing an address in Redis. A limited
  response is HTTP 429 with retry metadata. Production fails closed with HTTP 503 if the limiter
  is unavailable; development may fail open with a redacted warning.

### Identity and authorization

- Passwords use Argon2id. Opaque bearer tokens are returned once and only keyed digests are
  stored. Sessions expire and can be revoked. Login responses remain intentionally generic.
- The API is authoritative for permissions. UI visibility is not an authorization control.
- Unknown roles receive no permissions. Auditors retain read-only evidence access and cannot
  upload, reconcile, change rules, or mutate cases.
- MFA, password reset, federation, device binding, and central session revocation are not present;
  they remain explicit production risks rather than implied capabilities.

### Database boundary

- A migration service owns schema changes. The API and worker use a separate non-owner login that
  receives only schema usage, sequence usage, and table DML needed by the application.
- The runtime login receives only `SELECT` and `INSERT` on `audit_events`; `UPDATE`, `DELETE`,
  `TRUNCATE`, schema creation, and role administration are not granted. The append-only trigger is
  a second control, not a substitute for privileges.
- Production must inject migration and runtime credentials separately and run migrations as a
  one-shot job. Neither credential belongs in source control, container layers, logs, or URLs
  exported to telemetry.

### Data and telemetry boundary

- This repository and its demonstrations accept synthetic data only. When
  `SYNTHETIC_DATA_ONLY=true`, ingestion and reconciliation source systems must use the
  `synthetic-` prefix. This is a guardrail, not proof that arbitrary uploaded text is fictitious.
- Structured logs recursively redact credential, email, connection, payload, instrument, and
  source-record fields. String sanitization also removes bearer credentials, email-shaped values,
  and URL user information. Logs never replace authoritative audit evidence.
- Metrics use bounded labels and never contain user, account, job, transaction, or source-record
  identifiers. Operational dashboards are loopback-only in the development profile.

## Threat model and findings

| Threat | Existing or repaired controls | Residual risk, owner, and timing |
| --- | --- | --- |
| Credential stuffing and password guessing | Generic failures, constant-work unknown-user check, account lockout, Redis login throttling, Argon2id | NAT-shared clients can affect each other; MFA and federation are Product/Security work before real-user deployment. |
| Session theft | 256-bit opaque tokens, keyed digest storage, expiry, logout revocation, memory-only browser storage, no-store responses | Bearer tokens remain replayable until expiry; TLS and managed edge controls are Deployment work on Day 19. |
| Privilege escalation or insecure direct object reference | Deny-by-default API permissions, account-scoped queries, negative role tests, audit of denials | Administrator user-management workflows and one-administrator concurrency controls need their own feature implementation before production. |
| Malicious CSV/JSON upload | Pydantic validation, UTF-8 CSV parser, fixed fields, decimal/timestamp constraints, record-count cap, body and file byte limits, asynchronous time limits | CSV formula risk is controlled on export, not on arbitrary downstream consumers; antivirus/content-disarm is Deployment/Security work before non-synthetic uploads. |
| SQL, command, template, and spreadsheet injection | SQLAlchemy parameterization, no shell evaluation of input, fixed export fields, spreadsheet-formula neutralization, strict identifiers | Dependency vulnerabilities and future dynamic queries require continued scanning and review; Engineering owns every change. |
| Excessive resource use and queue flooding | Request/login limits, request and record caps, worker timeouts, one-message prefetch, idempotency, bounded retries | Fixed-window/IP limits are not a managed WAF or tenant quota; Day 17 measures load and Day 19 defines edge quotas. |
| Secret exposure | Placeholder rejection in production, `SecretStr`, ignored `.env`/keys/state, value-aware log redaction, tracked-file secret scan, separate DB identities | Local Compose defaults are public demonstration credentials and must never be exposed; Operations owns secret-manager injection and rotation on Day 19. |
| Audit tampering | Append-only database trigger, runtime `SELECT`/`INSERT` only, no mutation API, bounded allowlisted evidence | A database owner can disable controls; privileged database operations need provider audit logs and dual control on Day 19. |
| Telemetry data leakage | Recursive/value-aware redaction, bounded metric labels, sanitized health responses, synthetic failure drills | Third-party collector retention and access are unconfigured; Operations must approve collector tenancy and retention. |
| Supply-chain compromise | Pinned direct dependencies, locked npm graph, Python/npm vulnerability scans, tracked-file secret scan, read-only CI token | Transitive Python resolution is not hash-locked; hash-pinned production builds and signed provenance remain Day 19 work. |
| Cross-origin, host-header, clickjacking, and MIME attacks | Explicit CORS, host allowlist, CSP, frame denial, nosniff, referrer and permission policies | Reverse-proxy host and scheme normalization must be verified in the target environment on Day 19. |
| Accidental real-data use | Synthetic fixtures, `.invalid` users, production-blocked demo seeders, synthetic source guard, contributor rules | Prefix checks cannot identify disguised personal data; repository operators remain accountable for fixture review. |

No open finding from this review is rated critical for the synthetic local demonstration after the
repairs above. The residual production risks are deployment blockers, not accepted assurances.

## Retention and privacy baseline

The following periods are approved only as LedgerGuard's synthetic reference-policy baseline.
A deploying organization must replace them with legal, contractual, and jurisdiction-specific
decisions before processing non-synthetic data.

| Data | Baseline | Disposal boundary |
| --- | ---: | --- |
| Transactions, settlements, reconciliation evidence | 7 years | Delete as one referentially complete evidence set after holds expire. |
| Alerts, cases, comments, case history | 7 years after resolution | A legal hold overrides expiry. |
| Audit events | 7 years | Only a separately privileged, externally audited retention job may delete. |
| Accepted source snapshots | 1 year after batch completion | Retain typed financial facts and evidence for the longer period. |
| Rejected source snapshots | 90 days | Retain non-payload reason codes and aggregate counts. |
| Session records and non-audit security telemetry | 1 year | Authentication actions copied to `audit_events` retain the audit baseline; extend other evidence only for an approved incident or policy requirement. |
| Generated exports | 30 days maximum | Prefer on-demand generation; audit metadata outlives files. |
| Redacted logs and traces | 30 days maximum | Collector access must be operational, not analyst, access. |

No purge automation is added on Day 16. Legal-hold representation, dry-run reporting,
referential-integrity tests, deletion evidence, backups, and restoration behaviour must exist before
the first destructive retention job.

## Verification and acceptance criteria

Day 16 is complete only when automated tests prove:

- secure headers, host validation, declared/streamed size rejection, limit/retry responses, and
  limiter failure policy;
- production configuration rejects disabled throttling, unsafe hosts/origins, placeholder secrets,
  and unrestricted synthetic-data settings;
- log output contains none of the supplied credential, email, connection, or payload canaries;
- the migration/runtime database split grants ordinary DML while denying audit update/delete and
  schema creation to the runtime identity;
- Python and npm dependency scans and the tracked-file secret scan execute in CI;
- all existing permission, duplicate, retry, browser, and integration workflows still pass.
