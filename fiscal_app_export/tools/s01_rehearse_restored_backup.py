"""S01: rehearsal of a locally held PostgreSQL production backup, never production.

Runs exclusively on the owner's Mac (or other non-root local machine) with
PostgreSQL 18 installed. Makes a new private Unix-socket-only PG cluster,
restores an authenticated custom-format backup, exercises the ACTUAL
bootstrap_db.py twice and verifies every original row via local fingerprints.
No backup, row, log, fingerprint, password or external DB URL is uploaded.
DO NOT run via GitHub Actions; do not run against Railway.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote

BASE = Path(__file__).resolve().parents[1]
DB_NAME = "s01_local_rehearsal"
DB_USER = "postgres"
PORT = 55435
PRE_REV = "v5w6x7y8z9a0"
POST_REV = "z9a0b1c2d3e4"
NEW_TABLES = (
    "s01_stripe_checkout_attempts",
    "s01_stripe_event_receipts",
    "s01_stripe_notification_outbox",
)
NEW_COLUMNS = ("rafa_fee_cents", "commission_cents", "commission_rate_bps")


class RehearsalError(RuntimeError):
    pass


def checked_archive(backup: Path, expected: str) -> None:
    """Refuse symlinks, non-private dumps, wrong hashes and invalid formats."""
    if not backup.is_absolute() or backup.is_symlink():
        raise RehearsalError("El backup debe ser una ruta absoluta sin enlaces simbólicos")
    try:
        meta = backup.stat()
    except OSError:
        raise RehearsalError("No se encuentra el archivo de backup") from None
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid():
        raise RehearsalError("Se exige un archivo regular propiedad del usuario")
    if meta.st_mode & 0o077:
        raise RehearsalError("El backup debe tener permisos privados (chmod 600)")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise RehearsalError("Se exige SHA-256 verificado de la copia original")
    with backup.open("rb") as f:
        magic = f.read(5)
        f.seek(0)
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if magic != b"PGDMP":
        raise RehearsalError("El archivo no es un pg_dump custom válido")
    if digest.lower() != expected.lower():
        raise RehearsalError("SHA-256 incorrecto: no se utilizará la copia")


def expected_digest(backup: Path, sha_file: Path) -> str:
    if not sha_file.is_absolute() or sha_file.is_symlink():
        raise RehearsalError("Checksum: ruta absoluta sin symlink obligatoria")
    try:
        lines = sha_file.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        raise RehearsalError("No se puede leer el checksum previamente registrado") from None
    if len(lines) != 1:
        raise RehearsalError("El checksum debe tener una sola línea")
    value = lines[0].strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?(.+))?", value)
    if not match:
        raise RehearsalError("Formato de checksum SHA-256 no reconocido")
    recorded_name = match.group(2)
    if recorded_name and Path(recorded_name).name != backup.name:
        raise RehearsalError("El checksum corresponde a otro nombre de archivo")
    return match.group(1)


def clean_environment() -> dict[str, str]:
    """No inherited URLs, PGPASSWORD, provider keys, proxies or cloud tokens."""
    allowed = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def pg_environment(socket_dir: Path, work: Path, *, app=False) -> dict[str, str]:
    env = clean_environment()
    env.update(
        PGHOST=str(socket_dir), PGPORT=str(PORT), PGUSER=DB_USER,
        PGDATABASE=DB_NAME, PGSSLMODE="disable", PGCONNECT_TIMEOUT="5",
        PGPASSFILE="/dev/null",
    )
    if app:
        env.update(
            FLASK_ENV="testing",
            SECRET_KEY="S01-OFFLINE-REHEARSAL-ONLY-NEVER-USE-LIVE",
            DATABASE_URL=(
                "postgresql+psycopg2://postgres@/" + DB_NAME +
                "?host=" + quote(str(socket_dir), safe="") +
                "&port=" + str(PORT)
            ),
            RESEND_API_KEY="", GOOGLE_CLIENT_ID="",
            GOOGLE_CLIENT_SECRET="", STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="", APP_BASE_URL="https://s01-rehearsal.invalid",
            MPLCONFIGDIR=str(work / "mpl"),
            PYTHONPATH=str(work / "python_guard"),
        )
    return env


def run_step(label: str, args: list[str], *, env: dict[str, str],
             cwd: Path | None = None, timeout=240) -> None:
    try:
        result = subprocess.run(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RehearsalError(f"{label}: error de ejecución o timeout") from None
    if result.returncode:
        # Do not echo log output: it may contain restored business data.
        raise RehearsalError(f"{label}: fallo (código {result.returncode})")


def verify_pg18(bin_dir: Path) -> dict[str, str]:
    tools = {}
    if not bin_dir.is_absolute():
        raise RehearsalError("--pg-bin requiere ruta absoluta PostgreSQL 18")
    for name in ("initdb", "pg_ctl", "psql", "pg_restore"):
        path = bin_dir / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RehearsalError(f"Falta binario PostgreSQL: {name}")
        result = subprocess.run(
            [str(path), "--version"], env=clean_environment(),
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode or re.search(r"\b18\.\d+\b", result.stdout) is None:
            raise RehearsalError(f"{name}: versión distinta de PostgreSQL 18")
        tools[name] = str(path)
    return tools


def deny_tcp_python_network(work: Path) -> None:
    guard = work / "python_guard"
    guard.mkdir(mode=0o700)
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "_orig_socket = socket.socket\n"
        # SSL subclasses socket.socket during import. The guard must remain
        # a class; replacing socket.socket with a function crashes asyncio.
        "class _LocalSocket(_orig_socket):\n"
        "    def __init__(self, family=socket.AF_INET, "
        "type=socket.SOCK_STREAM, proto=0, fileno=None):\n"
        "        if family != socket.AF_UNIX:\n"
        "            raise OSError('S01 rehearsal blocks all IP networking')\n"
        "        super().__init__(family, type, proto, fileno)\n"
        "socket.socket = _LocalSocket\n"
        "def _blocked_getaddrinfo(*args, **kwargs):\n"
        "    raise OSError('S01 rehearsal blocks DNS')\n"
        "socket.getaddrinfo = _blocked_getaddrinfo\n",
        encoding="utf-8",
    )


def connect_local(socket_dir: Path):
    # Not imported until the archive has been verified; same venv as app.
    import psycopg2
    return psycopg2.connect(
        host=str(socket_dir), port=PORT, dbname=DB_NAME,
        user=DB_USER, connect_timeout=5, sslmode="disable",
    )


def version(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise RehearsalError("Alembic: se exige una única revisión")
        return rows[0][0]


def columns(conn, name: str) -> tuple[str, ...]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position", (name,),
        )
        return tuple(row[0] for row in cursor.fetchall())


def table_fingerprint(conn, table: str, previous_cols: tuple[str, ...]):
    """All original columns/rows; only count+digest leave PostgreSQL."""
    from psycopg2 import sql
    if not previous_cols:
        raise RehearsalError("Tabla histórica sin columnas")
    q = sql.SQL(
        "SELECT count(*), coalesce(md5(string_agg("
        "md5(row_to_json(src)::text), ',' ORDER BY "
        "md5(row_to_json(src)::text))), md5('')) "
        "FROM (SELECT {} FROM {}) AS src"
    ).format(
        sql.SQL(", ").join(sql.Identifier(col) for col in previous_cols),
        sql.Identifier("public", table),
    )
    with conn.cursor() as cursor:
        cursor.execute(q)
        return cursor.fetchone()


def snapshot(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' AND tablename <> 'alembic_version' "
            "ORDER BY tablename"
        )
        names = [x[0] for x in cursor.fetchall()]
    if "fiscal_advisory_requests" not in names or len(names) < 10:
        raise RehearsalError("Esquema original incompleto: restauración denegada")
    if any(name in names for name in NEW_TABLES):
        raise RehearsalError("La copia ya contiene tablas S01")
    if any(col in columns(conn, "fiscal_advisory_requests") for col in NEW_COLUMNS):
        raise RehearsalError("La copia ya contiene las columnas S01")
    return {
        name: (col_list, *table_fingerprint(conn, name, col_list))
        for name in names
        for col_list in (columns(conn, name),)
    }


def verify_migration(conn, before):
    if version(conn) != POST_REV:
        raise RehearsalError("Alembic no alcanzó el head S01 esperado")
    for table, (col_list, old_count, old_digest) in before.items():
        existing = columns(conn, table)
        if not set(col_list).issubset(existing):
            raise RehearsalError("Desapareció una columna histórica")
        count, digest = table_fingerprint(conn, table, col_list)
        if (count, digest) != (old_count, old_digest):
            raise RehearsalError("Algún registro histórico ha cambiado")
    with conn.cursor() as cursor:
        for name in NEW_TABLES:
            cursor.execute("SELECT to_regclass(%s)", ("public." + name,))
            if cursor.fetchone()[0] is None:
                raise RehearsalError("Falta una tabla S01")
            from psycopg2 import sql
            cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier("public", name)
            ))
            if cursor.fetchone()[0]:
                raise RehearsalError("Las tablas S01 no deben contener backfill")
        if not set(NEW_COLUMNS).issubset(columns(conn, "fiscal_advisory_requests")):
            raise RehearsalError("Faltan columnas de desglose S01")
        cursor.execute(
            "SELECT COUNT(*) FROM fiscal_advisory_requests "
            "WHERE rafa_fee_cents IS NOT NULL OR commission_cents IS NOT NULL "
            "OR commission_rate_bps IS NOT NULL"
        )
        if cursor.fetchone()[0]:
            raise RehearsalError("La migración inventó comisiones históricas")

        # CREATE TABLE IF NOT EXISTS alone cannot certify schema equivalence:
        # app.py runs db.create_all() on import before Alembic upgrades.
        expected_constraints = {
            "s01_stripe_checkout_attempts": {
                "s01_stripe_checkout_attempts_pkey",
                "uq_s01_attempt_advisory", "ck_s01_checkout_status",
                "ck_s01_attempt_amount", "ck_s01_attempt_currency",
            },
            "s01_stripe_event_receipts": {
                "s01_stripe_event_receipts_pkey",
            },
            "s01_stripe_notification_outbox": {
                "s01_stripe_notification_outbox_pkey",
                "uq_s01_outbox_attempt_kind", "ck_s01_outbox_kind",
                "ck_s01_outbox_status",
            },
        }
        for table, required in expected_constraints.items():
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass",
                ("public." + table,),
            )
            actual = {name for (name,) in cursor.fetchall()}
            if not required.issubset(actual):
                raise RehearsalError("Faltan constraints de integridad S01")
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename IN %s",
            (NEW_TABLES,),
        )
        indexes = {name for (name,) in cursor.fetchall()}
        if not {"ix_s01_attempt_status", "ix_s01_outbox_status"}.issubset(indexes):
            raise RehearsalError("Faltan índices obligatorios S01")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename <> 'alembic_version'"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}
        expected_tables = set(before) | set(NEW_TABLES)
        if actual_tables != expected_tables:
            raise RehearsalError("Tablas inesperadas o desaparecidas tras el upgrade")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--sha-file", required=True, type=Path)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    if os.geteuid() == 0:
        raise RehearsalError("Está prohibida la ejecución como root")
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RAILWAY_ENVIRONMENT"):
        raise RehearsalError("No ejecutar sobre infraestructura CI o Railway")

    digest = expected_digest(args.backup, args.sha_file)
    checked_archive(args.backup, digest)
    if not (BASE / "bootstrap_db.py").is_file():
        raise RehearsalError("Se exige un checkout local de la aplicación S01")
    tools = verify_pg18(args.pg_bin)
    run_step("Inspección de formato del archivo",
             [tools["pg_restore"], "--list", str(args.backup)],
             env=clean_environment(), timeout=60)
    print("S01 PRECHECK: backup privado, formato custom, SHA-256 y PG18 OK", flush=True)
    if args.preflight_only:
        return

    # No inherited connection string ever reaches any subprocess. All DB ops
    # are restricted to a newly initialized Unix-socket-only local cluster.
    original_umask = os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="s01-local-rehearsal-"))
    data = root / "pgdata"
    sock = root / "socket"
    sock.mkdir(mode=0o700)
    (root / "mpl").mkdir(mode=0o700)
    started = False
    old_handlers = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        run_step("initdb",
                 [tools["initdb"], "-D", str(data), "-U", DB_USER,
                  "--encoding=UTF8", "--locale=C",
                  "--auth-local=trust", "--auth-host=reject", "--no-instructions"],
                 env=clean_environment())
        run_step("Arranque PostgreSQL sin TCP",
                 [tools["pg_ctl"], "-D", str(data), "-l", str(root / "postgres.log"),
                  "-o", f"-c listen_addresses= -c unix_socket_directories={sock} -p {PORT}",
                  "-w", "start"], env=clean_environment())
        started = True
        pg_env = pg_environment(sock, root)
        run_step("Creación de base local",
                 [tools["psql"], "-X", "-w", "-v", "ON_ERROR_STOP=1",
                  "-d", "postgres", "-c", f"CREATE DATABASE {DB_NAME}"],
                 env=pg_env)
        run_step("pg_restore transaccional",
                 [tools["pg_restore"], "--exit-on-error", "--single-transaction",
                  "--no-owner", "--no-acl", "-d", DB_NAME, str(args.backup)],
                 env=pg_env, timeout=600)
        with connect_local(sock) as conn:
            if version(conn) != PRE_REV:
                raise RehearsalError("Revisión inicial distinta de v5w6x7y8z9a0")
            before = snapshot(conn)
        print("S01 RESTORE: copia restaurada y revisión inicial OK", flush=True)
        deny_tcp_python_network(root)
        app_env = pg_environment(sock, root, app=True)
        for repetition in (1, 2):
            run_step(
                f"bootstrap_db.py pasada {repetition}",
                [sys.executable, str(BASE / "bootstrap_db.py")],
                env=app_env, cwd=BASE, timeout=600,
            )
            with connect_local(sock) as conn:
                verify_migration(conn, before)
            print(f"S01 UPGRADE {repetition}: Alembic, datos históricos y comisión OK",
                  flush=True)
        print("S01 REHEARSAL: PASS (local-only, sin datos expuestos)", flush=True)
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        # pg_ctl can start the server and then fail/timed out before the
        # start command returns. Never remove PGDATA while a postmaster may
        # still exist, even if our local started flag remained false.
        needs_stop = started or (data / "postmaster.pid").exists()
        stopped = not needs_stop
        if needs_stop:
            try:
                run_step("Detención PostgreSQL",
                         [tools["pg_ctl"], "-D", str(data), "-m", "fast", "-w", "stop"],
                         env=clean_environment(), timeout=45)
                stopped = True
            except RehearsalError:
                print("ATENCIÓN: PostgreSQL no se detuvo; directorio privado conservado: "
                      + str(root), file=sys.stderr)
        if stopped:
            shutil.rmtree(root)
        os.umask(original_umask)


if __name__ == "__main__":
    try:
        main()
    except (RehearsalError, KeyboardInterrupt) as exc:
        print(f"S01 REHEARSAL: NO-GO: {exc}", file=sys.stderr)
        sys.exit(1)
