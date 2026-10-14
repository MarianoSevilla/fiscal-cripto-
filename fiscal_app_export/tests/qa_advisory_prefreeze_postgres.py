"""CI-only PostgreSQL 18 test database, never Railway or inherited credentials."""
from pathlib import Path
import tempfile
import psycopg2
from test_advisory_prefreeze import run_worker

conn = psycopg2.connect(host='127.0.0.1', port=5432, user='postgres',
                       password='ci-only-test-password', dbname='postgres')
conn.autocommit = True
try:
    with conn.cursor() as cur:
        cur.execute('CREATE DATABASE prefreeze_ci')
    with tempfile.TemporaryDirectory() as path:
        run_worker('postgresql+psycopg2://postgres:ci-only-test-password@127.0.0.1:5432/prefreeze_ci',
                   Path(path), postgres=True)
finally:
    with conn.cursor() as cur:
        cur.execute('DROP DATABASE IF EXISTS prefreeze_ci WITH (FORCE)')
    conn.close()
