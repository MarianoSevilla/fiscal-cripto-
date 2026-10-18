"""Actual Flask authorization matrix, synthetic accounts and offline SQLite."""
from datetime import datetime
import pytest
from app import app,db,limiter
from models import User

TOOLS=['binance','bit2me','bitget','bitvavo','coinbase','cryptocom','kraken','kucoin','mexc','nexo','uphold']

@pytest.fixture(autouse=True)
def isolated():
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    app.config.update(TESTING=True,RATELIMIT_ENABLED=False,SESSION_COOKIE_SECURE=False)
    limiter.enabled=False
    with app.app_context():db.create_all()
    yield
    with app.app_context():db.session.remove();db.drop_all()

def client_for(role='user',plan='free',email=None):
    with app.app_context():
        user=User(email=email or f'{role}-{plan}@example.invalid',full_name='Persona sintética',
                  nif='12345678Z',role=role,plan=plan,email_verified_at=datetime.utcnow())
        db.session.add(user);db.session.commit();identity=user.get_id()
    client=app.test_client()
    with client.session_transaction() as session:
        session['_user_id']=identity;session['_fresh']=True
    return client

@pytest.mark.parametrize('role,plan',[(r,p) for r in ['user','fiscal_advisor','admin'] for p in ['free','pro']])
def test_routes_and_menu_flags_do_not_confuse_plan_and_role(role,plan):
    c=client_for(role,plan);u=c.get('/api/me').json['user']
    assert u['plan']==plan
    assert u['is_admin']==(role=='admin')
    assert u['is_fiscal_advisor']==(role in ['admin','fiscal_advisor'])
    for route in ['/dashboard','/dashboard-apple-preview','/modelo721','/account','/pedir-asesoramiento',*('/'+x for x in TOOLS)]:
        r=c.get(route);assert r.status_code==200,(role,plan,route,r.status_code)
    preview=c.get('/dashboard-apple-preview')
    assert preview.headers['Cache-Control']=='no-store'
    assert preview.headers['X-Robots-Tag']=='noindex, nofollow'
    assert 'Persona sintética' not in preview.text and '12345678Z' not in preview.text
    assert c.get('/static/dashboard_apple.html').status_code==404
    matrix={
      '/stats':200 if role=='admin' else 302,
      '/admin/asesoramiento':200 if role!='user' else 302,
      '/admin/recursos':200 if role!='user' else 302,
      '/admin/contactos':200 if role=='admin' else 302,
      '/admin/comunicaciones':200 if role=='admin' else 404,
      '/mis-solicitudes-fiscales':200 if role=='admin' else 404,
    }
    for route,want in matrix.items():
        assert c.get(route).status_code==want,(role,plan,route)
    for route in ['/api/admin/asesoramiento/solicitudes','/api/admin/recursos/solicitudes']:
        assert c.get(route).status_code==(403 if role=='user' else 200),(role,route)
    assert c.get('/api/admin/contactos').status_code==(200 if role=='admin' else 403)
    assert c.get('/api/admin/comunicaciones/campaigns').status_code==(200 if role=='admin' else 404)
    assert c.get('/pricing').status_code==404
    assert c.get('/api/asesoramiento/precios').status_code==503

@pytest.mark.parametrize('email,admin,advisor',[
 ('fallback-admin@example.invalid',True,True),('fallback-advisor@example.invalid',False,True)])
def test_server_email_fallback_still_controls_flags(email,admin,advisor):
    c=client_for(email=email);u=c.get('/api/me').json['user']
    assert u['is_admin']==admin and u['is_fiscal_advisor']==advisor
    assert c.get('/admin/asesoramiento').status_code==200
    assert c.get('/admin/contactos').status_code==(200 if admin else 302)

@pytest.mark.parametrize('identity',[None,'123','v1:123:'+'0'*64])
def test_anonymous_expired_or_forged_session_cannot_use_private_pages_or_apis(identity):
    c=app.test_client()
    if identity:
        with c.session_transaction() as s:s['_user_id']=identity;s['_fresh']=True
    assert c.get('/api/me').json=={'user':None}
    for path in ['/dashboard','/dashboard-apple-preview','/modelo721','/account',*('/'+x for x in TOOLS)]:
        r=c.get(path);assert r.status_code==302 and r.location.startswith('/login/'),path
    for path in ['/api/analizar','/api/kucoin/analizar','/api/bitget/analizar','/api/721','/api/721/xml']:
        assert c.post(path,json={}).status_code==401,path

def test_invalid_inputs_do_not_run_or_bypass_fiscal_tools():
    c=client_for()
    for path in ['/api/analizar','/api/kucoin/analizar','/api/bitget/analizar','/api/721','/api/721/xml']:
        assert c.post(path,json={}).status_code==400,path
    assert c.get('/api/descargar/fixture-unowned-token').status_code==400
    assert c.get('/api/descargar/fixture-unowned-token.pdf').status_code==403

def test_revoked_session_cannot_reenter_workspace():
    c=client_for()
    with app.app_context():
        u=User.query.first();u.is_active=False;db.session.commit()
    assert c.get('/dashboard-apple-preview').status_code==302
    assert c.get('/api/me').json=={'user':None}
