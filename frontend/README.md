# LedgerLine frontend

The React app uses Tailwind CSS v4 theme tokens, React Router, TanStack Query,
and cookie-based authentication. The API client includes credentials on requests
and only adds an `Idempotency-Key` header when a request explicitly provides one.

Set `VITE_API_BASE_URL` when the API is served from a different origin. By
default, requests use the `/api` prefix and the Vite development proxy forwards
them to the backend. The authentication provider loads the current session from
`GET /auth/me`.

Production builds default to an empty `VITE_API_BASE_URL`, so requests use the
same origin as the FastAPI-served frontend; development still defaults to `/api`
and the Vite proxy. The backend serves the Vite build and falls back to
`index.html` for browser-side routes. Keep the frontend and API on the same
origin for the existing secure, strict-samesite authentication cookie.

The Statements page loads the visible accounts from `GET /accounts` and fetches
filtered, cursor-paginated activity from `GET /accounts/{id}/statement`.
Account visibility is enforced by the API for each signed-in role.

Audit Logs uses the cursor-paginated `GET /audit-logs` endpoint with action and
date filters; account holders only receive their own events. Profile displays
the signed-in user's name, email, and role without edit controls. The Admin page
allows admins to create accounts, assign users, and list users and accounts.
Admins and auditors can run reconciliation and ledger verification checks;
auditors only see the read-only check view. `GET /admin/users` returns safe user
summaries to administrators only.
