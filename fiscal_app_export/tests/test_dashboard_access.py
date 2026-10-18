"""Run dashboard/roles checks in a process without inherited provider secrets."""
import os
from pathlib import Path
import subprocess
import sys

def test_dashboard_authorization_offline(tmp_path):
    worker=Path(__file__).with_name('qa_dashboard_access.py')
    env={'PATH':os.defpath,'FLASK_ENV':'testing','SECRET_KEY':'workspace-fixture-only-key',
         'DATABASE_URL':'sqlite:///'+str(tmp_path/'workspace.sqlite'),
         'MPLCONFIGDIR':str(tmp_path/'mpl'),'PYTHONDONTWRITEBYTECODE':'1',
         'ADMIN_EMAILS':'fallback-admin@example.invalid',
         'FISCAL_ADVISOR_EMAILS':'fallback-advisor@example.invalid',
         'PROCESSING_ERROR_EMAILS_ENABLED':'false','ENABLE_ADVISORY_UPLOADS':'false'}
    script='''
import socket
from unittest.mock import patch
import pytest
def denied(*a,**kw):raise AssertionError('Dashboard fixture forbids network/DNS')
with patch.object(socket.socket,'connect',denied),patch.object(socket,'create_connection',denied),patch.object(socket,'getaddrinfo',denied):
    raise SystemExit(pytest.main(['-q','--disable-warnings',__import__('sys').argv[1]]))
'''
    r=subprocess.run([sys.executable,'-c',script,str(worker.resolve())],cwd=worker.parent.parent,
                     env=env,capture_output=True,text=True,timeout=180)
    assert r.returncode==0,r.stdout+r.stderr
    print('DASHBOARD_ACCESS_OFFLINE: '+r.stdout)
