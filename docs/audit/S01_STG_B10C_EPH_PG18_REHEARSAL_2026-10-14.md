# STG-B10C — PostgreSQL18 synthetic bootstrap rehearsal (NO-GO live lab)

## Scope and authorization

Owner instructed "procede" after STG-B10B. This phase implements and tests an **offline/synthetic procedural rehearsal**, not a real lab initialization. No mutations to Railway, no connecting GitHub source to Railway maintenance service, no prod/staging SQL, and no change to `main`. Base is PR #65, SHA `4403b03eb69e07d4f7256ed41f434668ddacf25b`; PR stays DRAFT and stacked.

## Finding and technical resolution

Existing `bootstrap_db.py` imports `app.py`, whose lab guard only accepts web service ID `212f4f52-b349-4387-a046-9f6b08237d2e`. The maintenance service has ID `9728d19b-7d17-4acb-8be1-c4b0847179df`. Bypassing or mutating the web identity in order to perform DDL would violate its safety model.

The proposed **future** administrative runner will use an isolated Flask object (no routes, no listeners, no providers), `models.db` metadata and the existing Flask-Migrate scripts; it will *not* import `app.py`. This is rehearsed on CI-local PostgreSQL 18 by `private_maintenance_rehearsal.py`, which is restricted to fixed `127.0.0.1:5432/railway` and the CI-synthetic password, and refuses any environment containing `RAILWAY_*` or a `DATABASE_URL`. Its `main()` is permanently `NO-GO`: no production launch flag or permission is shipped. It is **not** the executable for Railway.

## Synthetic sequence and negative tests

1. Strictly validate CI markers, explicit localhost synthetic DSN, no Railway markers and no arbitrary DATABASE_URL. Check Alembic revision graph has exactly `z9a0b1c2d3e4`.
2. Acquire session-scoped fixed PostgreSQL advisory lock. It only serializes **cooperating** executors and cannot stop an independent/unreviewed writer.
3. Establish independent READ ONLY connection. Verify empty `public` catalog: relations/functions/types/schemas/extensions/event triggers, database name and PostgreSQL 18. Abort on any unexpected object, or busy lock.
4. Create minimal isolated Flask+SQLAlchemy+Migrate context, `db.create_all`, Alembic `stamp(m6n7o8p9q0r1)`, `upgrade(head)`. This writes to the **disposable CI PostgreSQL** only. On failure leave dirty state for inspection, no automatic DROP/rollback illusion.
5. Check resulting Alembic head, critical S01 tables, constraints and indexes, and presence of the Bitcoin resource seed. Release advisory lock.
6. Repeat same call: must deny `NOT_PRISTINE` before DDL.
7. Test full runtime CLI with subprocess: always exits NO-GO.
8. No app import, no modification of existing `bootstrap_db.py`, `lab_isolation.py`, `Procfile`, `startup_schema_gate.py`, migrations or public routes.

CI is GitHub Actions on `ubuntu-24.04`, a transient `postgres:18` container and the project's locked Python dependencies, no Railway secrets or network access to the lab. Failures prove rehearsal is **not** yet safe to deploy.

## Outstanding gates for a real live-lab execution (separate authorization)

- Obtain direct proof of effective `RAILWAY_PRIVATE_DOMAIN` and `DATABASE_URL`/reference identity. Service-level DNS name `postgres.railway.internal` alone does **not** prove isolation.
- Independent inventory must confirm maintenance and web services have no public HTTP domains or TCP proxies, no source deployment, no auto-deploy, no other writer; maintenance restart=NEVER, cron absent, one replica.
- Review a distinct, hardened live-lab executor with strict project/environment/maintenance service ID, non-web minimal Flask context, identity check **before imports/network**, once-only permission, cooperative advisory lock, at-most-one attempt and postflight, and a named exact code SHA.
- Validate network, TLS policy, restore plan for a *partially applied* schema, recovery/teardown criteria, seeds/migration graph and acceptance of generated app schema. A partial failure cannot be made atomic because DDL and seed upgrade may span multiple transaction boundaries.
- Only with separate explicit owner authorization for PostgreSQL writes, and after final B09 revalidation, schedule one controlled run on LAB. Record before/after and veto prod/staging.
- Subsequent web deploy has another independent approval; no merge of pending stacked PRs automatically.

**STOP/NO-GO:** Railway maintenance service still empty/inactive. No production/staging changes, no real lab PostgreSQL DDL, no deployed web or money/email traffic. B10C marks *synthetic rehearsal only*.
