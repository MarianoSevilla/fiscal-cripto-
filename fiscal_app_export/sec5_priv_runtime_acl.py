"""SEC5-PRIV: grant only existing ORM-table DML + owned sequences.

Preparatorio: NO invocado por Flask, Procfile, migraciones ni Railway.
Un operador debe autorizar por separado cualquier creación de roles o cambio
de permisos en una base persistente. La prueba CI usa PostgreSQL desechable.
"""
from __future__ import annotations

from psycopg2 import sql


def grant_existing_runtime_acl(cursor, *, login: str, model_tables: set[str]) -> dict:
    """Apply explicit grants. Caller owns the transaction and creates LOGIN.

    Never adds privileges for future tables, tables outside the ORM, roles,
    schema CREATE, or TRUNCATE. A database administrator executes this only
    after separately validating the instance, database and target identity.
    """
    if not login or len(model_tables) != 17 or "alembic_version" in model_tables:
        raise ValueError("SEC5 runtime ACL: unexpected ORM inventory")
    if any(not name or "." in name or "\x00" in name for name in model_tables):
        raise ValueError("SEC5 runtime ACL: invalid table identifier")

    cursor.execute(
        "SELECT current_setting('server_version_num')::integer / 10000"
    )
    if cursor.fetchone()[0] != 18:
        raise ValueError("SEC5 runtime ACL: PostgreSQL 18 required")

    cursor.execute("""
        SELECT c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
    """)
    actual = {row[0] for row in cursor.fetchall()}
    if "alembic_version" not in actual or not model_tables <= actual:
        raise ValueError("SEC5 runtime ACL: missing tables; no grant")

    cursor.execute("""
        SELECT seq.relname FROM pg_class seq
        JOIN pg_namespace sn ON sn.oid = seq.relnamespace
        JOIN pg_depend d ON d.objid = seq.oid
            AND d.classid = 'pg_class'::regclass
            AND d.refclassid = 'pg_class'::regclass
            AND d.deptype IN ('a','i')
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_namespace tn ON tn.oid = t.relnamespace
        WHERE seq.relkind = 'S' AND sn.nspname = 'public'
            AND tn.nspname = 'public' AND t.relname = ANY(%s)
    """, (sorted(model_tables),))
    owned_sequences = {row[0] for row in cursor.fetchall()}

    # Security boundary: no ALL TABLES IN SCHEMA and no default privileges.
    # The future blocking vault must be in a separate restricted schema.
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
        sql.Identifier(cursor.connection.info.dbname), sql.Identifier(login)))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
        sql.Identifier(login)))
    for table in sorted(model_tables):
        cursor.execute(sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{} TO {}"
        ).format(sql.Identifier(table), sql.Identifier(login)))
    cursor.execute(sql.SQL(
        "GRANT SELECT ON TABLE public.alembic_version TO {}"
    ).format(sql.Identifier(login)))
    for sequence in sorted(owned_sequences):
        cursor.execute(sql.SQL(
            "GRANT USAGE, SELECT ON SEQUENCE public.{} TO {}"
        ).format(sql.Identifier(sequence), sql.Identifier(login)))
    return {"orm_tables": len(model_tables),
            "sequences": len(owned_sequences),
            "alembic_readonly": True, "future_grants": False}
