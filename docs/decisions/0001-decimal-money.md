# ADR-0001: Decimal-safe monetary representation

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decision owners:** LedgerGuard engineering

## Context

LedgerGuard compares, allocates, sums, and reports monetary values. Binary floating-point types cannot represent many decimal fractions exactly and can create inconsistent matches or totals. Currency scale also varies, and values in different currencies are not interchangeable.

## Decision

- Persist monetary amounts as PostgreSQL `NUMERIC(20,6)`.
- Use Python `Decimal` constructed from strings, never from `float`.
- Exchange money in JSON as canonical decimal strings plus a separate uppercase ISO 4217 currency code.
- Keep monetary values as strings in TypeScript unless a calculation is unavoidable; then use one reviewed arbitrary-precision decimal library.
- Store positive magnitudes for transactions/settlements and model economic direction separately.
- Validate currency-specific allowed scale in versioned application reference data; database checks enforce positive bounds and currency shape.
- Never sum or compare values across currencies without an explicit, versioned conversion input. Currency conversion is outside version 1.
- Define rounding only at an explicit boundary. Default arithmetic uses exact decimals; no implicit UI, matching, or database rounding is allowed.

`NUMERIC(20,6)` supports up to 14 integral and 6 fractional digits. Any future requirement beyond this range requires a migration and decision update rather than silent truncation.

## Consequences

- Matching and report totals remain deterministic across Python and PostgreSQL.
- API clients must treat amounts as strings; OpenAPI examples and frontend types must make this explicit.
- Developers must avoid `float`, JavaScript `number`, and database floating types for money.
- Tests must cover parsing, maximum bounds, scale rejection, exact equality, allocation totals, and serialization round trips.
- A reviewed decimal dependency may be required in the frontend.

## Alternatives rejected

- **Binary floating point:** simple but cannot guarantee decimal equality or totals.
- **Integer minor units only:** safe for common fiat currencies but insufficient for the selected six-decimal source contract and awkward across currency exponents.
- **Arbitrary unbounded numeric:** avoids an explicit limit but weakens schema validation and predictable storage.
