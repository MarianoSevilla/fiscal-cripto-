# STG-B04 · S01-LAB-LOCK · Code-only draft / NO-GO

**13 Oct 2026. Authorized ONLY: implementation + synthetic offline tests on separate GitHub branch.**

## Real Railway lab verified, unchanged by this PR

- New private project `fiscal-cripto-s01-lab`: `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment `lab`: `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- PostgreSQL 18.6 is ONLINE with **0 public tables** as checked by owner via read-only SQL; one PostgreSQL server + volume only. No web service exists, therefore no web service ID or approved HTTPS origin may be pinned yet. Postgres private endpoint label observed as `postgres`; candidate expected host `postgres.railway.internal` must be confirmed from the future web reference before deployment.
- Production / existing staging are **untouched**.

## Implementation

- New standalone `lab_isolation.py` with hardcoded separate lab project/environment IDs, frozen `LabIdentity`, and **unset** web service ID / HTTPS origin: **actual lab startup fails closed before db.init_app**.
- On a future separately approved web service, verify the actual web service ID, private DB reference resolution and HTTPS origin (must not invent/publicize a domain or use generic `LAB_MODE`). Pin values through an independently reviewed code change and rerun all CI. Do not allow `FLASK_ENV=testing` in deployed Railway; lab must use secure `staging` mode.
- Lab identity is detected before STG-LOCK: one of exact project ID, environment ID, environment name `lab`, or pinned service ID. Any marker triggers full-identity validation; cross-project database host, wrong Railway identity, presence of external credentials or enabled upload/mail features aborts startup. Other unknown `FLASK_ENV=staging` environments continue to be rejected by **unmodified STG-LOCK-001**.
- During preflight, only `GET/HEAD /healthz` on the trusted host or exact `healthcheck.railway.app` Host without Origin are permitted. Every other route/method is 503, foreign hosts 421 and foreign Origin 403; all deny responses have no-store and 503 Retry-After. No payments, auth, admin, reports, FIFO, email, webhooks, uploads or self-registration run during preflight.
- Resend emails are blocked process-wide independently of provider key absence. Stripe and PayPal advisory money flows remain frozen by S01 candidate, without exception.
- `staging_isolation.py` is **not changed** and the old staging tests continue running. `main` and deployed Railway configuration are **not changed**.

## CI gate

1. `pytest` unit tests for synthetic valid lab, unpinned real runtime, every identity field mismatch, provider key/feature flags, foreign DB URLs, mixed stage/production markers, Host/Origin, healthcheck-only and Resend.
2. A process-import Flask test with sockets/requests/psycopg2 connections forcibly blocked verifies that a fabricated valid lab is **blocked by default**. Another, with CI-only in-memory patched test identity, asserts only healthcheck works and 16 real sensitive Flask endpoints return 503.
3. Existing `qa_stg_b01_app_isolation.py`, PG18 suites, browser/Chromium and full Python regression unchanged.
4. This branch is stacked on #61 as a DRAFT PR. Do not merge without complete staged PR graph consolidation/review.

## Required future authorizations (none granted by STG-B04)

- **Web service creation** inside the new project (no source attached; review IDs/DB/URL).
- **Another code review PR** to pin real web ID/approved URL, auto-deploy disabled, and verify exact effective DB reference.
- **Explicit PostgreSQL DDL / bootstrap** only after separate preflight, backups and user approval.
- **Explicit web deployment** on exact SHA only after G04 startup gate and DB head `z9a0b1c2d3e4`.
- Test traffic beyond healthcheck, financial flows, rollback/restoration and teardown each require their own scoped gate.

**NO-GO** means that green CI proves synthetic guards; it does not demonstrate that the live lab web functions (none deployed) or database schema has been initialized (0 tables).
