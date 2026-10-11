"""U03 runs in a fresh process: no inherited DB, credentials or network.

The previous automatic-link expectation is replaced by the rejection tests in
qa_google_oauth_identity.py. Business mocks and real signed OIDC tests are
separate there; all identities and tokens are synthetic.
"""
import os
from pathlib import Path
import subprocess
import sys


def test_google_oauth_identity_isolated(tmp_path):
    worker = Path(__file__).with_name("qa_google_oauth_identity.py")
    env = {
        "PATH": os.defpath,
        "FLASK_ENV": "testing",
        "SECRET_KEY": "u03-fictional-session-key",
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "u03.sqlite"),
        "MPLCONFIGDIR": str(tmp_path / "mpl"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GOOGLE_CLIENT_ID": "fictional-u03-client",
        "GOOGLE_CLIENT_SECRET": "fictional-u03-secret",
        "ADMIN_EMAILS": "",
        "FISCAL_ADVISOR_EMAILS": "",
        "PROCESSING_ERROR_EMAILS_ENABLED": "false",
    }
    script = """
import socket
from unittest.mock import patch
import pytest

def forbidden(*args, **kwargs):
    raise AssertionError('U03 forbids network and DNS')
with patch.object(socket.socket, 'connect', forbidden), \\
     patch.object(socket, 'create_connection', forbidden), \\
     patch.object(socket, 'getaddrinfo', forbidden):
    raise SystemExit(pytest.main(['-q', '--disable-warnings', __import__('sys').argv[1]]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(worker.resolve())],
        cwd=worker.parent.parent, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
