"""Real Flask/bcrypt, synthetic identities, no providers or production I/O."""
from datetime import datetime,timedelta
import time
import hashlib
from unittest.mock import patch
import pytest
from flask.testing import FlaskClient
import app as module
from app import app,db
from models import User
from auth_flow import safe_auth_next
import re
from urllib.parse import urlsplit, parse_qs

REAL_VERIFY_EMAIL=module._send_verification_email
REAL_RESET_EMAIL=module._send_password_reset_email

PASSWORD='A fictional password 2026!'

class FreshRequestClient(FlaskClient):
    def open(self,*args,**kwargs):
        # The DB fixture holds an outer app context. Flask-Login caches its user
        # on g, so each simulated HTTP request needs its own app context, as in
        # the real WSGI server; otherwise clients incorrectly share cached users.
        with self.application.app_context():
            return super().open(*args,**kwargs)

@pytest.fixture(autouse=True)
def isolate():
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    app.config.update(TESTING=True,RATELIMIT_ENABLED=False,SESSION_COOKIE_SECURE=False)
    app.test_client_class=FreshRequestClient
    with app.app_context():
        db.create_all()
        with patch.object(module,'_send_verification_email',return_value=True), patch.object(module,'_send_password_reset_email',return_value=True):
            yield
        db.session.remove();db.drop_all()

def person(verified=True,role='user'):
    u=User(email='person@example.invalid',full_name='Persona ficticia',role=role,
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

@pytest.mark.parametrize('payload',[[],{'email':[]},{'password':{}},{'remember':'true'},{'password':'\ud800'}])
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

def test_verification_next_and_no_store():
    u=person(False);c=app.test_client()
    token=module._generate_verification_token(u.email)
    r=c.get('/verify-email',query_string={'token':token,'next':'/pedir-asesoramiento'})
    assert r.status_code==302 and 'next=%2Fpedir-asesoramiento' in r.location
    assert r.headers['Cache-Control']=='no-store' and r.headers['Referrer-Policy']=='no-referrer'
    assert c.get('/api/me').headers['Cache-Control']=='no-store'

@pytest.mark.parametrize('path,view',[
    ('/login','login'),('/login/','login'),('/signup','signup'),
    ('/recuperar-contrasena','forgot'),('/recuperar-contrasena/','forgot'),
    ('/reset-password/synthetic-token','reset'),('/verify-email-result','verify')])
def test_production_auth_routes(path,view):
    r=app.test_client().get(path,follow_redirects=True)
    assert r.status_code==200
    if path.endswith('/'):
        assert len(r.history)==1 and r.history[0].status_code==301
    assert f'data-auth-view="{view}"' in r.text
    assert 'data-auth-preview="true"' not in r.text
    assert 'noindex, nofollow' in r.text
    assert r.headers['Cache-Control']=='no-store'
    assert r.headers['Referrer-Policy']=='no-referrer'

def test_complete_registration_verification_login_and_recovery():
    """Exercise real routes, token builders and mail templates; intercept transport."""
    outbox=[]
    c=app.test_client();destination='/pedir-asesoramiento'
    payload={'full_name':'Persona ficticia','email':'person@example.invalid',
             'password':PASSWORD,'next':destination}
    def local_link(mail,path):
        url=re.search(r'https?://[^\s<>]*'+path+r'[^\s<>]*',mail['text']).group(0)
        parsed=urlsplit(url)
        return parsed.path+'?'+parsed.query
    with patch.object(module,'_send_verification_email',side_effect=REAL_VERIFY_EMAIL), \
         patch.object(module,'_send_password_reset_email',side_effect=REAL_RESET_EMAIL), \
         patch.object(module.resend,'api_key','synthetic-not-a-real-key'), \
         patch.object(module.resend.Emails,'send',side_effect=lambda mail:outbox.append(mail)):
        assert c.post('/api/register',json=payload).status_code==201
        assert len(outbox)==1 and outbox[0]['to']==[payload['email']]
        assert c.get('/api/me').json=={'user':None}
        verify=local_link(outbox[0],'/verify-email')
        r=c.get(verify)
        assert r.status_code==302 and 'status=success' in r.location
        assert parse_qs(urlsplit(r.location).query)['next']==[destination]
        assert c.get(r.location).status_code==200
        assert login(c,next=destination).json['redirect_to']==destination
        assert c.get('/api/me').json['user']['email']==payload['email']
        assert c.get('/recuperar-contrasena').status_code==200
        assert c.post('/api/forgot-password',json={'email':payload['email'],'next':destination}).status_code==200
        assert len(outbox)==2
        reset=local_link(outbox[1],'/reset-password/')
        assert c.get(reset).status_code==200
        assert parse_qs(urlsplit(reset).query)['next']==[destination]
        token=urlsplit(reset).path.rsplit('/',1)[-1]
        new_password='A replacement phrase 2026!'
        data={'token':token,'password':new_password,'confirm_password':new_password}
        assert c.post('/api/reset-password',json=data).status_code==200
        assert c.get('/api/me').json=={'user':None}
        assert c.post('/api/reset-password',json=data).status_code==400
        assert login(c).status_code==401
        assert login(c,new_password,next=destination).json['redirect_to']==destination
        assert c.post('/api/logout').status_code==200
        assert c.get('/api/me').json=={'user':None}



# AUTH-SESSION-TTL-001: real Flask session, synthetic accounts, no providers.
def _move_session_clock(client, *, started_delta, activity_delta=None):
    now=int(time.time())
    with client.session_transaction() as sess:
        sess['auth_started_at']=now-started_delta
        sess['auth_last_activity_at']=now-(
            started_delta if activity_delta is None else activity_delta
        )
    return now


@pytest.mark.parametrize('role,idle',[
    ('user',1800),('fiscal_advisor',900),('admin',900),
])
def test_server_expires_restored_session_at_role_idle_limit(role,idle):
    person(role=role);c=app.test_client()
    assert login(c).status_code==200
    now=_move_session_clock(c,started_delta=idle,activity_delta=idle)
    with patch.object(module.time,'time',return_value=now):
        res=c.get('/dashboard')
    assert res.status_code==302 and '/login/' in res.location, res.location
    assert 'expired=1' in res.location
    assert c.get('/api/me').json=={'user':None}
    with c.session_transaction() as sess:
        assert '_user_id' not in sess


@pytest.mark.parametrize('role,idle',[
    ('user',1800),('fiscal_advisor',900),('admin',900),
])
def test_activity_renews_idle_but_me_poll_does_not(role,idle):
    person(role=role);c=app.test_client()
    assert login(c).status_code==200
    now=_move_session_clock(c,started_delta=idle-3,activity_delta=idle-3)
    # Navigation is real user activity, while /api/me polling is passive.
    with patch.object(module.time,'time',return_value=now):
        assert c.get('/api/me').json['user']['email']=='person@example.invalid'
    with c.session_transaction() as sess:
        assert sess['auth_last_activity_at']==now-idle+3
    with patch.object(module.time,'time',return_value=now):
        assert c.get('/dashboard').status_code==200
    with c.session_transaction() as sess:
        assert sess['auth_last_activity_at']==now


@pytest.mark.parametrize('role', ['fiscal_advisor','admin'])
def test_staff_eight_hour_absolute_expiry_even_with_recent_activity(role):
    person(role=role);c=app.test_client()
    assert login(c).status_code==200
    now=_move_session_clock(c,started_delta=8*3600,activity_delta=5)
    with patch.object(module.time,'time',return_value=now):
        resp=c.get('/admin/asesoramiento')
    assert resp.status_code==302 and 'expired=1' in resp.location,resp.location
    assert c.get('/api/me').json=={'user':None}


def test_session_expiry_blocks_mutating_api_with_explicit_code():
    person();c=app.test_client();assert login(c).status_code==200
    now=_move_session_clock(c,started_delta=1801)
    with patch.object(module.time,'time',return_value=now):
        res=c.post('/api/change-password',json={
            'current_password':PASSWORD,'new_password':'Some other long password 2026!'
        })
    assert res.status_code==401, res.get_json()
    assert res.json.get('code')=='session_expired'
    assert c.get('/api/me').json=={'user':None}


def test_legacy_signed_session_without_timeout_stamps_is_not_trusted():
    u=person();c=app.test_client()
    with c.session_transaction() as sess:
        sess['_user_id']=u.get_id()
        sess['_fresh']=True
    res=c.get('/dashboard')
    assert res.status_code==302 and 'expired=1' in res.location
    assert c.get('/api/me').json=={'user':None}


def test_remember_parameter_cannot_create_persistent_login():
    person();c=app.test_client();assert login(c,remember=True).status_code==200
    assert c.get_cookie('remember_token') is None
    assert c.get('/api/me').json['user']['email']=='person@example.invalid'


def test_valid_legacy_remember_cookie_does_not_resurrect_account():
    from flask_login.utils import encode_cookie
    u=person();c=app.test_client()
    c.set_cookie('remember_token',encode_cookie(u.get_id(),key=app.secret_key))
    assert c.get('/api/me').json=={'user':None}
    assert c.get_cookie('remember_token') is None


def test_restored_browser_cookie_cannot_bypass_server_idle_limit():
    person();c=app.test_client();assert login(c).status_code==200
    cookie=c.get_cookie('session')
    assert cookie
    restarted=app.test_client()
    restarted.set_cookie('session',cookie.value)
    now=int(time.time())
    with patch.object(module.time,'time',return_value=now+1801):
        res=restarted.get('/dashboard')
    assert res.status_code==302 and 'expired=1' in res.location
    assert restarted.get('/api/me').json=={'user':None}


def test_corrupt_or_future_timestamp_fails_closed():
    person();c=app.test_client();assert login(c).status_code==200
    with c.session_transaction() as sess:
        sess['auth_started_at']='invalid'
    assert c.get('/api/me').json=={'user':None}
    assert login(c).status_code==200
    with c.session_transaction() as sess:
        sess['auth_last_activity_at']=int(time.time())+3600
    assert c.get('/api/me').json=={'user':None}


def test_login_page_explains_expiry_and_old_login_still_works():
    source=(__import__('pathlib').Path(__file__).resolve().parents[1] /
            'static'/'auth_apple.js').read_text(encoding='utf-8')
    assert "query.get('expired')==='1'" in source
    person();c=app.test_client()
    res=c.get('/login/?expired=1',follow_redirects=True)
    assert res.status_code==200
    assert 'data-auth-view="login"' in res.text
    assert login(c).status_code==200
