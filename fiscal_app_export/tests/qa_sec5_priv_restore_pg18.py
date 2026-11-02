"""SEC5-PRIV PG18: disposable pg_dump/pg_restore + out-of-backup replay rehearsal.

CI ONLY. No Flask import, production execution, retention policy or legal block.
All credentials, users, records and decision-journal key are fictitious.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg2
from psycopg2 import errors, sql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import db, User, ProcessingError  # noqa: E402
from sec5_priv_runtime_acl import grant_existing_runtime_acl  # noqa: E402

DB = "sec5_priv_restore_ci"
VAULT = "sec5_priv_restored_vault_ci"
APP_LOGIN = "sec5_restore_app_ci"
LEGAL_LOGIN = "sec5_restore_legal_ci"
PG_PASSWORD = "ci-only-test-password"
TEST_KEY = b"synthetic-out-of-backup-journal-key-for-CI-only"
APP_PASSWORD = "synthetic-app-restore"
LEGAL_PASSWORD = "synthetic-legal-restore"


def _guard():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or os.environ.get("FLASK_ENV") != "testing"
        or os.environ.get("SEC5_PRIV_RESTORE_PG18_ONLY") != "1"
        or os.environ.get("DATABASE_URL")
        or any(k.startswith("RAILWAY_") for k in os.environ)
        or any(os.environ.get(k) for k in (
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
            "PAYPAL_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "RESEND_API_KEY",
        ))
    ):
        raise RuntimeError("SEC5 restore rehearsal: isolated GitHub CI only")


def _connect(dbname="postgres", *, user="postgres", password=PG_PASSWORD):
    _guard()
    if dbname not in (DB, "postgres"):
        raise RuntimeError("Unexpected database identity")
    return psycopg2.connect(
        host="127.0.0.1", port=5432, dbname=dbname,
        user=user, password=password, connect_timeout=5,
        options="-c statement_timeout=5000",
    )


@contextmanager
def _tx(dbname=DB, **kwargs):
    with closing(_connect(dbname, **kwargs)) as connection:
        with connection:
            with connection.cursor() as cursor:
                yield cursor


def _client(command, dump=None):
    """Run version-matched PostgreSQL 18 client in the ephemeral CI container."""
    _guard()
    args = [
        "docker", "run", "--rm", "--network", "host",
        "-e", "PGPASSWORD=" + PG_PASSWORD, "postgres:18", command,
        "-h", "127.0.0.1", "-U", "postgres", "-d", DB,
    ]
    args += ["--format=custom"] if command == "pg_dump" else [
        "--no-owner", "--no-privileges", "--exit-on-error",
    ]
    result = subprocess.run(
        args, input=dump, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=90, check=False,
    )
    if result.returncode:
        raise RuntimeError("Synthetic PostgreSQL client failed: " +
                           result.stderr.decode("utf-8", "replace")[-450:])
    return result.stdout


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _mac(value):
    return hmac.new(TEST_KEY, value, hashlib.sha256).hexdigest()


def _row(cur, record_id):
    cur.execute(
        "SELECT id,user_id,email,exchange,message_short "
        "FROM public.processing_errors WHERE id=%s FOR UPDATE",
        (record_id,),
    )
    return cur.fetchone()


def _tag(row):
    return _mac(b"record:" + _canonical(list(row)))


def _sign(payload):
    return {"payload": payload, "signature": _mac(b"manifest:" + _canonical(payload))}


def _validate(envelope, dump):
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValueError("Missing or malformed external decision journal")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or not isinstance(envelope["signature"], str):
        raise ValueError("Invalid decision journal")
    if not hmac.compare_digest(
        envelope["signature"], _mac(b"manifest:" + _canonical(payload))
    ):
        raise ValueError("Decision journal integrity mismatch")
    if payload.get("version") != 1 or payload.get("backup_sha256") != hashlib.sha256(dump).hexdigest():
        raise ValueError("Journal not bound to this exact backup")
    events = payload.get("events")
    if (not isinstance(events, list) or len(events) != 2
            or payload.get("complete_through") != 2
            or [item.get("sequence") for item in events] != [1, 2]):
        raise ValueError("Missing or non-contiguous reviewed decisions")
    if {item.get("decision") for item in events} != {"SUPRIMIR", "BLOQUEAR_ART32"}:
        raise ValueError("Unexpected decision inventory")
    for item in events:
        if set(item) != {"sequence", "record_id", "subject_id", "decision", "row_tag"}:
            raise ValueError("Unexpected decision fields")
        if (type(item["record_id"]) is not int or item["record_id"] <= 0
                or type(item["subject_id"]) is not int or item["subject_id"] <= 0
                or not isinstance(item["row_tag"], str)
                or len(item["row_tag"]) != 64):
            raise ValueError("Invalid scope in decision")
    if len({item["record_id"] for item in events}) != 2:
        raise ValueError("Duplicate source records")
    return payload


def _gate(envelope, dump):
    """Synthetic pre-traffic decision: failure MUST deny opening the restore."""
    _validate(envelope, dump)
    with _tx() as cur:
        cur.execute("SELECT to_regclass(%s)", (VAULT + ".receipt",))
        if cur.fetchone()[0] is None:
            raise RuntimeError("Recovery ledger not reconciled; traffic forbidden")
        cur.execute(sql.SQL(
            "SELECT signature,backup_sha256,applied_count FROM {}.receipt"
        ).format(sql.Identifier(VAULT)))
        receipts = cur.fetchall()
        if receipts != [(envelope["signature"],
                         hashlib.sha256(dump).hexdigest(), 2)]:
            raise RuntimeError("Recovery reconciliation receipt mismatch")
        for item in envelope["payload"]["events"]:
            cur.execute("SELECT EXISTS(SELECT 1 FROM public.processing_errors WHERE id=%s)",
                        (item["record_id"],))
            if cur.fetchone()[0]:
                raise RuntimeError("Restored personal record still accessible")
            cur.execute(sql.SQL(
                "SELECT subject_id,decision,row_tag FROM {}.ledger WHERE source_id=%s"
            ).format(sql.Identifier(VAULT)), (item["record_id"],))
            if cur.fetchone() != (item["subject_id"], item["decision"], item["row_tag"]):
                raise RuntimeError("Recovery evidence incomplete")
    return True


def _reconcile(envelope, dump, *, crash_after_first=False):
    """Atomic replay in a disposable DB only; the production gate is NOT wired."""
    payload = _validate(envelope, dump)
    with _tx() as cur:
        cur.execute("SELECT to_regclass(%s)", (VAULT + ".receipt",))
        if cur.fetchone()[0] is not None:
            # A previous complete replay is idempotent. A mismatch is fatal.
            _gate(envelope, dump)
            return False

        # Verify all rows and ownership before moving even one. Row tags are
        # keyed: the journal contains neither email nor free-text PII.
        originals = []
        for event in payload["events"]:
            row = _row(cur, event["record_id"])
            if row is None or row[1] != event["subject_id"] or not hmac.compare_digest(
                _tag(row), event["row_tag"]
            ):
                raise ValueError("Restored row does not match reviewed subject/snapshot")
            originals.append(row)

        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(VAULT)))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
            sql.Identifier(VAULT)))
        cur.execute(sql.SQL("""
            CREATE TABLE {}.ledger(
                source_id integer PRIMARY KEY,
                subject_id integer NOT NULL,
                decision text NOT NULL,
                row_tag char(64) NOT NULL,
                payload jsonb
            )
        """).format(sql.Identifier(VAULT)))
        cur.execute(sql.SQL("""
            CREATE TABLE {}.receipt(
                signature text NOT NULL,
                backup_sha256 text NOT NULL,
                applied_count integer NOT NULL
            )
        """).format(sql.Identifier(VAULT)))
        for index, (event, row) in enumerate(zip(payload["events"], originals)):
            held = {
                "id": row[0], "user_id": row[1], "email": row[2],
                "exchange": row[3], "message_short": row[4],
            } if event["decision"] == "BLOQUEAR_ART32" else None
            cur.execute(sql.SQL(
                "INSERT INTO {}.ledger(source_id,subject_id,decision,row_tag,payload) "
                "VALUES (%s,%s,%s,%s,%s::jsonb)"
            ).format(sql.Identifier(VAULT)), (
                event["record_id"], event["subject_id"],
                event["decision"], event["row_tag"],
                json.dumps(held) if held is not None else None,
            ))
            cur.execute(
                "DELETE FROM public.processing_errors WHERE id=%s AND user_id=%s",
                (event["record_id"], event["subject_id"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError("Concurrent record or ownership change")
            if crash_after_first and index == 0:
                raise RuntimeError("Injected failure during replay")
        cur.execute(sql.SQL(
            "INSERT INTO {}.receipt(signature,backup_sha256,applied_count) VALUES(%s,%s,2)"
        ).format(sql.Identifier(VAULT)), (
            envelope["signature"], payload["backup_sha256"],
        ))
    return True


def _deny(user, password, statement):
    with closing(_connect(DB, user=user, password=password)) as con:
        with con.cursor() as cur:
            try:
                cur.execute(statement)
            except errors.InsufficientPrivilege:
                con.rollback()
                return
    raise AssertionError("SQL privilege boundary broken")


def main():
    _guard()
    with _tx("postgres") as cur:
        cur.execute("SELECT current_database(),current_user,"
                    "current_setting('server_version_num')::int")
        database, role, version = cur.fetchone()
        assert (database, role, version // 10000) == ("postgres", "postgres", 18)

    admin = _connect("postgres")
    admin.autocommit = True
    created = False
    created_roles = []
    engine = None
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            created = True
        engine = create_engine(
            "postgresql+psycopg2://postgres:" + PG_PASSWORD +
            "@127.0.0.1:5432/" + DB,
        )
        assert len(db.Model.metadata.tables) == 17
        db.Model.metadata.create_all(engine)
        with Session(engine) as session:
            a = User(email="restore-a@example.invalid", is_active=True)
            b = User(email="restore-b@example.invalid", is_active=True)
            session.add_all((a, b))
            session.flush()
            x = ProcessingError(user_id=a.id, email=a.email,
                                exchange="binance", message_short="Synthetic blocked")
            y = ProcessingError(user_id=a.id, email=a.email,
                                exchange="kraken", message_short="Synthetic erased")
            z = ProcessingError(user_id=b.id, email=a.email,
                                exchange="bitvavo", message_short="B owns this record")
            session.add_all((x, y, z))
            session.flush()
            subject, other, blocked, erased, unrelated = a.id, b.id, x.id, y.id, z.id
            session.commit()
        with _tx() as cur:
            cur.execute("CREATE TABLE public.alembic_version(version_num text PRIMARY KEY)")
            cur.execute("INSERT INTO public.alembic_version VALUES ('synthetic-only')")
        engine.dispose()
        engine = None
        dump = _client("pg_dump")
        assert dump and len(dump) > 500
        with _tx() as cur:
            event_rows = [_row(cur, rid) for rid in (blocked, erased)]
        manifest = _sign({
            "version": 1, "backup_sha256": hashlib.sha256(dump).hexdigest(),
            "complete_through": 2,
            "events": [
                {"sequence": i, "record_id": row[0], "subject_id": subject,
                 "decision": decision, "row_tag": _tag(row)}
                for i, (row, decision) in enumerate(
                    zip(event_rows, ("BLOQUEAR_ART32", "SUPRIMIR")), start=1
                )
            ],
        })
        assert "restore-a@example.invalid" not in repr(manifest)
        with _tx() as cur:
            cur.execute("DELETE FROM public.processing_errors WHERE id IN (%s,%s)",
                        (blocked, erased))
            assert cur.rowcount == 2

        # Restore the exact PRE-decision pg_dump, not a cloned current database.
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(DB)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
        _client("pg_restore", dump)

        try:
            _gate(manifest, dump)
        except RuntimeError as exc:
            assert "traffic forbidden" in str(exc)
        else:
            raise AssertionError("Unreconciled restoration was permitted")

        for bad in (None, {}, {"payload": manifest["payload"]}):
            try:
                _reconcile(bad, dump)
            except ValueError:
                pass
            else:
                raise AssertionError("Missing external journal was accepted")

        tampered = copy.deepcopy(manifest)
        tampered["payload"]["events"].pop()
        for altered, supplied_dump in ((tampered, dump), (manifest, dump + b"x")):
            try:
                _reconcile(altered, supplied_dump)
            except ValueError:
                pass
            else:
                raise AssertionError("Tampering or wrong backup was accepted")

        # Even a correctly signed but INCORRECT subject association fails.
        bad_subject = copy.deepcopy(manifest["payload"])
        bad_subject["events"][0]["subject_id"] = other
        try:
            _reconcile(_sign(bad_subject), dump)
        except ValueError:
            pass
        else:
            raise AssertionError("Another subject's data was accepted")

        # An altered restored record must fail closed; revert the test change.
        with _tx() as cur:
            cur.execute("UPDATE public.processing_errors "
                        "SET message_short='synthetic changed' WHERE id=%s",
                        (blocked,))
        try:
            _reconcile(manifest, dump)
        except ValueError:
            pass
        else:
            raise AssertionError("Drift in restored record was accepted")
        with _tx() as cur:
            cur.execute("UPDATE public.processing_errors "
                        "SET message_short='Synthetic blocked' WHERE id=%s",
                        (blocked,))

        try:
            _reconcile(manifest, dump, crash_after_first=True)
        except RuntimeError as exc:
            assert str(exc) == "Injected failure during replay"
        else:
            raise AssertionError("Reconciliation partial failure was accepted")
        with _tx() as cur:
            cur.execute("SELECT to_regclass(%s)", (VAULT + ".ledger",))
            assert cur.fetchone()[0] is None
            cur.execute("SELECT count(*) FROM public.processing_errors")
            assert cur.fetchone()[0] == 3

        assert _reconcile(manifest, dump) is True
        assert _gate(manifest, dump)
        assert _reconcile(manifest, dump) is False  # Idempotent re-run
        with _tx() as cur:
            cur.execute("SELECT user_id,email,message_short FROM "
                        "public.processing_errors WHERE id=%s", (unrelated,))
            assert cur.fetchone() == (
                other, "restore-a@example.invalid", "B owns this record",
            )
            cur.execute(sql.SQL(
                "SELECT source_id,decision,payload FROM {}.ledger ORDER BY source_id"
            ).format(sql.Identifier(VAULT)))
            rows = {row[0]: row for row in cur.fetchall()}
            assert rows[blocked][1:] == (
                "BLOQUEAR_ART32",
                {"id": blocked, "user_id": subject,
                 "email": "restore-a@example.invalid",
                 "exchange": "binance", "message_short": "Synthetic blocked"},
            )
            assert rows[erased][1:] == ("SUPRIMIR", None)

        with admin.cursor() as cur:
            for login, password in ((APP_LOGIN, APP_PASSWORD),
                                    (LEGAL_LOGIN, LEGAL_PASSWORD)):
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password)))
                created_roles.append(login)
        with _tx() as cur:
            outcome = grant_existing_runtime_acl(
                cur, login=APP_LOGIN, model_tables=set(db.Model.metadata.tables))
            assert outcome["orm_tables"] == 17
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(DB), sql.Identifier(LEGAL_LOGIN)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(VAULT), sql.Identifier(LEGAL_LOGIN)))
            cur.execute(sql.SQL(
                "GRANT SELECT ON {}.ledger TO {}"
            ).format(sql.Identifier(VAULT), sql.Identifier(LEGAL_LOGIN)))
        _deny(APP_LOGIN, APP_PASSWORD, sql.SQL(
            "SELECT payload FROM {}.ledger").format(sql.Identifier(VAULT)))
        _deny(APP_LOGIN, APP_PASSWORD, sql.SQL(
            "SELECT signature FROM {}.receipt").format(sql.Identifier(VAULT)))
        _deny(LEGAL_LOGIN, LEGAL_PASSWORD,
              "SELECT email FROM public.processing_errors")
        _deny(LEGAL_LOGIN, LEGAL_PASSWORD, sql.SQL(
            "UPDATE {}.ledger SET payload=NULL").format(sql.Identifier(VAULT)))
        with _tx(user=APP_LOGIN, password=APP_PASSWORD) as cur:
            cur.execute("SELECT id FROM public.processing_errors ORDER BY id")
            assert cur.fetchall() == [(unrelated,)]
        print("SEC5_PRIV_RESTORE_PG18: PASS (real synthetic pg_dump/restore, "
              "external signed journal, pre-traffic deny, replay atomicity, "
              "subject integrity, idempotence, SQL role isolation)")
    finally:
        if engine is not None:
            engine.dispose()
        try:
            with admin.cursor() as cur:
                if created:
                    cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(DB)))
                for role in reversed(created_roles):
                    cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(role)))
        finally:
            admin.close()


if __name__ == "__main__":
    main()
