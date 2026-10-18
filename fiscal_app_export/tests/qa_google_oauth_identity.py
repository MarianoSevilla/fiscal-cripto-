"""Synthetic U03 business decisions and real Authlib 1.8 OIDC validation.

Invoked only by the isolated test runner; transport is stubbed, JWT verification
is real. No production DB, Google calls, keys, cookies or personal data.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import time
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.oidc.core import UserInfo
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import app as app_module
from app import app, db
from models import User


@pytest.fixture(scope="module", autouse=True)
def setup_app():
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False)
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def clean_users():
    with app.app_context():
        db.create_all()
        yield
        db.session.rollback()
        User.query.delete()
        db.session.commit()
        db.session.remove()


@pytest.fixture
def client():
    return app.test_client()


def token(email="new@example.com", sub="sub-A", **claims):
    info = dict(email=email, sub=sub, email_verified=True, nonce="fake-nonce",
                given_name="Persona", family_name="Ficticia")
    info.update(claims)
    return {"id_token": "fictional-business-only", "userinfo": UserInfo(info)}


def callback(client, value):
    with patch.object(app_module.google_oauth, "authorize_access_token", return_value=value):
        return client.get("/auth/google/callback")


def user(email="linked@example.com", sub="sub-A", **kwargs):
    obj = User(email=email, google_id=sub, email_verified_at=datetime(2025, 1, 1),
               full_name="Nombre Guardado", **kwargs)
    db.session.add(obj)
    db.session.commit()
    return obj


def snapshot(obj):
    return {col.key: getattr(obj, col.key) for col in inspect(User).columns}


def denied(client, response, before=None, obj=None):
    assert response.status_code == 302
    assert "/login/?error=" in response.location
    with client.session_transaction() as sess:
        assert "_user_id" not in sess
    assert client.get("/api/me").get_json()["user"] is None
    if obj is not None:
        db.session.expire_all()
        assert snapshot(obj) == before


def test_linked_sub_login_preserves_data_and_privileges(client):
    obj = user(role="admin", plan="pro")
    obj.set_password("Fictional-pass-123")
    db.session.commit()
    before = snapshot(obj)
    response = callback(client, token(obj.email))
    assert response.location == "/dashboard"
    with client.session_transaction() as sess:
        assert sess["_user_id"] == obj.get_id()
    after = snapshot(obj)
    assert after.pop("last_login") is not None
    before.pop("last_login")
    assert after == before


def test_same_email_different_sub_rejected_unchanged(client):
    obj = user()
    before = snapshot(obj)
    denied(client, callback(client, token(obj.email, "sub-B")), before, obj)


def test_usuario_existente_password_no_vincula_google(client):
    obj = user(email="classic@example.com", sub=None)
    obj.email_verified_at = None
    obj.set_password("Fictional-pass-123")
    db.session.commit()
    before = snapshot(obj)
    response = callback(client, token(obj.email))
    denied(client, response, before, obj)
    assert "identity_conflict" in response.location
    # The original method still grants access; OAuth has not verified its email.
    assert client.post("/api/login", json={"email": obj.email,
                        "password": "Fictional-pass-123"}).status_code == 200
    assert obj.google_id is None
    assert obj.email_verified_at is None


@pytest.mark.parametrize("active,sub", [(False, "sub-A"), (False, None), (False, "sub-B")])
def test_disabled_never_mutated_or_reactivated(client, active, sub):
    obj = user(is_active=active, sub=sub)
    obj.email_verified_at = None
    obj.full_name = None
    db.session.commit()
    before = snapshot(obj)
    denied(client, callback(client, token(obj.email)), before, obj)


@pytest.mark.parametrize("claim,value", [
    ("sub", None), ("sub", ""), ("sub", "   "), ("sub", 123),
    ("sub", []), ("sub", True), ("sub", "x" * 129), ("sub", " sub-A"),
    ("email_verified", None), ("email_verified", False),
    ("email_verified", "false"), ("email_verified", "true"),
    ("email_verified", 1), ("email_verified", []),
    ("email", None), ("email", ""), ("email", 42), ("email", []),
    ("email", "bad-email"), ("email", "a@b.c"), ("email", "a" * 255 + "@example.com"),
    ("nonce_supported", False), ("nonce", None),
])
def test_bad_claims_rejected_without_mutation(client, claim, value):
    obj = user()
    before = snapshot(obj)
    value_token = token(obj.email)
    value_token["userinfo"][claim] = value
    denied(client, callback(client, value_token), before, obj)
    assert User.query.count() == 1


@pytest.mark.parametrize("missing", ["sub", "email", "email_verified"])
def test_missing_claim_rejected(client, missing):
    value = token()
    del value["userinfo"][missing]
    denied(client, callback(client, value))
    assert User.query.count() == 0


@pytest.mark.parametrize("value", [None, {}, {"userinfo": {}},
    {"id_token": "fake", "userinfo": dict(token()["userinfo"])},
    {"userinfo": token()["userinfo"]}, {"id_token": "", "userinfo": token()["userinfo"]}])
def test_untrusted_token_response_rejected(client, value):
    denied(client, callback(client, value))
    assert User.query.count() == 0


def test_new_google_account_defaults_and_commit_before_login(client):
    with patch.object(app_module, "login_user", wraps=app_module.login_user) as login:
        response = callback(client, token(" NEW@EXAMPLE.COM "))
    assert response.location == "/dashboard"
    obj = User.query.one()
    assert obj.email == "new@example.com" and obj.google_id == "sub-A"
    assert obj.is_active is True and obj.email_verified_at is not None
    assert obj.role == "user" and obj.plan == "free" and obj.password_hash is None
    assert obj.full_name == "Persona Ficticia"
    assert login.call_count == 1 and obj.id is not None


def test_known_sub_changed_email_keeps_contact_and_identity(client):
    obj = user()
    before = snapshot(obj)
    assert callback(client, token("changed@example.com")).location == "/dashboard"
    after = snapshot(obj)
    before.pop("last_login")
    after.pop("last_login")
    assert after == before
    assert User.query.count() == 1


def test_known_sub_email_owned_by_other_account_is_conflict(client):
    first = user()
    second = user(email="other@example.com", sub="sub-B")
    before = snapshot(first), snapshot(second)
    denied(client, callback(client, token(second.email, first.google_id)))
    db.session.expire_all()
    assert (snapshot(first), snapshot(second)) == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("error_cls", [IntegrityError, SQLAlchemyError, RuntimeError])
def test_commit_failure_rollback_no_login(client, existing, error_cls):
    obj = user() if existing else None
    before = snapshot(obj) if obj else None
    failure = (IntegrityError("synthetic insert", {}, Exception("synthetic collision"))
               if error_cls is IntegrityError else error_cls("synthetic failure"))
    with patch.object(db.session, "commit", side_effect=failure), \
         patch.object(db.session, "rollback", wraps=db.session.rollback) as rollback, \
         patch.object(app_module, "login_user") as login:
        response = callback(client, token(obj.email if obj else "new@example.com"))
        assert rollback.called and not login.called
    denied(client, response, before, obj)
    assert User.query.count() == int(existing)
    # The session remains usable after rollback.
    assert callback(client, token(obj.email if obj else "new@example.com")).location == "/dashboard"


def test_retry_does_not_duplicate_account(client):
    assert callback(client, token()).location == "/dashboard"
    obj = User.query.one()
    uid = obj.id
    assert callback(app.test_client(), token()).location == "/dashboard"
    assert User.query.one().id == uid


@pytest.mark.parametrize("mode", ["same", "same-email", "same-sub"])
def test_concurrent_registration_uniqueness_and_identity(mode):
    barrier = Barrier(2)
    values = [token(), token()]
    if mode == "same-email":
        values[1] = token(sub="sub-B")
    if mode == "same-sub":
        values[1] = token(email="other@example.com")

    def sync_insert(mapper, connection, target):
        barrier.wait(timeout=10)

    def run(value):
        with app.test_client() as cli:
            # Each thread has its own request and SQLAlchemy session.
            response = cli.get("/auth/google/callback")
            with cli.session_transaction() as sess:
                return response.location, sess.get("_user_id")

    import threading
    local = threading.local()
    def run_local(value):
        local.value = value
        return run(value)

    event.listen(User, "before_insert", sync_insert)
    try:
        with patch.object(app_module.google_oauth, "authorize_access_token", side_effect=lambda: local.value):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run_local, values))
    finally:
        event.remove(User, "before_insert", sync_insert)
    db.session.expire_all()
    assert User.query.count() == 1
    obj = User.query.one()
    assert (obj.email, obj.google_id) in [(v["userinfo"]["email"], v["userinfo"]["sub"]) for v in values]
    assert sum(location == "/dashboard" for location, uid in results) == 1
    assert all(uid == obj.get_id() if location == "/dashboard" else uid is None for location, uid in results)


def test_preexisting_session_survives_rejected_callback(client):
    obj = user(sub=None)
    obj.set_password("Fictional-pass-123")
    db.session.commit()
    assert client.post("/api/login", json={"email": obj.email,
                        "password": "Fictional-pass-123"}).status_code == 200
    before = snapshot(obj)
    response = callback(client, token(obj.email))
    assert "/login/?error=" in response.location
    with client.session_transaction() as sess:
        assert sess["_user_id"] == obj.get_id()
    assert snapshot(obj) == before


def test_password_recovery_still_works_after_conflict(client):
    obj = user(sub=None)
    obj.set_password("Fictional-pass-123")
    db.session.commit()
    denied(client, callback(client, token(obj.email)))
    with patch.object(app_module, "_send_password_reset_email") as mail:
        assert client.post("/api/forgot-password", json={"email": obj.email}).status_code == 200
        mail.assert_called_once()
    reset = "fictional-reset-token"
    obj.password_reset_token_hash = hashlib.sha256(reset.encode()).hexdigest()
    obj.password_reset_expires_at = datetime.utcnow() + timedelta(minutes=5)
    db.session.commit()
    assert client.post("/api/reset-password", json={"token": reset, "password": "New-fictional-123",
                       "confirm_password": "New-fictional-123"}).status_code == 200
    assert obj.google_id is None
    assert client.post("/api/login", json={"email": obj.email,
                        "password": "New-fictional-123"}).status_code == 200


# Authenticity tests: real authorize_redirect, authorize_access_token,
# parse_id_token and JWT verification. Only metadata/JWKS/token transport mocked.
@pytest.fixture(scope="module")
def keys():
    return RSAKey.generate_key(2048), RSAKey.generate_key(2048)


def oidc_start(client, monkeypatch, keys):
    google = app_module.google_oauth
    metadata = {
        "issuer": "https://accounts.google.com", "authorization_endpoint": "https://accounts.google.com/o/oauth2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token", "jwks_uri": "https://fixture.invalid/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    monkeypatch.setattr(google, "load_server_metadata", lambda: metadata)
    monkeypatch.setattr(google, "fetch_jwk_set", lambda **kwargs: {"keys": [keys[0].as_dict(private=False)]})
    response = client.get("/auth/google")
    query = parse_qs(urlparse(response.location).query)
    assert "openid" in query["scope"][0]
    return query["state"][0], query["nonce"][0]


def signed_response(keys, nonce, changes=None, bad_signature=False):
    now = int(time.time())
    claims = dict(iss="https://accounts.google.com", aud="fictional-u03-client", sub="real-path-sub",
                  exp=now + 600, iat=now, nonce=nonce, email="signed@example.com", email_verified=True)
    claims.update(changes or {})
    raw = jwt.encode({"alg": "RS256"}, claims, keys[int(bad_signature)])
    return {"access_token": "synthetic-access", "id_token": raw, "token_type": "Bearer"}


def test_real_oidc_valid_signature_claims_and_state(client, monkeypatch, keys):
    state, nonce = oidc_start(client, monkeypatch, keys)
    monkeypatch.setattr(app_module.google_oauth, "fetch_access_token", lambda **kwargs: signed_response(keys, nonce))
    response = client.get("/auth/google/callback", query_string={"code": "synthetic-code", "state": state})
    assert response.location == "/dashboard"
    assert User.query.one().google_id == "real-path-sub"


@pytest.mark.parametrize("case", ["signature", "issuer", "audience", "expired", "nonce", "state", "replay", "missing-id-token", "missing-nonce-state", "nonce-bypass"])
def test_real_oidc_untrusted_claims_never_reach_login(client, monkeypatch, keys, case):
    state, nonce = oidc_start(client, monkeypatch, keys)
    changes = {
        "issuer": {"iss": "https://attacker.invalid"}, "audience": {"aud": "other-client"},
        "expired": {"exp": int(time.time()) - 600}, "nonce": {"nonce": "other-nonce"},
        "nonce-bypass": {"nonce_supported": False, "nonce": "other-nonce"},
    }.get(case, {})
    value = signed_response(keys, nonce, changes, bad_signature=(case == "signature"))
    if case == "missing-id-token":
        del value["id_token"]
        value["userinfo"] = dict(token()["userinfo"])
    if case == "missing-nonce-state":
        with client.session_transaction() as sess:
            del sess[f"_state_google_{state}"]["data"]["nonce"]
            sess.modified = True
        value["userinfo"] = dict(token()["userinfo"])
    fetch = lambda **kwargs: value
    monkeypatch.setattr(app_module.google_oauth, "fetch_access_token", fetch)
    if case == "state":
        state = "unregistered-state"
    if case == "replay":
        # First callback fails claims validation; its consumed state cannot be reused.
        bad = signed_response(keys, nonce, {"aud": "other-client"})
        monkeypatch.setattr(app_module.google_oauth, "fetch_access_token", lambda **kwargs: bad)
        denied(client, client.get("/auth/google/callback", query_string={"code": "synthetic", "state": state}))
        monkeypatch.setattr(app_module.google_oauth, "fetch_access_token", fetch)
    with patch.object(app_module, "login_user") as login:
        denied(client, client.get("/auth/google/callback", query_string={"code": "synthetic", "state": state}))
        assert not login.called
    assert User.query.count() == 0
