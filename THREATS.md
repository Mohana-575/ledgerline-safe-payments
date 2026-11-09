# Threats

## Threat record

- Threat:
- What I did:
- Test that covers it:

## Risks I knowingly accepted

## Mutation check results

| Experiment | Result |
|---|---|
| Removed FOR UPDATE on the account-row lock in ledger.py | all 4 tests in tests/test_concurrency.py failed. 4 of 20 simultaneous withdrawals succeeded against a balance that allowed 1, and the global balance sum drifted by 60,000 paise. |
| Removed the insufficient-funds check | 6 tests failed. The database CHECK constraint (balance >= 0) still blocked every overdraft, but it surfaced as a 500 instead of a clean 409, so the app-level check gives the clean refusal and the database is the second layer. |
| Forced every request to count as the first one (idempotency) | 8 tests failed. Replays created new transactions and a changed amount under the same key was accepted. |
| Removed the membership check for withdraw and transfer | 3 tests failed. Another holder's money moved with 201 Created. |

### Not mutation-tested

- Removing the `order_by` on the account lock query (deadlock avoidance).
- Letting the `AUDITOR` role through in the service layer (the route layer also blocks it).
- Dropping the append-only triggers.
- The role-row and membership-row locks (`read=True` locks), because the tests cannot pause a transaction midway.
