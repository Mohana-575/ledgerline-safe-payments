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
| Run reconciliation | Yes | No | No |

An administrator's administrative privileges do not grant permission to withdraw
from or transfer out of an account unless the administrator is also a member of
that account. Account holders may deposit only into accounts they are members of.
An account holder's transfer destination may be any active account identified by
its account number. Auditors may read all data but may not make changes or move
money.

## Ledger invariants

- The sum of all account balances, including the External system account, is
  always zero.
- No non-system account balance may be below zero.
- The ledger is append-only; ledger rows are never updated or deleted.
- A given idempotency key moves money at most once.
