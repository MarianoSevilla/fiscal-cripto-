"""Run auth regressions in a fresh, offline process and temporary SQLite DB."""
import os
from pathlib import Path
import subprocess
import sys

def test_auth_flow_isolated(tmp_path):
    worker = Path(__file__).with_name('qa_auth_hardening.py')
    env = {
        'PATH': os.defpath, 'FLASK_ENV': 'testing',
        'SECRET_KEY': 'auth-fixture-key-not-a-production-secret',
        'DATABASE_URL': 'sqlite:///' + str(tmp_path/'auth.sqlite'),
        'MPLCONFIGDIR': str(tmp_path/'mpl'), 'PYTHONDONTWRITEBYTECODE': '1',
        'ADMIN_EMAILS': '', 'FISCAL_ADVISOR_EMAILS': '',
        'PROCESSING_ERROR_EMAILS_ENABLED': 'false',
    }
    script = '''
import socket
from unittest.mock import patch
import pytest
def forbidden(*a, **kw):
    raise AssertionError('Auth tests forbid network and DNS')
with patch.object(socket.socket, 'connect', forbidden), patch.object(socket, 'create_connection', forbidden), patch.object(socket, 'getaddrinfo', forbidden):
    raise SystemExit(pytest.main(['-q','--disable-warnings',__import__('sys').argv[1]]))
'''
    r = subprocess.run([sys.executable,'-c',script,str(worker.resolve())],
        cwd=worker.parent.parent,env=env,capture_output=True,text=True,timeout=180)
    assert r.returncode == 0, r.stdout+r.stderr
    print('AUTH_HARDENING_OFFLINE: '+r.stdout)
