"""G04-R02: prove the candidate can safely serve a migrated PG18 schema.

GitHub Actions ONLY, using localhost PostgreSQL 18, synthetic records and
inert providers. Not a deploy, not a tested image rollback, not real clients.
"""
import os
from pathlib import Path

from qa_db_bootstrap_postgres import (
    _create_db, _db_conn, _run, _bootstrap, _startup, HEAD,
)

DB = "s01_recovery_runtime_ci"
ROOT = Path(__file__).resolve().parents[1]


def _guard():
    assert os.environ.get("GITHUB_ACTIONS") == "true", "GitHub CI only"
    assert os.environ.get("CI") == "true", "CI only"
    assert os.environ.get("FLASK_ENV") == "testing", "Testing only"
    assert DB.endswith("_ci")
    assert HEAD == "z9a0b1c2d3e4"


def _snapshot():
    with _db_conn(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, status, quoted_amount, quote_sent_at,
                   quote_expires_at, payment_link_token,
                   paypal_order_id, paypal_capture_id,
                   stripe_checkout_session_id, stripe_payment_intent_id,
                   payment_provider, amount_paid, paid_at,
                   rafa_fee_cents, commission_cents, commission_rate_bps
            FROM fiscal_advisory_requests ORDER BY id
        """)
        records = tuple(cur.fetchall())
        assert len(records) == 6
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM s01_stripe_checkout_attempts),
                (SELECT COUNT(*) FROM s01_stripe_event_receipts),
                (SELECT COUNT(*) FROM s01_stripe_notification_outbox)
        """)
        money = cur.fetchone()
        return records, money


SEED = """
from datetime import datetime
from app import app, db
from models import User, FiscalAdvisoryRequest
with app.app_context():
    advisor = User(email='advisor@ci.invalid', role='fiscal_advisor',
                   is_active=True, email_verified_at=datetime(2026, 1, 1))
    db.session.add(advisor)
    db.session.flush()
    for i in range(1, 7):
        legacy = i == 6
        db.session.add(FiscalAdvisoryRequest(
            full_name='Synthetic Recovery ' + str(i),
            user_id=advisor.id,
            email='synthetic' + str(i) + '@example.invalid',
            tax_residence_country='España', tax_year=2025,
            service_type='presupuesto_personalizado',
            case_description='Fictional G04-R02 record',
            status='quote_sent' if legacy else 'submitted',
            quoted_amount=20000 if legacy else None,
            quote_sent_at=datetime(2026, 9, 1) if legacy else None,
            quote_expires_at=datetime(2026, 10, 1) if legacy else None,
            payment_link_token='CI_EXPIRED_SYNTHETIC_TOKEN' if legacy else None,
        ))
    db.session.commit()
"""


HTTP_PROBE = """
from unittest.mock import patch
from sqlalchemy import event
import app as mod
from app import app, db
from advisory_prefreeze import SUSPENSION_MESSAGE

assert mod._PAYPAL_ENABLED is False
assert app.config['SQLALCHEMY_DATABASE_URI'].endswith('/s01_recovery_runtime_ci')
app.config.update(TESTING=True, RATELIMIT_ENABLED=False,
                  SESSION_COOKIE_SECURE=False)
with app.app_context():
    engine = db.engine
    denied = []
    def financial_writes(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith(('INSERT', 'UPDATE', 'DELETE')):
            if any(table in normalized for table in (
                'FISCAL_ADVISORY_REQUESTS', 'S01_STRIPE_',
                'ADVISORY_AUDIT_LOG', 'FISCAL_ADVISORY_STATUS_HISTORY')):
                denied.append(normalized.split()[0])
                raise AssertionError('Unexpected financial write during PREFREEZE')
    event.listen(engine, 'before_cursor_execute', financial_writes)
    def external_forbidden(*args, **kwargs):
        raise AssertionError('External provider/email I/O in recovery probe')
    try:
        with patch('requests.sessions.Session.request', external_forbidden), \
             patch('resend.Emails.send', external_forbidden), \
             patch.object(mod, '_paypal_get_access_token', external_forbidden), \
             patch.object(mod, '_paypal_create_order', external_forbidden), \
             patch.object(mod, '_paypal_capture_order', external_forbidden), \
             patch.object(mod, '_send_advisory_quote_email', external_forbidden), \
             patch.object(mod, '_PAYPAL_ENABLED', True), \
             patch.object(mod, '_stripe_available', True), \
             patch.object(mod, '_STRIPE_SECRET_KEY', 'sk_test_inert_ci'), \
             patch.object(mod, '_STRIPE_WEBHOOK_SECRET', 'whsec_inert_ci'):
            # Even simulated configured providers cannot bypass PREFREEZE.
            cli = app.test_client()
            health = cli.get('/healthz')
            assert health.status_code == 200
            assert health.get_json()['ok'] is True

            public = (
                ('GET', '/api/pago/info/CI_EXPIRED_SYNTHETIC_TOKEN'),
                ('POST', '/api/pago/iniciar/CI_EXPIRED_SYNTHETIC_TOKEN'),
                ('GET', '/api/pago/paypal/capture?request_id=6&token=fictional'),
                ('POST', '/api/webhooks/paypal'),
                ('POST', '/api/webhooks/stripe'),
            )
            for method, url in public:
                result = cli.open(url, method=method,
                                  data=b'{}' if method == 'POST' else None,
                                  content_type='application/json')
                assert result.status_code == 503, (url, result.status_code)
                assert result.headers['Cache-Control'] == 'no-store'
                assert SUSPENSION_MESSAGE in result.get_data(as_text=True)
                assert result.get_json()['code'] == 'advisory_financial_suspended'
            with cli.session_transaction() as session:
                session['_user_id'] = '1'
                session['_fresh'] = True
            for path in (
                '/api/admin/asesoramiento/solicitudes/6/enviar-presupuesto',
                '/api/admin/asesoramiento/solicitudes/6/mensaje',
            ):
                result = cli.post(path, json={'amount_euros': 200})
                assert result.status_code == 503, (path, result.status_code)
                assert result.headers['Cache-Control'] == 'no-store'
            static = cli.get('/pagar/CI_EXPIRED_SYNTHETIC_TOKEN')
            assert static.status_code == 200
            assert SUSPENSION_MESSAGE in static.get_data(as_text=True)
            assert 'iniciarPago' not in static.get_data(as_text=True)
            legacy = cli.get('/asesoramiento-fiscal-confirmado')
            assert legacy.status_code == 503
            assert legacy.headers['Cache-Control'] == 'no-store'
            assert 'no acredita' in legacy.get_data(as_text=True)
    finally:
        event.remove(engine, 'before_cursor_execute', financial_writes)
    assert not denied
print('S01 G04-R02 runtime PG18: HTTP health PASS; 7 financial endpoints fail closed; legacy and page neutral PASS; no DML/provider PASS')
"""


def main():
    _guard()
    assert "bootstrap_db.py" not in (ROOT / "Procfile").read_text()
    assert "startup_schema_gate.py && gunicorn " in (ROOT / "Procfile").read_text()
    _create_db(DB)
    try:
        # Wrong/empty DB must fail closed, with no implicit migration.
        _startup(DB, success=False)
        with _db_conn(DB) as conn, conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                           WHERE table_schema='public'""")
            assert cur.fetchone()[0] == 0
        # Maintenance migration exclusively inside CI ephemeral PG18.
        _bootstrap(DB)
        _startup(DB)
        _run(DB, SEED)
        baseline = _snapshot()
        assert baseline[1] == (0, 0, 0)
        assert sum(bool(row[5]) for row in baseline[0]) == 1

        # The approved release itself must continue to deny legacy money paths.
        _run(DB, HTTP_PROBE)
        assert _snapshot() == baseline

        # Simulate a failed cut where the revision is stale but data are intact.
        with _db_conn(DB) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE alembic_version SET version_num='v5w6x7y8z9a0'"
            )
        _startup(DB, success=False)
        assert _snapshot() == baseline
        with _db_conn(DB) as conn, conn.cursor() as cur:
            cur.execute("UPDATE alembic_version SET version_num=%s", (HEAD,))
        _startup(DB)
        assert _snapshot() == baseline

        # Fail shut on missing financial integrity CHECK, without repairing it.
        with _db_conn(DB) as conn, conn.cursor() as cur:
            cur.execute("""ALTER TABLE s01_stripe_checkout_attempts
                           DROP CONSTRAINT ck_s01_attempt_currency""")
        _startup(DB, success=False)
        assert _snapshot() == baseline
        print(
            "S01 G04-R02 recovery gate PG18: schema mismatch -> startup denied; "
            "approved head -> runtime finance blocked; history retained; "
            "missing CHECK -> denied; no implicit repair PASS"
        )
    finally:
        # All destructive cleanup operates ONLY on fixed ephemeral CI DB.
        conn = _db_conn("postgres")
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "DROP DATABASE IF EXISTS s01_recovery_runtime_ci WITH (FORCE)"
                )
        finally:
            conn.close()


if __name__ == "__main__":
    main()
