"""S01-R01: inventario agregado PayPal desde copia local restaurada, nunca Live.

No conecta a Railway ni PayPal; no importa app.py; no captura órdenes,
no actualiza expedientes, ni exporta identificadores/PII ni SQL/logs.
Reutiliza validaciones de backup y entorno del ensayo S01 #45.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import shutil
import sys
import tempfile

import s01_rehearse_restored_backup as guard


PAYPAL_SIGNAL = (
    "(NULLIF(BTRIM(paypal_order_id), '') IS NOT NULL OR "
    "NULLIF(BTRIM(paypal_capture_id), '') IS NOT NULL OR "
    "LOWER(COALESCE(payment_provider, '')) = 'paypal')"
)
ORDER = "NULLIF(BTRIM(paypal_order_id), '') IS NOT NULL"
CAPTURE = "NULLIF(BTRIM(paypal_capture_id), '') IS NOT NULL"

# Only hardcoded aggregate columns can leave the isolated restored database.
COUNTS = [
    ("expedientes_totales", "TRUE"),
    ("expedientes_senal_paypal", PAYPAL_SIGNAL),
    ("paypal_orden_presente", f"{PAYPAL_SIGNAL} AND {ORDER}"),
    ("paypal_captura_presente", f"{PAYPAL_SIGNAL} AND {CAPTURE}"),
    ("paypal_orden_sin_captura", f"{PAYPAL_SIGNAL} AND {ORDER} AND NOT ({CAPTURE})"),
    ("paypal_captura_sin_orden", f"{PAYPAL_SIGNAL} AND {CAPTURE} AND NOT ({ORDER})"),
    ("paypal_proveedor_sin_ambos_ids", (
        "LOWER(COALESCE(payment_provider,'')) = 'paypal' "
        f"AND NOT ({ORDER}) AND NOT ({CAPTURE})"
    )),
    ("paypal_con_importe_local", f"{PAYPAL_SIGNAL} AND amount_paid IS NOT NULL"),
    ("paypal_con_paid_at", f"{PAYPAL_SIGNAL} AND paid_at IS NOT NULL"),
    ("paypal_estado_paid_received", f"{PAYPAL_SIGNAL} AND status = 'paid_received'"),
    ("paypal_estado_refunded", f"{PAYPAL_SIGNAL} AND status = 'refunded'"),
    ("paypal_sin_captura_con_senal_pago", (
        f"{PAYPAL_SIGNAL} AND NOT ({CAPTURE}) "
        "AND (amount_paid IS NOT NULL OR paid_at IS NOT NULL "
        "OR status IN ('paid_received', 'refunded'))"
    )),
    ("paypal_senal_is_test", f"{PAYPAL_SIGNAL} AND is_test IS TRUE"),
    ("paypal_senal_no_test", f"{PAYPAL_SIGNAL} AND is_test IS NOT TRUE"),
    ("paypal_divisa_no_eur_o_nula", (
        f"{PAYPAL_SIGNAL} AND (currency IS NULL OR LOWER(currency) <> 'eur')"
    )),
    ("paypal_id_orden_vacio_no_nulo", (
        "paypal_order_id IS NOT NULL AND NULLIF(BTRIM(paypal_order_id),'') IS NULL"
    )),
    ("paypal_id_captura_vacio_no_nulo", (
        "paypal_capture_id IS NOT NULL AND NULLIF(BTRIM(paypal_capture_id),'') IS NULL"
    )),
    ("paypal_ids_con_proveedor_stripe", (
        f"({ORDER} OR {CAPTURE}) "
        "AND LOWER(COALESCE(payment_provider,'')) = 'stripe'"
    )),
    ("pagado_sin_proveedor_ni_ids", (
        "(amount_paid IS NOT NULL OR paid_at IS NOT NULL "
        "OR status IN ('paid_received', 'refunded')) "
        "AND payment_provider IS NULL "
        f"AND NOT ({ORDER}) AND NOT ({CAPTURE}) "
        "AND stripe_checkout_session_id IS NULL "
        "AND stripe_payment_intent_id IS NULL"
    )),
    ("aceptados_sin_proveedor_ni_ids", (
        "quote_accepted_at IS NOT NULL AND payment_provider IS NULL "
        f"AND NOT ({ORDER}) AND NOT ({CAPTURE}) "
        "AND stripe_checkout_session_id IS NULL "
        "AND stripe_payment_intent_id IS NULL"
    )),
]


def build_aggregate_sql() -> str:
    clauses = [
        f"COUNT(*) FILTER (WHERE {condition}) AS {name}"
        for name, condition in COUNTS
    ]
    return "SELECT " + ", ".join(clauses) + " FROM public.fiscal_advisory_requests"


def duplicated_refs_sql(column: str) -> str:
    if column not in ("paypal_order_id", "paypal_capture_id"):
        raise ValueError("Only vetted PayPal reference columns allowed")
    return (
        "SELECT COUNT(*) FROM ("
        f"SELECT {column} FROM public.fiscal_advisory_requests "
        f"WHERE NULLIF(BTRIM({column}), '') IS NOT NULL "
        f"GROUP BY {column} HAVING COUNT(*) > 1"
        ") duplicate_reference_groups"
    )


def aggregate_local_only(conn) -> dict[str, int]:
    """All returned values are COUNTs; transaction must be READ ONLY."""
    required = {
        "paypal_order_id", "paypal_capture_id", "payment_provider",
        "amount_paid", "currency", "paid_at", "status", "is_test",
        "stripe_checkout_session_id", "stripe_payment_intent_id",
        "quote_accepted_at",
    }
    found = set(guard.columns(conn, "fiscal_advisory_requests"))
    if not required.issubset(found):
        raise guard.RehearsalError("El esquema del backup no contiene los campos auditados")
    if guard.version(conn) != guard.PRE_REV:
        raise guard.RehearsalError("Revisión Alembic inicial inesperada; detener inventario")
    with conn.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        if cursor.fetchone()[0] != "on":
            raise guard.RehearsalError("La transacción no es READ ONLY")
        cursor.execute(build_aggregate_sql())
        counts = cursor.fetchone()
        if counts is None or len(counts) != len(COUNTS):
            raise guard.RehearsalError("Resultados agregados incompletos")
        result = {name: count for (name, _), count in zip(COUNTS, counts)}
        for col, label in (
            ("paypal_order_id", "orden"),
            ("paypal_capture_id", "captura"),
        ):
            cursor.execute(duplicated_refs_sql(col))
            result[f"paypal_grupos_id_{label}_repetidos"] = cursor.fetchone()[0]
    total = result["expedientes_totales"]
    if any(type(value) is not int or value < 0 or value > total
           for value in result.values()):
        raise guard.RehearsalError("Recuento inválido: inventario rechazado")
    if (result["paypal_senal_is_test"] + result["paypal_senal_no_test"]
            != result["expedientes_senal_paypal"]):
        raise guard.RehearsalError("Totales de expedientes PayPal inconsistentes")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--sha-file", required=True, type=Path)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    if os.geteuid() == 0 or os.environ.get("GITHUB_ACTIONS") == "true":
        raise guard.RehearsalError("Prohibido como root o en CI")
    if any(k.startswith(("RAILWAY_", "STRIPE_", "PAYPAL_"))
           for k in os.environ):
        # Local shell may contain provider credentials; never proceed with them.
        raise guard.RehearsalError("Entorno con variables de proveedor; inventario denegado")

    original_hash = guard.expected_digest(args.backup, args.sha_file)
    guard.checked_archive(args.backup, original_hash)
    binaries = guard.verify_pg18(args.pg_bin)
    guard.run_step(
        "Inspección pg_restore local",
        [binaries["pg_restore"], "--list", str(args.backup)],
        env=guard.clean_environment(), timeout=60,
    )
    print("S01 R01 PRECHECK: backup privado, SHA-256 y PostgreSQL 18 OK", flush=True)
    if args.preflight_only:
        return

    before_umask = os.umask(0o077)
    root = None
    data = None
    started = False
    old_handlers = {}
    try:
        root = Path(tempfile.mkdtemp(prefix="s01-paypal-inventory-"))
        data = root / "pgdata"
        sock = root / "socket"
        sock.mkdir(mode=0o700)
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(
                sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
            )
        guard.run_step(
            "PostgreSQL 18 initdb",
            [binaries["initdb"], "-D", str(data), "-U", guard.DB_USER,
             "--encoding=UTF8", "--locale=C", "--auth-local=trust",
             "--auth-host=reject", "--no-instructions"],
            env=guard.clean_environment(),
        )
        guard.run_step(
            "Arranque PG18 local Unix-socket-only",
            [binaries["pg_ctl"], "-D", str(data), "-l", str(root / "postgres.log"),
             "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -p {guard.PORT}",
             "-w", "start"],
            env=guard.clean_environment(),
        )
        started = True
        pg_env = guard.pg_environment(sock, root)
        guard.run_step(
            "Creación DB local efímera",
            [binaries["psql"], "-X", "-w", "-v", "ON_ERROR_STOP=1",
             "-d", "postgres", "-c", f"CREATE DATABASE {guard.DB_NAME}"],
            env=pg_env,
        )
        guard.run_step(
            "Restauración íntegra sin propietarios externos",
            [binaries["pg_restore"], "--exit-on-error",
             "--single-transaction", "--no-owner", "--no-acl",
             "-d", guard.DB_NAME, str(args.backup)],
            env=pg_env, timeout=600,
        )
        print("S01 R01 RESTORE: PostgreSQL temporal restaurado", flush=True)

        conn = guard.connect_local(sock)
        try:
            conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
            with conn.cursor() as cursor:
                cursor.execute("SHOW data_directory")
                actual = cursor.fetchone()[0]
                if Path(actual).resolve() != data.resolve():
                    raise guard.RehearsalError("Conexión no corresponde al PG efímero")
            result = aggregate_local_only(conn)
        finally:
            conn.rollback()
            conn.close()

        print("S01 R01 INVENTARIO LOCAL (solo recuentos; sin IDs):", flush=True)
        for label, _ in COUNTS:
            print(f"S01 R01 {label}: {result[label]}", flush=True)
        for label in ("paypal_grupos_id_orden_repetidos",
                      "paypal_grupos_id_captura_repetidos"):
            print(f"S01 R01 {label}: {result[label]}", flush=True)
        print(
            "S01 R01: PASS LOCAL — NOTA: cifras del backup, no del proveedor "
            "ni del estado actual; G05 continúa ABIERTO",
            flush=True,
        )
    finally:
        for sig, old in old_handlers.items():
            signal.signal(sig, old)
        if root is not None:
            needs_stop = started or (data / "postmaster.pid").exists()
            stopped = not needs_stop
            if needs_stop:
                try:
                    guard.run_step(
                        "Detener PostgreSQL temporal",
                        [binaries["pg_ctl"], "-D", str(data),
                         "-m", "fast", "-w", "stop"],
                        env=guard.clean_environment(), timeout=45,
                    )
                    stopped = True
                except guard.RehearsalError:
                    print("S01 R01 AVISO: servidor temporal no detenido; "
                          "directorio privado conservado: " + str(root),
                          file=sys.stderr)
            if stopped:
                shutil.rmtree(root)
        os.umask(before_umask)


if __name__ == "__main__":
    try:
        main()
    except (guard.RehearsalError, KeyboardInterrupt) as exc:
        # Never echo driver messages/SQL/values.
        print("S01 R01 NO-GO: " + str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print("S01 R01 NO-GO: error interno "
              + type(exc).__name__ + "; contenido protegido", file=sys.stderr)
        sys.exit(1)
