"""Clean subprocess: synthetic credentials, ephemeral SQLite, all network denied."""
import os
from pathlib import Path
import subprocess
import sys


def run_worker(database_url, tmp_path, postgres=False):
    worker = Path(__file__).with_name('qa_advisory_prefreeze.py')
    env = {'PATH': os.defpath, 'FLASK_ENV': 'testing',
           'SECRET_KEY': 'prefreeze-fictional-session-key', 'DATABASE_URL': database_url,
           'MPLCONFIGDIR': str(tmp_path / 'mpl'), 'PYTHONDONTWRITEBYTECODE': '1',
           'ADMIN_EMAILS': '', 'FISCAL_ADVISOR_EMAILS': '',
           'PROCESSING_ERROR_EMAILS_ENABLED': 'false'}
    script = """
import socket, sys
from unittest.mock import patch
import pytest
original = socket.socket.connect
def forbidden(self, address):
    if sys.argv[2] == 'postgres' and address in [('127.0.0.1', 5432), ('localhost', 5432)]:
        return original(self, address)
    raise AssertionError('PREFREEZE forbids external network')
with patch.object(socket.socket, 'connect', forbidden):
    raise SystemExit(pytest.main(['-q', '--disable-warnings', sys.argv[1]]))
"""
    proc = subprocess.run([sys.executable, '-c', script, str(worker.resolve()),
                           'postgres' if postgres else 'sqlite'], cwd=worker.parent.parent,
                          env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    print(proc.stdout)


def test_advisory_prefreeze_isolated(tmp_path):
    run_worker('sqlite:///' + str(tmp_path / 'prefreeze.sqlite'), tmp_path)
