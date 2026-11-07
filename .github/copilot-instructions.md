# Copilot Instructions

- Represent money as BIGINT paise. Never use floating-point numbers for money.
- Keep all money logic only in `backend/app/services/ledger.py`.
- Perform every money movement in one database transaction.
- Lock account rows with `SELECT ... FOR UPDATE`, ordered by account ID ascending.
- Check balances only after acquiring the locks and inside the transaction.
- Never update or delete ledger rows.
- Decide authorization on the server from the database on every request; never
  take authorization decisions from client input.
- Validate every input with strict Pydantic types.
- Never trust the frontend.
