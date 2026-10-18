"""Keep the production limiter active in a fresh, offline test process."""
import os
from pathlib import Path
import subprocess
import sys


def test_session_rate_limit_offline(tmp_path):
    worker = Path(__file__).with_name('qa_me_rate_limit.py')
    env = {
        'PATH': os.defpath, 'FLASK_ENV': 'testing',
        'SECRET_KEY': 'me-rate-fixture-only-not-a-production-key',
        'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'session-rate.sqlite'),
        'MPLCONFIGDIR': str(tmp_path / 'mpl'), 'PYTHONDONTWRITEBYTECODE': '1',
        'ADMIN_EMAILS': '', 'FISCAL_ADVISOR_EMAILS': '',
        'PROCESSING_ERROR_EMAILS_ENABLED': 'false',
        'ENABLE_ADVISORY_UPLOADS': 'false',
    }
    script = '''
import socket
from unittest.mock import patch
import pytest
def denied(*args, **kwargs):
    raise AssertionError('Session rate-limit fixture forbids network/DNS')
with patch.object(socket.socket, 'connect', denied), patch.object(socket, 'create_connection', denied), patch.object(socket, 'getaddrinfo', denied):
    raise SystemExit(pytest.main(['-q', '--disable-warnings', __import__('sys').argv[1]]))
'''
    result = subprocess.run(
        [sys.executable, '-c', script, str(worker.resolve())],
        cwd=worker.parent.parent, env=env,
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print('ME_RATE_LIMIT_OFFLINE: ' + result.stdout)
