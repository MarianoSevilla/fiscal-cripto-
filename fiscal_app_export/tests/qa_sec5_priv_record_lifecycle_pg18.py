"""SEC5-PRIV: scoped record lifecycle rehearsal on disposable PG18 with real ORM tables.

TEST ONLY. No user-facing deletion, legal decision workflow or production vault.
This script may only use its named local CI database; never a DATABASE_URL.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Barrier
import os
from pathlib import Path
import sys

import psycopg2
from psycopg2 import errors, sql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import (  # noqa: E402
    db, User, ProcessingError, FiscalAdvisoryRequest, FiscalAdvisoryFile,
    Contacto, CommunicationCampaign,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
)
from sec5_priv_runtime_acl import grant_existing_runtime_acl  # noqa: E402
from sec5_priv_advisory_file_probe import inspect_advisory_file_metadata  # noqa: E402
from privacy_scope_probe import inventory_verified_user_synthetic  # noqa: E402

DB = "sec5_priv_lifecycle_ci"
APP_LOGIN = "sec5_lifecycle_runtime_ci"
LEGAL_LOGIN = "sec5_lifecycle_legal_ci"
VAULT = "sec5_priv_lifecycle_vault_ci"
ADMIN_PASSWORD = "ci-only-test-password"
APP_PASSWORD = "synthetic-runtime-only"
LEGAL_PASSWORD = "synthetic-legal-only"
AUTHORIZED = "SYNTHETIC_MANUALLY_REVIEWED"
MODES = frozenset({"SUPRIMIR", "BLOQUEAR_ART32"})


def _guard():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or os.environ.get("FLASK_ENV") != "testing"
        or os.environ.get("SEC5_PRIV_LIFECYCLE_PG18_ONLY") != "1"
        or os.environ.get("DATABASE_URL")
        or any(k.startswith("RAILWAY_") for k in os.environ)
        or any(os.environ.get(k) for k in (
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
            "PAYPAL_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "RESEND_API_KEY"
        ))
    ):
        raise RuntimeError("SEC5 lifecycle: disposable PG18 CI only")


def _connect(dbname, *, user="postgres", password=ADMIN_PASSWORD):
    _guard()
    if dbname not in ("postgres", DB):
        raise RuntimeError("Unexpected CI database")
    return psycopg2.connect(
        host="127.0.0.1", port=5432, dbname=dbname, user=user,
        password=password, connect_timeout=5,
        options="-c statement_timeout=5000",
    )


@contextmanager
def _tx(dbname=DB, **kwargs):
    with closing(_connect(dbname, **kwargs)) as con:
        with con:
            with con.cursor() as cur:
                yield cur


def _expect_denied(user, password, statement):
    with closing(_connect(DB, user=user, password=password)) as con:
        with con.cursor() as cur:
            try:
                cur.execute(statement)
            except errors.InsufficientPrivilege:
                con.rollback()
                return
    raise AssertionError("Unexpected SQL privilege for isolated role")


def _seed(engine):
    with Session(engine) as session:
        a = User(email="synthetic-a@example.invalid", role="user", is_active=True)
        b = User(email="synthetic-b@example.invalid", role="user", is_active=True)
        c = User(email="synthetic-inactive@example.invalid", is_active=False)
        session.add_all((a, b, c))
        session.flush()
        a_id, b_id, c_id = a.id, b.id, c.id
        blocked = ProcessingError(
            user_id=a_id, email=a.email, exchange="binance",
            message_short="Synthetic A diagnostic",
            csv_filename="synthetic-a.csv", csv_context='{"test":"a"}',
        )
        erased = ProcessingError(
            user_id=a_id, email=a.email, exchange="kraken",
            message_short="Synthetic A deletable diagnostic",
        )
        other = ProcessingError(
            user_id=b_id, email=a.email, exchange="bitvavo",
            message_short="Copied email does not establish ownership",
        )
        orphan = ProcessingError(
            user_id=None, email=a.email, exchange="coinbase",
            message_short="Unlinked email candidate",
        )
        inactive = ProcessingError(
            user_id=c_id, email=c.email, exchange="bit2me",
            message_short="No active identity verification",
        )
        session.add_all((blocked, erased, other, orphan, inactive))
        request = FiscalAdvisoryRequest(
            user_id=b_id, full_name="Synthetic B", email=b.email,
            tax_residence_country="ES", tax_year=2025,
            service_type="revision_basica", case_description="Synthetic case",
        )
        session.add(request)
        session.flush()
        attempt = S01StripeCheckoutAttempt(
            id="33333333-3333-4333-8333-333333333333",
            advisory_id=request.id, quote_fingerprint="c" * 64,
            idempotency_key="ci-lifecycle-b", expected_amount_cents=9900,
            status="reserved",
        )
        session.add(attempt)
        session.flush()
        session.add(S01StripeEventReceipt(
            stripe_event_id="evt_sec5_lifecycle_b",
            attempt_id=attempt.id, event_type="checkout.session.completed",
        ))
        session.flush()
        # Two synthetic historical metadata rows, one deliberately linked to
        # a different account than the request. No physical files are created.
        session.add_all([
            FiscalAdvisoryFile(
                request_id=request.id, user_id=b_id, file_name="synthetic-b.pdf",
                file_path="/ci-only/nonexistent-b.pdf", file_type="application/pdf",
            ),
            FiscalAdvisoryFile(
                request_id=request.id, user_id=c_id, file_name="synthetic-mismatch.pdf",
                file_path="/ci-only/nonexistent-mismatch.pdf",
                file_type="application/pdf",
            ),
        ])
        session.flush()
        result = (a_id, b_id, c_id, blocked.id, erased.id, other.id, orphan.id,
                  inactive.id, attempt.id)
        session.commit()
        return result


def _rehearsal(record_id, user_id, email, *, decision, authorization,
               inject_failure=False, inject_failure_after_delete=False):
    """Operator-only simulated operation for a single verified processing error.

    No public entrypoint; refuses financial-advisory records. A vault tombstone
    for SUPRIMIR is only a synthetic recovery artifact, not a retention rule.
    """
    if (
        type(record_id) is not int or record_id <= 0
        or type(user_id) is not int or user_id <= 0
        or not isinstance(email, str) or not email
        or authorization != AUTHORIZED or decision not in MODES
    ):
        raise PermissionError("Unverified synthetic request")
    with _tx() as cur:
        cur.execute(
            "SELECT email, is_active FROM public.users WHERE id=%s FOR UPDATE",
            (user_id,),
        )
        user = cur.fetchone()
        if user is None or not user[1] or user[0].casefold() != email.strip().casefold():
            raise PermissionError("Unverified active account/email pairing")
        # Deliberately conservative: never process even a diagnostic row
        # while the subject has an advisory case that needs separate review.
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM public.fiscal_advisory_requests "
            "WHERE user_id=%s)",
            (user_id,),
        )
        if cur.fetchone()[0]:
            raise PermissionError("Advisory or financial records require review")
        cur.execute(
            "SELECT user_id FROM public.processing_errors "
            "WHERE id=%s FOR UPDATE",
            (record_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                sql.SQL("SELECT user_id, decision FROM {}.ledger WHERE source_id=%s")
                .format(sql.Identifier(VAULT)), (record_id,),
            )
            previous = cur.fetchone()
            if previous == (user_id, decision):
                return False
            raise LookupError("Missing record or incompatible previous decision")
        if row[0] != user_id:
            raise PermissionError("Record belongs to another or unknown subject")
        cur.execute(
            sql.SQL("""
                INSERT INTO {}.ledger(source_id, user_id, decision, payload)
                SELECT p.id, p.user_id, %s,
                    CASE WHEN %s='BLOQUEAR_ART32' THEN to_jsonb(p)
                         ELSE NULL END
                FROM public.processing_errors p
                WHERE p.id=%s AND p.user_id=%s
            """).format(sql.Identifier(VAULT)),
            (decision, decision, record_id, user_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Concurrent source mismatch")
        if inject_failure:
            raise RuntimeError("Injected synthetic failure")
        cur.execute(
            "DELETE FROM public.processing_errors WHERE id=%s AND user_id=%s",
            (record_id, user_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Unexpected concurrent delete")
        if inject_failure_after_delete:
            raise RuntimeError("Injected synthetic failure after delete")
        return True


def _assert_lifecycle(engine, ids):
    a, b, c, block_id, erase_id, other_id, orphan_id, inactive_id, attempt_id = ids

    for kwargs in (
        {"decision": "BLOQUEAR_ART32", "authorization": None},
        {"decision": "SUPRIMIR", "authorization": "LEGAL_APPROVED"},
        {"decision": "KEEP", "authorization": AUTHORIZED},
    ):
        try:
            _rehearsal(block_id, a, "synthetic-a@example.invalid", **kwargs)
        except PermissionError:
            pass
        else:
            raise AssertionError("A request without the synthetic gate was accepted")

    for rid, uid, address, mode in (
        (other_id, a, "synthetic-a@example.invalid", "SUPRIMIR"),
        (orphan_id, a, "synthetic-a@example.invalid", "SUPRIMIR"),
        (inactive_id, c, "synthetic-inactive@example.invalid", "SUPRIMIR"),
        (other_id, b, "synthetic-b@example.invalid", "SUPRIMIR"),
    ):
        try:
            _rehearsal(rid, uid, address, decision=mode, authorization=AUTHORIZED)
        except PermissionError:
            pass
        else:
            raise AssertionError("Unsafe account scope or financial state was accepted")

    try:
        _rehearsal(block_id, a, "synthetic-a@example.invalid",
                   decision="BLOQUEAR_ART32", authorization=AUTHORIZED,
                   inject_failure=True)
    except RuntimeError as exc:
        assert str(exc) == "Injected synthetic failure"
    else:
        raise AssertionError("Missing simulated rollback")

    with _tx() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.ledger").format(sql.Identifier(VAULT)))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM public.processing_errors WHERE id=%s",
                    (block_id,))
        assert cur.fetchone()[0] == 1

    # A failure after the DELETE must also roll back the entire transaction.
    try:
        _rehearsal(erase_id, a, "synthetic-a@example.invalid",
                   decision="SUPRIMIR", authorization=AUTHORIZED,
                   inject_failure_after_delete=True)
    except RuntimeError as exc:
        assert str(exc) == "Injected synthetic failure after delete"
    else:
        raise AssertionError("Post-delete crash did not roll back")
    with _tx() as cur:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.ledger").format(
            sql.Identifier(VAULT)))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM public.processing_errors WHERE id=%s",
                    (erase_id,))
        assert cur.fetchone()[0] == 1

    assert _rehearsal(block_id, a, "synthetic-a@example.invalid",
                      decision="BLOQUEAR_ART32", authorization=AUTHORIZED)

    # Two concurrent identical requests must serialize at the user/row lock,
    # produce exactly one ledger item, and return one new + one idempotent result.
    simultaneous = Barrier(2)
    def _concurrent_erasure():
        simultaneous.wait(timeout=10)
        return _rehearsal(erase_id, a, "synthetic-a@example.invalid",
                          decision="SUPRIMIR", authorization=AUTHORIZED)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_concurrent_erasure)
        second = pool.submit(_concurrent_erasure)
        assert sorted((first.result(timeout=20), second.result(timeout=20))) == [False, True]
    assert _rehearsal(block_id, a, "synthetic-a@example.invalid",
                      decision="BLOQUEAR_ART32", authorization=AUTHORIZED) is False
    assert _rehearsal(erase_id, a, "synthetic-a@example.invalid",
                      decision="SUPRIMIR", authorization=AUTHORIZED) is False
    try:
        _rehearsal(erase_id, a, "synthetic-a@example.invalid",
                   decision="BLOQUEAR_ART32", authorization=AUTHORIZED)
    except LookupError:
        pass
    else:
        raise AssertionError("Incompatible replay accepted")

    with Session(engine) as session:
        assert session.get(ProcessingError, block_id) is None
        assert session.get(ProcessingError, erase_id) is None
        assert session.get(ProcessingError, other_id).user_id == b
        assert session.get(ProcessingError, orphan_id).user_id is None
        assert session.get(ProcessingError, inactive_id).user_id == c
        assert session.execute(
            select(S01StripeEventReceipt).where(
                S01StripeEventReceipt.attempt_id == attempt_id)
        ).scalar_one().stripe_event_id == "evt_sec5_lifecycle_b"

    with _tx() as cur:
        cur.execute(sql.SQL(
            "SELECT source_id, user_id, decision, payload FROM {}.ledger "
            "ORDER BY source_id"
        ).format(sql.Identifier(VAULT)))
        entries = {row[0]: row for row in cur.fetchall()}
        assert set(entries) == {block_id, erase_id}
        assert entries[block_id][1:3] == (a, "BLOQUEAR_ART32")
        assert entries[block_id][3]["csv_context"] == '{"test":"a"}'
        assert entries[block_id][3]["email"] == "synthetic-a@example.invalid"
        assert entries[erase_id][1:3] == (a, "SUPRIMIR")
        assert entries[erase_id][3] is None

    # Exercise the count-only preflight with a real, limited PostgreSQL login.
    # It may report mismatched ownership but must never expose names or paths.
    probe_engine = create_engine(
        f"postgresql+psycopg2://{APP_LOGIN}:{APP_PASSWORD}@127.0.0.1:5432/{DB}"
    )
    try:
        report = inspect_advisory_file_metadata(probe_engine)
        assert report["status"] == "REVIEW_REQUIRED"
        assert report["metadata_rows"] == 2
        assert report["linked_requests"] == 1
        assert report["linked_users"] == 2
        assert report["ownership_mismatches"] == 1
        assert report["missing_requests"] == 0
        assert not report["physical_files_verified"]
        assert not report["complete_inventory_proven"]
        assert not any("file_name" in key or "file_path" in key for key in report)
    finally:
        probe_engine.dispose()

    with _tx(user=APP_LOGIN, password=APP_PASSWORD) as cur:
        cur.execute(
            "SELECT id FROM public.processing_errors WHERE id IN (%s,%s)",
            (block_id, erase_id))
        assert cur.fetchall() == []

    _expect_denied(APP_LOGIN, APP_PASSWORD, sql.SQL(
        "SELECT payload FROM {}.ledger").format(sql.Identifier(VAULT)))
    _expect_denied(LEGAL_LOGIN, LEGAL_PASSWORD,
                   "SELECT email FROM public.processing_errors")
    _expect_denied(LEGAL_LOGIN, LEGAL_PASSWORD, sql.SQL(
        "UPDATE {}.ledger SET payload=NULL WHERE source_id=1"
    ).format(sql.Identifier(VAULT)))
    _expect_denied(APP_LOGIN, APP_PASSWORD, "SET ROLE postgres")
    _expect_denied(LEGAL_LOGIN, LEGAL_PASSWORD, "SET ROLE postgres")

    with _tx(user=LEGAL_LOGIN, password=LEGAL_PASSWORD) as cur:
        cur.execute(sql.SQL(
            "SELECT source_id, decision FROM {}.ledger ORDER BY source_id"
        ).format(sql.Identifier(VAULT)))
        assert {r[0] for r in cur.fetchall()} == {block_id, erase_id}



def _rehearse_empty_account_row_only(
    engine, *, user_id, original_email, manual_evidence, inject_after_flush=False
):
    """Delete ONLY a synthetic, unreferenced user row, never a real data subject.

    This is NOT a production API or a complete GDPR erasure. It intentionally
    refuses any known direct, actor, case or copied-email candidate, including
    an unpaid advisory case. Unlinked free text, providers and backups remain
    outside this laboratory.
    """
    _guard()
    if engine.url.database != DB or engine.url.host != "127.0.0.1":
        raise RuntimeError("Unexpected non-CI database")
    if manual_evidence != AUTHORIZED:
        raise PermissionError("Synthetic review marker required")
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError("Invalid synthetic account identifier")
    if not isinstance(original_email, str) or not original_email:
        raise PermissionError("Verified synthetic email required")

    with Session(engine) as session:
        with session.begin():
            account = session.execute(
                select(User).where(User.id == user_id).with_for_update()
            ).scalar_one_or_none()
            if account is None:
                # No-op on a missing row, not proof of prior real-world erasure.
                return False
            if account.role != "user" or account.plan != "free":
                raise PermissionError("Staff or paid account requires review")
            # Verify email/active status and classify all known 17-model links.
            scope = inventory_verified_user_synthetic(
                session, user_id=user_id, original_email=original_email
            )
            if scope["tables_modeled"] != 17:
                raise RuntimeError("Unexpected ORM inventory")
            for key in (
                "verified_subject_refs", "staff_actor_refs",
                "copied_email_candidates", "indirect_case_refs",
            ):
                if any(count != 0 for count in scope[key].values()):
                    raise PermissionError("Related data requires separate review")
            if scope["delete_permitted"] or scope["blocking_proven"]:
                raise AssertionError("The synthetic scope must never authorize erasure")
            # A throw after SQL has been flushed proves rollback of the row.
            session.delete(account)
            session.flush()
            if inject_after_flush:
                raise RuntimeError("Injected synthetic post-delete failure")
    return True


def _assert_empty_account_rehearsal(engine, ids):
    """Adversarial, disposable PG18 test; no calls or state in production."""
    a_id, b_id, c_id, *_rest = ids
    with Session(engine) as session:
        clean = User(email="synthetic-clean@example.invalid", role="user")
        copied = User(email="synthetic-copied@example.invalid", role="user")
        actor = User(email="synthetic-actor@example.invalid", role="user")
        concurrent = User(email="synthetic-race@example.invalid", role="user")
        session.add_all((clean, copied, actor, concurrent))
        session.flush()
        clean_id, copied_id = clean.id, copied.id
        actor_id, concurrent_id = actor.id, concurrent.id
        session.add(Contacto(
            nombre="Synthetic", email=copied.email, mensaje="test-only",
            tipo_consulta="otros",
        ))
        session.add(CommunicationCampaign(
            created_by_id=actor_id, subject="test-only", body="synthetic",
        ))
        session.commit()

    def rehearse(user_id, email, *, evidence=AUTHORIZED, failure=False):
        return _rehearse_empty_account_row_only(
            engine, user_id=user_id, original_email=email,
            manual_evidence=evidence, inject_after_flush=failure,
        )

    # Missing/manual or invalid evidence must refuse before touching rows.
    for user_id, email, evidence in (
        (clean_id, "synthetic-clean@example.invalid", "APPROVED"),
        (clean_id, "wrong@example.invalid", AUTHORIZED),
        (a_id, "synthetic-a@example.invalid", AUTHORIZED),
        (b_id, "synthetic-b@example.invalid", AUTHORIZED),
        (c_id, "synthetic-inactive@example.invalid", AUTHORIZED),
        (copied_id, "synthetic-copied@example.invalid", AUTHORIZED),
        (actor_id, "synthetic-actor@example.invalid", AUTHORIZED),
    ):
        try:
            rehearse(user_id, email, evidence=evidence)
        except (ValueError, PermissionError):
            pass
        else:
            raise AssertionError("Unsafe synthetic account deletion accepted")

    # An exception after DELETE/flush must fully restore the account.
    try:
        rehearse(clean_id, "synthetic-clean@example.invalid", failure=True)
    except RuntimeError as exc:
        assert str(exc) == "Injected synthetic post-delete failure"
    else:
        raise AssertionError("Missing rollback after flushed synthetic DELETE")
    with Session(engine) as session:
        assert session.get(User, clean_id) is not None

    assert rehearse(clean_id, "synthetic-clean@example.invalid")
    assert rehearse(clean_id, "synthetic-clean@example.invalid") is False

    # Two simultaneous requests must serialize; never erase a second account.
    barrier = Barrier(2)
    def worker():
        barrier.wait(timeout=10)
        return rehearse(concurrent_id, "synthetic-race@example.invalid")
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(worker), pool.submit(worker)
        assert sorted((one.result(timeout=20), two.result(timeout=20))) == [
            False, True
        ]

    with Session(engine) as session:
        assert session.get(User, clean_id) is None
        assert session.get(User, concurrent_id) is None
        for surviving_id in (a_id, b_id, c_id, copied_id, actor_id):
            assert session.get(User, surviving_id) is not None
        assert session.execute(
            select(Contacto.id).where(
                Contacto.email == "synthetic-copied@example.invalid"
            )
        ).scalar_one() is not None
        assert session.execute(
            select(CommunicationCampaign.id).where(
                CommunicationCampaign.created_by_id == actor_id
            )
        ).scalar_one() is not None
        assert session.execute(
            select(S01StripeEventReceipt.stripe_event_id).where(
                S01StripeEventReceipt.stripe_event_id == "evt_sec5_lifecycle_b"
            )
        ).scalar_one() == "evt_sec5_lifecycle_b"

    print("SEC5_PRIV_EMPTY_ACCOUNT_PG18: PASS "
          "(only synthetic unreferenced user rows, no production or legal erasure)")

def main():
    _guard()
    with _tx("postgres") as cur:
        cur.execute("SELECT current_database(), current_user, "
                    "current_setting('server_version_num')::int")
        assert cur.fetchone()[:2] == ("postgres", "postgres")
        cur.execute("SELECT current_setting('server_version_num')::int")
        assert cur.fetchone()[0] // 10000 == 18

    admin = _connect("postgres")
    admin.autocommit = True
    db_created = False
    roles_created = []
    engine = None
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            db_created = True

        engine = create_engine(
            f"postgresql+psycopg2://postgres:{ADMIN_PASSWORD}@127.0.0.1:5432/{DB}",
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        model_tables = set(db.Model.metadata.tables)
        assert len(model_tables) == 17 and "alembic_version" not in model_tables
        db.Model.metadata.create_all(engine)

        with admin.cursor() as cur:
            for role, secret in ((APP_LOGIN, APP_PASSWORD),
                                 (LEGAL_LOGIN, LEGAL_PASSWORD)):
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(secret)))
                roles_created.append(role)

        with _tx() as cur:
            cur.execute("CREATE TABLE public.alembic_version "
                        "(version_num varchar(32) PRIMARY KEY)")
            cur.execute("INSERT INTO public.alembic_version "
                        "VALUES ('synthetic-version')")
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(VAULT)))
            cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(
                sql.Identifier(VAULT)))
            cur.execute(sql.SQL("""
                CREATE TABLE {}.ledger (
                    source_id integer PRIMARY KEY,
                    user_id integer NOT NULL,
                    decision text NOT NULL CHECK (decision IN ('SUPRIMIR','BLOQUEAR_ART32')),
                    payload jsonb,
                    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                    CHECK ((decision='SUPRIMIR' AND payload IS NULL)
                        OR (decision='BLOQUEAR_ART32' AND payload IS NOT NULL))
                )
            """).format(sql.Identifier(VAULT)))
            grants = grant_existing_runtime_acl(
                cur, login=APP_LOGIN, model_tables=model_tables)
            assert grants["orm_tables"] == 17
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(VAULT), sql.Identifier(LEGAL_LOGIN)))
            cur.execute(sql.SQL("GRANT SELECT ON {}.ledger TO {}").format(
                sql.Identifier(VAULT), sql.Identifier(LEGAL_LOGIN)))

        ids = _seed(engine)
        _assert_lifecycle(engine, ids)
        _assert_empty_account_rehearsal(engine, ids)
        print("SEC5_PRIV_LIFECYCLE_PG18: PASS (synthetic ORM scope, "
              "atomic reservation/erasure, identity/finance guards, "
              "least-privilege SQL, no providers or Railway)")
    finally:
        if engine is not None:
            engine.dispose()
        try:
            with admin.cursor() as cur:
                if db_created:
                    cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(DB)))
                for role in reversed(roles_created):
                    cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(role)))
        finally:
            admin.close()


if __name__ == "__main__":
    main()
