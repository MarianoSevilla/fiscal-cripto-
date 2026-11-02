"""SEC5-PRIV: explicit, metadata-only audit of the CURRENT PostgreSQL login.

This is NOT a role migration, runtime startup check, vault-access proof, or
legal blocking implementation. Never print database URLs or caught exceptions.
It is NOT imported by the Flask service. Execute manually only if authorised.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import text

ROLE_QUERY = """
SELECT
    current_setting('server_version_num')::integer / 10000 AS pg_major,
    (current_user = session_user) AS same_session_role,
    r.rolcanlogin, r.rolsuper, r.rolbypassrls, r.rolcreaterole,
    r.rolcreatedb, r.rolreplication,
    (SELECT pg_has_role(session_user, d.datdba, 'MEMBER')
       FROM pg_database d WHERE d.datname = current_database())
       AS database_owner_membership,
    (SELECT pg_has_role(session_user, n.nspowner, 'MEMBER')
       FROM pg_namespace n WHERE n.nspname = 'public')
       AS public_schema_owner_membership,
    EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
          AND pg_has_role(session_user, c.relowner, 'MEMBER')
    ) AS public_object_owner_membership,
    has_schema_privilege('public', 'CREATE') AS public_schema_create,
    has_database_privilege(current_database(), 'CREATE')
       AS database_schema_create,
    EXISTS (
        SELECT 1 FROM pg_roles privileged
        WHERE pg_has_role(session_user, privileged.oid, 'SET')
          AND (privileged.rolsuper OR privileged.rolbypassrls
               OR privileged.rolcreaterole OR privileged.rolcreatedb
               OR privileged.rolreplication)
    ) AS privileged_set_role
FROM pg_roles r
WHERE r.rolname = current_user
"""

_BOOLEAN_FIELDS = (
    "same_session_role", "rolcanlogin", "rolsuper", "rolbypassrls",
    "rolcreaterole", "rolcreatedb", "rolreplication",
    "database_owner_membership", "public_schema_owner_membership",
    "public_object_owner_membership", "public_schema_create",
    "database_schema_create", "privileged_set_role",
)
# The third column is the UNSAFE value, not the permitted baseline.
_RISK_FLAGS = (
    ("same_session_role", "set_role_already_active", False),
    ("rolcanlogin", "not_a_login_role", False),
    ("rolsuper", "superuser", True),
    ("rolbypassrls", "bypass_rls", True),
    ("rolcreaterole", "create_role", True),
    ("rolcreatedb", "create_database", True),
    ("rolreplication", "replication", True),
    ("database_owner_membership", "database_owner_membership", True),
    ("public_schema_owner_membership", "public_schema_owner_membership", True),
    ("public_object_owner_membership", "public_object_owner_membership", True),
    ("public_schema_create", "public_schema_create", True),
    ("database_schema_create", "database_schema_create", True),
    ("privileged_set_role", "privileged_set_role", True),
)


def inspect_runtime_role(engine) -> dict:
    """Return flags only. A clean result is NOT proof of vault isolation.

    Catalogs only: pg_roles, pg_database, pg_namespace and pg_class. No
    customer tables, pg_authid/passwords, application PII or DDL.
    """
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            if connection.exec_driver_sql(
                "SHOW transaction_read_only"
            ).scalar_one() != "on":
                raise RuntimeError("Read-only inspection not confirmed")
            record = connection.execute(text(ROLE_QUERY)).mappings().one()
        finally:
            transaction.rollback()

    if record["pg_major"] != 18:
        raise RuntimeError("PostgreSQL 18 required for this audit")
    if any(type(record[key]) is not bool for key in _BOOLEAN_FIELDS):
        raise RuntimeError("Indeterminate PostgreSQL role attributes")

    failures = sorted(
        label for key, label, expected in _RISK_FLAGS
        if record[key] == expected
    )
    return {
        "postgres_major": 18,
        "catalog_readonly": True,
        "role_separation_candidate": not failures,
        "status": "NEEDS_SEPARATION" if failures else "CANDIDATE_ONLY",
        "risk_flags": failures,
        "vault_isolation_proven": False,
        "production_authorized": False,
    }


def main() -> int:
    """An explicit operator-only command; never runs in Procfile/startup."""
    if os.environ.get("SEC5_PRIV_ROLE_PREFLIGHT") != "EXPLICIT_READONLY":
        print("SEC5_PRIV_ROLE_PREFLIGHT: OPT_IN_REQUIRED", file=sys.stderr)
        return 2
    try:
        # The web service's exact engine and DATABASE_URL must be inspected;
        # never replace them with a separate administrator DSN.
        from app import app, db
        with app.app_context():
            result = inspect_runtime_role(db.engine)
    except Exception:
        # Never leak DSN, passwords, connection errors or catalog details.
        print("SEC5_PRIV_ROLE_PREFLIGHT: INDETERMINATE", file=sys.stderr)
        return 2

    print("SEC5_PRIV_ROLE_PREFLIGHT: " + result["status"])
    print("SEC5_PRIV_ROLE_PREFLIGHT_FLAGS: " + ",".join(result["risk_flags"]))
    print("SEC5_PRIV_ROLE_PREFLIGHT_VAULT_PROVEN: false")
    return 1 if result["risk_flags"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
