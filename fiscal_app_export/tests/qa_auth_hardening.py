"""Real Flask/bcrypt, synthetic identities, no providers or production I/O."""
from datetime import datetime,timedelta
import hashlib
from unittest.mock import patch
import pytest
import app as module
from app import app,db
from models import User
from auth_flow import safe_auth_next

PASSWORD='A fictional password 2026!'

@pytest.fixture(autouse=True)
def isolate():
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    app.config.update(TESTING=True,RATELIMIT_ENABLED=False,SESSION_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        with patch.object(module,'_send_verification_email',return_value=True), patch.object(module,'_send_password_reset_email',return_value=True):
            yield
        db.session.remove();db.drop_all()

def person(verified=True):
    u=User(email='person@example.invalid',full_name='Persona ficticia',
        email_verified_at=datetime.utcnow() if verified else None)
    u.set_password(PASSWORD);db.session.add(u);db.session.commit();return u

def login(c,password=PASSWORD,**extra):
    return c.post('/api/login',json={'email':'person@example.invalid','password':password,**extra})

@pytest.mark.parametrize('bad',['//example.invalid','/\\example.invalid','/%2fexample.invalid','/%252fexample.invalid','https://example.invalid','/\n/evil','/login','/signup?next=/login',None,5])
def test_external_next_rejected(bad):
    assert safe_auth_next(bad)=='/dashboard'

def test_internal_next_preserved():
    assert safe_auth_next('/pedir-asesoramiento?origen=web')=='/pedir-asesoramiento?origen=web'

def test_unverified_has_no_session_or_private_access():
    person(False);c=app.test_client();r=login(c)
    assert r.json['pending_verification']
    assert c.get('/api/me').json=={'user':None}
    assert c.get('/dashboard').status_code==302

def test_existing_short_password_still_works():
    u=person();u.set_password('legacy8!');db.session.commit()
    c=app.test_client();assert login(c,'legacy8!').status_code==200
    assert c.get('/api/me').json['user']['email']==u.email

def test_reset_revokes_sessions_and_remember_and_consumes_token():
    u=person();a=app.test_client();b=app.test_client()
    assert login(a).status_code==login(b,remember=True).status_code==200
    token='synthetic-reset-token';u.password_reset_token_hash=hashlib.sha256(token.encode()).hexdigest()
    u.password_reset_expires_at=datetime.utcnow()+timedelta(hours=1);db.session.commit()
    payload={'token':token,'password':'A different password 2026!','confirm_password':'A different password 2026!'}
    assert app.test_client().post('/api/reset-password',json=payload).status_code==200
    assert a.get('/api/me').json=={'user':None}
    b.delete_cookie('session')
    assert b.get('/api/me').json=={'user':None}
    assert app.test_client().post('/api/reset-password',json=payload).status_code==400
    assert login(app.test_client()).status_code==401
    assert login(app.test_client(),payload['password']).status_code==200

def test_change_revokes_current_and_other_sessions():
    person();a=app.test_client();b=app.test_client();login(a);login(b)
    r=a.post('/api/change-password',json={'current_password':PASSWORD,'new_password':'A replacement password 2026!'})
    assert r.status_code==200
    assert a.get('/api/me').json==b.get('/api/me').json=={'user':None}

def test_old_numeric_and_tampered_sessions_rejected():
    u=person()
    for identity in [str(u.id),u.get_id()[:-1]+'x','bad',None]:
        c=app.test_client()
        with c.session_transaction() as s:s['_user_id']=identity
        assert c.get('/api/me').json=={'user':None}

def test_disabled_account_loses_session():
    u=person();c=app.test_client();login(c);u.is_active=False;db.session.commit()
    assert c.get('/api/me').json=={'user':None}

def test_registration_and_resend_do_not_disclose_accounts():
    c=app.test_client();payload={'full_name':'Persona ficticia','email':'new@example.invalid','password':PASSWORD}
    first=c.post('/api/register',json=payload);second=c.post('/api/register',json=payload)
    assert first.status_code==second.status_code==201 and first.json==second.json
    missing=c.post('/api/resend-verification',json={'email':'missing@example.invalid'})
    pending=c.post('/api/resend-verification',json={'email':payload['email']})
    assert missing.json==pending.json

@pytest.mark.parametrize('password',['short-pass','a'*73,'á'*40])
def test_new_password_boundaries(password):
    assert not module._validar_password(password)[0]
    assert app.test_client().post('/api/register',json={'email':'new@example.invalid','full_name':'Ficticio','password':password}).status_code==400

def test_valid_unicode_and_oversized_login_do_not_crash():
    u=person();u.set_password('á'*20);db.session.commit();c=app.test_client()
    assert login(c,'á'*20).status_code==200
    assert login(app.test_client(),'á'*40).status_code==401

@pytest.mark.parametrize('payload',[[],{'email':[]},{'password':{}},{'remember':'true'}])
def test_malformed_payload_is_400(payload):
    assert app.test_client().post('/api/login',json=payload).status_code==400

def test_cross_origin_and_cross_site_writes_rejected():
    person();c=app.test_client()
    assert c.post('/api/login',json={'email':'person@example.invalid','password':PASSWORD},headers={'Origin':'https://example.invalid'}).status_code==403
    assert c.post('/api/login',json={},headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.post('/api/login',json={'email':'person@example.invalid','password':PASSWORD},headers={'Origin':'http://localhost'}).status_code==200

def test_api_destination_is_sanitized():
    person();c=app.test_client()
    assert login(c,next='//example.invalid').json['redirect_to']=='/dashboard'
    assert login(c,next='/pedir-asesoramiento').json['redirect_to']=='/pedir-asesoramiento'
