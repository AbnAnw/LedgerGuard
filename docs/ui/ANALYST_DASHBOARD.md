# Analyst Dashboard Contract

## Purpose

Day 8 turns the authenticated shell into an operational reconciliation workspace. The dashboard
must help an operations analyst identify the largest unresolved discrepancy, inspect its evidence,
see ingestion quality, and start a new reconciliation run without exposing administrative controls.
Auditors receive the same stored evidence in read-only mode.

## Read model

`GET /api/v1/dashboard/overview` requires both `transactions:read` and
`reconciliation:read`. It accepts a source-system and source-account identifier and returns:

- the selected synthetic account;
- decimal-string summary values calculated by Python `Decimal`;
- the completed reconciliation run with the latest effective UTC input cutoff and all result
  evidence (a later-created historical run cannot hide newer evidence);
- recent ingestion batches associated with that account's financial facts;
- validation-failure totals and stable classification counts.

The frontend never converts money to JavaScript `number`. Display values remain strings. Sorting
decimal values uses scaled `BigInt` comparison, and percentages arrive pre-calculated as strings.

### Metric definitions

- **Transaction value:** sum of each eligible transaction once.
- **Exact matched value:** transaction value in `exact_match` results.
- **Unresolved value:** for each non-exact result, the greater of its transaction and settlement
  total, summed once per result.
- **Match rate:** exact matched transaction value divided by total transaction value, expressed as
  a two-decimal percentage string; zero when there is no transaction value.
- **Validation failures:** sum of rejected-record counts in related ingestion batches.

These are operational indicators, not accounting balances or fraud conclusions.

## Interface states

- **Signed out:** least-privilege login form and public platform description.
- **Loading:** an announced dashboard loading state after authentication or refresh.
- **Ready:** summary cards, batch table, discrepancy filters/table, and details panel.
- **Empty:** a clear prompt when no completed reconciliation run exists.
- **Filtered empty:** a clear message when filters exclude all results.
- **Validation:** the run form rejects a window outside 1–168 hours before making a request.
- **Forbidden:** a specific message for HTTP 403 without exposing protected data.
- **Error:** a generic recoverable message with a retry action.

## Role behaviour

| Capability | Administrator | Operations analyst | Auditor |
| --- | --- | --- | --- |
| View dashboard and evidence | Yes | Yes | Yes |
| Filter, sort, and open details | Yes | Yes | Yes |
| Start reconciliation | Yes | Yes | No |
| See administration navigation | Yes | No | No |
| See read-only indicator | No | No | Yes |

The API independently enforces every permission. Hiding a control is usability, not authorization.
Bearer tokens remain only in React memory and are cleared on sign-out.

## Prioritisation and interaction

The default table order is deterministic:

1. non-exact results before exact matches;
2. larger unresolved exposure first using decimal-safe comparison;
3. classification and result UUID as stable tie-breakers.

Analysts can filter by classification and search source record ID, reference, reason code, or
classification. Selecting a row opens exact evidence, linked transactions and settlements, UTC
timestamps, totals, reason code, and the evidence digest.

## Accessibility and responsive behaviour

- Navigation, filters, tables, status/error messages, and details use labelled semantic elements.
- Keyboard users can select discrepancy rows through buttons with visible focus treatment.
- Status is not communicated by colour alone.
- The table scrolls horizontally on narrow screens; summary and detail layouts collapse to one
  column without hiding evidence.
- Displayed timestamps are explicitly labelled UTC.

## Test and acceptance matrix

- Analyst sees summary values, batches, discrepancies, run controls, and evidence details.
- Auditor sees evidence and read-only messaging but no write control.
- Highest-priority seeded discrepancy appears first under the default sort.
- Search and classification filters update the result list deterministically.
- Decimal sorting handles values larger than JavaScript's safe integer range.
- Loading, empty, filtered-empty, validation, forbidden, and recoverable error states render.
- A successful run refreshes the overview; a failed run preserves existing evidence and shows an
  error.
- Backend tests verify metric definitions, account scoping, and permission boundaries.
- Frontend lint, type-checking, browser-component journeys, production build, and live API smoke
  checks pass.

Day 8 is complete when an analyst can locate and explain the highest-priority synthetic discrepancy
from the dashboard, and an auditor can inspect the same evidence without any write capability.
