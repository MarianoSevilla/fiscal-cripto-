"""CI-only synthetic PostgreSQL 18 contract for S01-R01 PayPal inventory.

Uses only a disposable database with synthetic rows, no real provider or backup.
No actual PayPal identifiers, customers, production URLs or credentials.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import psycopg2
from psycopg2 import sql, errors

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import s01_paypal_inventory_local as inventory  # noqa: E402

HOST = "127.0.0.1"
PORT = 5432
USER = "postgres"
PASSWORD = "ci-only-test-password"
DB = "s01_paypal_inventory_pg18_ci"


def _guard():
    if any(os.environ.get(key) != expected for key, expected in (
        ("GITHUB_ACTIONS", "true"),
        ("CI", "true"),
        ("FLASK_ENV", "testing"),
    )):
        raise RuntimeError("Only in GitHub CI with synthetic PostgreSQL 18")


def connect_admin():
    _guard()
    return psycopg2.connect(host=HOST, port=PORT, user=USER,
                            password=PASSWORD, dbname="postgres",
                            connect_timeout=5)


def create_database():
    conn = connect_admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            assert 180000 <= int(cur.fetchone()[0]) < 190000
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
    finally:
        conn.close()


def drop_database():
    conn = connect_admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DB)))
    finally:
        conn.close()


def test():
    _guard()
    create_database()
    try:
        conn = psycopg2.connect(
            host=HOST, port=PORT, user=USER, password=PASSWORD,
            dbname=DB, connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE alembic_version (version_num VARCHAR(32))
                """)
                cur.execute("INSERT INTO alembic_version VALUES ('v5w6x7y8z9a0')")
                cur.execute("""
                    CREATE TABLE fiscal_advisory_requests (
                        id INTEGER PRIMARY KEY,
                        paypal_order_id VARCHAR(64),
                        paypal_capture_id VARCHAR(64),
                        payment_provider VARCHAR(16),
                        amount_paid INTEGER,
                        currency VARCHAR(3),
                        paid_at TIMESTAMP,
                        status VARCHAR(30) NOT NULL,
                        is_test BOOLEAN,
                        stripe_checkout_session_id VARCHAR(255),
                        stripe_payment_intent_id VARCHAR(255),
                        quote_accepted_at TIMESTAMP
                    )
                """)
                cur.executemany("""
                    INSERT INTO fiscal_advisory_requests
                    (id, paypal_order_id, paypal_capture_id, payment_provider,
                     amount_paid, currency, paid_at, status, is_test,
                     stripe_checkout_session_id, stripe_payment_intent_id,
                     quote_accepted_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [
                    (1, "ORD_SYN_001", "CAP_SYN_001", "paypal", 26000,
                     "eur", "2026-10-01", "paid_received", False, None, None, None),
                    (2, "ORD_DUP_SYN", None, "paypal", None,
                     "eur", None, "quote_sent", False, None, None, None),
                    (3, None, "CAP_SYN_003", "paypal", None,
                     "eur", "2026-10-02", "paid_received", False, None, None, None),
                    (4, None, None, "paypal", None,
                     "eur", None, "refunded", True, None, None, None),
                    (5, None, None, "stripe", 19900,
                     "eur", "2026-10-03", "paid_received", False, "cs_test_fake", "pi_fake", None),
                    (6, None, None, None, 10000,
                     "eur", None, "paid_received", False, None, None, None),
                    (7, "ORD_DUP_SYN", None, "paypal", None,
                     "eur", None, "quote_sent", False, None, None, None),
                    (8, "", None, None, None,
                     "eur", None, "submitted", False, None, None, "2026-10-04"),
                    (9, "ORD_SYN_009", None, "stripe", None,
                     "usd", None, "quote_sent", False, None, None, None),
                ])
            conn.commit()
            conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
            summary = inventory.aggregate_local_only(conn)
            expected = {
                "expedientes_totales": 9,
                "expedientes_senal_paypal": 6,
                "paypal_orden_presente": 4,
                "paypal_captura_presente": 2,
                "paypal_orden_sin_captura": 3,
                "paypal_captura_sin_orden": 1,
                "paypal_proveedor_sin_ambos_ids": 1,
                "paypal_con_importe_local": 1,
                "paypal_con_paid_at": 2,
                "paypal_estado_paid_received": 2,
                "paypal_estado_refunded": 1,
                "paypal_sin_captura_con_senal_pago": 1,
                "paypal_senal_is_test": 1,
                "paypal_senal_no_test": 5,
                "paypal_divisa_no_eur_o_nula": 1,
                "paypal_id_orden_vacio_no_nulo": 1,
                "paypal_id_captura_vacio_no_nulo": 0,
                "paypal_ids_con_proveedor_stripe": 1,
                "pagado_sin_proveedor_ni_ids": 1,
                "aceptados_sin_proveedor_ni_ids": 1,
                "paypal_grupos_id_orden_repetidos": 1,
                "paypal_grupos_id_captura_repetidos": 0,
            }
            assert summary == expected, "Synthetic PayPal aggregate counts changed"
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE fiscal_advisory_requests SET amount_paid=0")
            except errors.ReadOnlySqlTransaction:
                conn.rollback()
            else:
                raise AssertionError("READ ONLY transaction permitted a DML operation")
            assert all(isinstance(x, int) for x in summary.values())
            assert not any("ORD_SYN" in str(v) or "CAP_SYN" in str(v)
                           for v in summary.values())
            print(
                "S01-R01 PostgreSQL 18 synthetic inventory: aggregates PASS; "
                "duplicate IDs PASS; evidence gaps PASS; "
                "transaction READ ONLY enforced PASS",
                flush=True,
            )
        finally:
            conn.close()
    finally:
        drop_database()


if __name__ == "__main__":
    test()
