CREATE ROLE ledgerline_app LOGIN;
\password ledgerline_app

GRANT CONNECT ON DATABASE ledgerline TO ledgerline_app;
GRANT USAGE ON SCHEMA public TO ledgerline_app;

GRANT SELECT, INSERT ON
    transactions,
    ledger_entries,
    refused_attempts,
    audit_logs,
    accounts,
    idempotency_keys
TO ledgerline_app;

GRANT UPDATE (balance_paise, last_entry_hash)
ON accounts TO ledgerline_app;

GRANT UPDATE (status, response_status, response_body)
ON idempotency_keys TO ledgerline_app;

GRANT USAGE, SELECT ON SEQUENCE
    accounts_id_seq,
    ledger_entries_id_seq,
    refused_attempts_id_seq,
    audit_logs_id_seq
TO ledgerline_app;
