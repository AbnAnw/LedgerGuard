# Authentication and Access Control

## Security boundary

FastAPI is the authorization boundary. The React interface hides unavailable workspaces for usability, but every protected endpoint independently authenticates the session and checks a named permission. Roles not present in the permission map receive no permissions.

## Authentication design

- Passwords use Argon2id with a 64 MiB memory cost, three iterations, four lanes, a 16-byte random salt, and a 32-byte hash. Password values and hashes are never returned by the API.
- Login failures use the same generic response for unknown users, bad passwords, disabled accounts, and locked accounts. An unknown account still performs an Argon2 verification to reduce timing differences.
- Five consecutive failures lock a user for 15 minutes by default. Both values are validated configuration.
- Redis applies a stricter client-address bucket to login requests before credential parsing. The
  bucket key stores an HMAC rather than the connected address, ignores untrusted forwarded-address
  headers, and fails closed in production if the limiter is unavailable.
- A successful login returns a 256-bit URL-safe opaque bearer token. PostgreSQL stores only an HMAC-SHA-256 digest keyed by `AUTH_SECRET_KEY`.
- Sessions expire after 30 minutes by default. Logout revokes the current session in PostgreSQL. Expired, revoked, disabled-user, and locked-user sessions fail closed.
- The interface keeps the bearer token only in React memory, not browser persistent storage. Refreshing the page therefore requires another login.

## Permission matrix

| Capability | Administrator | Operations analyst | Auditor |
| --- | :---: | :---: | :---: |
| Manage users, rules, and configuration | Manage | Denied | Denied |
| Ingest transaction or settlement data | Manage | Manage | Denied |
| Read transactions and reconciliation evidence | Read | Read | Read |
| Run or review reconciliation | Manage | Manage | Read only |
| Review alerts and cases | Manage | Manage | Read only |
| Modify alerts and cases | Manage | Manage | Denied |
| Read reports | Read | Read | Read |
| Read audit history | Read | Denied | Read only |

The Day 4 access-check endpoints exercise representative boundaries: administration requires `users:manage`, operations requires `ingestion:write`, and audit requires `audit:read`.

## Synthetic demonstration users

`ledgerguard-seed` creates three `.invalid` users and one active role grant per user:

- `admin@ledgerguard.invalid` — administrator
- `analyst@ledgerguard.invalid` — operations analyst
- `auditor@ledgerguard.invalid` — auditor

Docker Compose supplies a documented local-only password unless `DEMO_USER_PASSWORD` is overridden. The seed command refuses to run in production mode. These identities and all repository data are synthetic.

## Residual authentication risks

Authentication and authorization events are stored in append-only audit history, while passwords,
tokens, and unrestricted payloads are excluded. MFA, password reset, external identity-provider
integration, device binding, and centrally managed secret rotation remain intentionally absent.
They are production blockers for real-user deployment and are tracked in the
[security and privacy review](SECURITY_AND_PRIVACY.md), not implied capabilities.
