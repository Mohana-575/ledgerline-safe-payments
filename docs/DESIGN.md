# LedgerLine Design

## Roles and permissions

| Action | ADMIN | ACCOUNT_HOLDER | AUDITOR |
|---|---|---|---|
| View account and ledger data | Yes | Yes, for accounts they are a member of | Yes, read-only |
| Deposit | Any account | Only accounts they are a member of | No |
| Withdraw | Only accounts they are a member of | Only accounts they are a member of | No |
| Transfer from an account | Only accounts they are a member of | Only accounts they are a member of | No |
| Transfer to an account | Any active account, by account number, when transferring from an account they are a member of | Any active account, by account number, when transferring from an account they are a member of | No |
| Create accounts | Yes | No | No |
| Assign account members | Yes | No | No |
| Run reconciliation and ledger verification | Yes | No | Yes, read-only |

An administrator's administrative privileges do not grant permission to withdraw
from or transfer out of an account unless the administrator is also a member of
that account. Account holders may deposit only into accounts they are members of.
An account holder's transfer destination may be any active account identified by
its account number. Auditors may read all data but may not make changes or move
money.

## Account API

- `POST /accounts` and `POST /accounts/{id}/members` are ADMIN-only. Account
  numbers are allocated under a transaction-scoped lock, and creation and member
  assignment are recorded as `ACCOUNT_CREATED` and `MEMBER_ASSIGNED` audit events.
- `GET /accounts` returns all accounts to ADMINs and AUDITORs, and only member
  accounts to ACCOUNT_HOLDERs.
- `GET /accounts/{id}` and `GET /accounts/{id}/balance` use the same visibility
  rules; an ACCOUNT_HOLDER receives 404 for an account they are not a member of.
- Each request resolves the user's current role from the database, and account
  responses do not include user credentials.
- The seed command reserves `ACC1001` and `ACC1002` for its sample Personal and
  Savings accounts. The External system account is `ACC1000`.
- `GET /admin/reconcile` checks total account balances, account-to-ledger
  balances, non-system account balances, and transaction debit/credit equality.
  `GET /admin/verify-ledger` verifies every account's hash chain. Both routes
  are available to ADMINs and AUDITORs and record their run in `audit_logs`.
- `GET /dashboard` reports the authenticated user's member-account balances and
  transaction activity; it does not expose credentials or other users' accounts.

## Ledger invariants

- The sum of all account balances, including the External system account, is
  always zero.
- No non-system account balance may be below zero.
- The ledger is append-only; ledger rows are never updated or deleted.
- A given idempotency key moves money at most once. Keys are scoped per user
  and retained indefinitely; they are not expired or recycled.
- Money endpoints require an 8–128 character `Idempotency-Key` containing only
  ASCII letters, digits, hyphens, or underscores. Repeating a key with the same
  request replays its stored result; using it for a different request is
  refused and recorded.
