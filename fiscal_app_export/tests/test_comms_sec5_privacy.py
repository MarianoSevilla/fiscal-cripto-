"""SEC5-COMMS-001/002: public unsubscribe privacy and individual eligibility.

All contacts, addresses, tokens and incidents are synthetic. Resend is always
stubbed; no network, user data, production DB or real email messages are used.
"""
import os
import tempfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _TEST_DB)
os.environ.setdefault("SECRET_KEY", "sec5-comms-synthetic-isolated-test-key")

from app import app as flask_app, db  # noqa: E402
from models import (  # noqa: E402
    User, ProcessingError, CommunicationCampaign, CommunicationDelivery,
)
from communications import routes as routes_module  # noqa: E402
from communications import service as comms  # noqa: E402


@pytest.fixture(scope="module")
def isolated_app():
    flask_app.config.update(
        TESTING=True, RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False,
    )
    with flask_app.app_context():
        db.create_all()
        admin = User(email="sec5-comms-admin@example.invalid", full_name="Admin fixture",
                     role="admin", email_verified_at=datetime.utcnow())
        admin.set_password("isolated-only-password")
        db.session.add(admin)
        db.session.commit()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(isolated_app):
    return isolated_app.test_client()


@pytest.fixture
def admin_client(isolated_app):
    client = isolated_app.test_client()
    resp = client.post("/api/login", json={
        "email": "sec5-comms-admin@example.invalid",
        "password": "isolated-only-password",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)[:150]
    return client


@pytest.fixture
def mail_stub(monkeypatch):
    sent = []

    def no_network(payload):
        sent.append(payload)
        return {"id": "provider-synthetic-only"}

    monkeypatch.setattr(comms.resend.Emails, "send", no_network)
    monkeypatch.setattr(comms, "_SEND_DELAY_S", 0)
    return sent


@pytest.fixture
def dispatch_stub(monkeypatch):
    started = []
    monkeypatch.setattr(routes_module, "dispatch_campaign",
                        lambda campaign_id, context: started.append(campaign_id))
    return started


def _user(*, email, opted_out=False, active=True, role="user", token=None):
    user = User(
        email=email, full_name="Synthetic recipient", role=role,
        is_active=active, comms_opted_out=opted_out,
        email_verified_at=datetime.utcnow(),
        comms_unsubscribe_token=token,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _incident(email, user_id=None):
    record = ProcessingError(
        exchange="bitvavo", email=email, user_id=user_id,
        stage="parse", error_type="synthetic", resolved=False,
    )
    db.session.add(record)
    db.session.commit()
    return record


def _draft(address, *, incident_id=None):
    campaign = CommunicationCampaign(
        subject="Aviso de prueba", body="Mensaje sintético sin información real.",
        recipient_segment="individual", individual_email=address,
        processing_error_id=incident_id, status="draft",
    )
    db.session.add(campaign)
    db.session.commit()
    return campaign.id


def _start(client, campaign_id):
    return client.post(
        f"/api/admin/comunicaciones/drafts/{campaign_id}/send",
        json={"confirm": True},
    )


def test_public_unsubscribe_has_identical_nonidentifying_reply_for_valid_and_unknown(
        client, isolated_app):
    known_token = "synthetic-unsubscribe-token-sec5"
    with isolated_app.app_context():
        _user(email="unsubscribe-sec5@example.invalid", token=known_token)
    known = client.post("/api/unsubscribe", json={"token": known_token})
    unknown = client.post("/api/unsubscribe", json={"token": "unknown-token-sec5"})
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json() == {
        "ok": True, "message": "Desuscripción procesada.",
    }
    assert "email" not in known.get_json()
    assert "unsubscribe-sec5@example.invalid" not in known.get_data(as_text=True)
    repeat = client.post("/api/unsubscribe", json={"token": known_token})
    assert repeat.get_json() == unknown.get_json()
    with isolated_app.app_context():
        assert User.query.filter_by(email="unsubscribe-sec5@example.invalid").one().comms_opted_out


@pytest.mark.parametrize("address,kind", [
    ("marketing-unsub-sec5@example.invalid", "opted"),
    ("marketing-disabled-sec5@example.invalid", "inactive"),
    ("marketing-advisor-sec5@example.invalid", "advisor"),
    ("marketing-admin-sec5@example.invalid", "admin"),
    ("marketing-unknown-sec5@example.invalid", "missing"),
])
def test_individual_marketing_preflight_blocks_ineligible(
        isolated_app, admin_client, dispatch_stub, mail_stub, address, kind):
    with isolated_app.app_context():
        if kind != "missing":
            _user(email=address, opted_out=(kind == "opted"),
                  active=(kind != "inactive"),
                  role=("fiscal_advisor" if kind == "advisor" else
                        "admin" if kind == "admin" else "user"))
        campaign_id = _draft(address)
    resp = _start(admin_client, campaign_id)
    assert resp.status_code == 400, resp.get_data(as_text=True)[:250]
    assert dispatch_stub == [] and mail_stub == []
    with isolated_app.app_context():
        campaign = db.session.get(CommunicationCampaign, campaign_id)
        assert campaign.status == "draft"
        assert campaign.recipients_count == 0
        assert CommunicationDelivery.query.filter_by(campaign_id=campaign_id).count() == 0


def test_marketing_checks_optout_again_after_queuing(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    address = "marketing-late-optout-sec5@example.invalid"
    with isolated_app.app_context():
        _user(email=address)
        campaign_id = _draft(address)
    resp = _start(admin_client, campaign_id)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:250]
    assert resp.get_json()["recipients_count"] == 1
    assert dispatch_stub == [campaign_id]
    with isolated_app.app_context():
        user = User.query.filter_by(email=address).one()
        user.comms_opted_out = True
        db.session.commit()
        comms._execute_campaign(campaign_id)
        campaign = db.session.get(CommunicationCampaign, campaign_id)
        assert campaign.status == "cancelled"
        assert campaign.recipients_count == 0
        assert campaign.error_message == "Destinatario individual no elegible."
        assert CommunicationDelivery.query.filter_by(campaign_id=campaign_id).count() == 0
    assert mail_stub == []


def test_eligible_individual_marketing_sends_with_unsubscribe(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    address = "marketing-ok-sec5@example.invalid"
    with isolated_app.app_context():
        _user(email=address)
        campaign_id = _draft(address)
    assert _start(admin_client, campaign_id).status_code == 200
    assert dispatch_stub == [campaign_id]
    with isolated_app.app_context():
        comms._execute_campaign(campaign_id)
        campaign = db.session.get(CommunicationCampaign, campaign_id)
        assert campaign.status == "sent"
        delivery = CommunicationDelivery.query.filter_by(campaign_id=campaign_id).one()
        assert delivery.status == "sent" and delivery.email == address
        token = User.query.filter_by(email=address).one().comms_unsubscribe_token
        assert token
    assert len(mail_stub) == 1
    assert "List-Unsubscribe" in mail_stub[0]["headers"]
    assert token in mail_stub[0]["headers"]["List-Unsubscribe"]
    assert "Desuscribirse" in mail_stub[0]["html"]


def test_verified_incident_reply_to_opted_out_user_is_not_marketing(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    address = "incident-optout-sec5@example.invalid"
    with isolated_app.app_context():
        user = _user(email=address, opted_out=True)
        incident = _incident(address, user.id)
        incident_id = incident.id
        campaign_id = _draft(address, incident_id=incident_id)
    accepted = _start(admin_client, campaign_id)
    assert accepted.status_code == 200, accepted.get_data(as_text=True)[:250]
    assert dispatch_stub == [campaign_id]
    with isolated_app.app_context():
        comms._execute_campaign(campaign_id)
        assert db.session.get(CommunicationCampaign, campaign_id).status == "sent"
        user = User.query.filter_by(email=address).one()
        assert user.comms_opted_out and user.comms_unsubscribe_token is None
        assert db.session.get(ProcessingError, incident_id).auto_email_sent is True
    assert len(mail_stub) == 1
    assert mail_stub[0]["to"] == [address]
    assert "headers" not in mail_stub[0]
    assert "Desuscribirse" not in mail_stub[0]["html"]
    assert "incidencia concreta" in mail_stub[0]["html"]


def test_verified_incident_reply_can_contact_nonregistered_recipient(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    address = "incident-external-sec5@example.invalid"
    with isolated_app.app_context():
        incident = _incident(address)
        incident_id = incident.id
        campaign_id = _draft(address, incident_id=incident_id)
    assert _start(admin_client, campaign_id).status_code == 200
    with isolated_app.app_context():
        comms._execute_campaign(campaign_id)
        assert db.session.get(CommunicationCampaign, campaign_id).status == "sent"
        delivery = CommunicationDelivery.query.filter_by(campaign_id=campaign_id).one()
        assert delivery.user_id is None and delivery.status == "sent"
        assert db.session.get(ProcessingError, incident.id).auto_email_sent is True
    assert len(mail_stub) == 1 and mail_stub[0]["to"] == [address]
    assert "Desuscribirse" not in mail_stub[0]["html"]


def test_incident_link_cannot_be_used_for_another_address(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    with isolated_app.app_context():
        record = _incident("incident-owner-sec5@example.invalid")
        campaign_id = _draft("another-address-sec5@example.invalid",
                             incident_id=record.id)
    rejected = _start(admin_client, campaign_id)
    assert rejected.status_code == 400
    assert dispatch_stub == mail_stub == []


def test_incident_link_revalidated_when_dispatch_runs(
        isolated_app, admin_client, dispatch_stub, mail_stub):
    address = "incident-edited-sec5@example.invalid"
    with isolated_app.app_context():
        incident = _incident(address)
        incident_id = incident.id
        campaign_id = _draft(address, incident_id=incident_id)
    assert _start(admin_client, campaign_id).status_code == 200
    with isolated_app.app_context():
        incident = db.session.get(ProcessingError, incident_id)
        incident.email = "changed-sec5@example.invalid"
        db.session.commit()
        comms._execute_campaign(campaign_id)
        assert db.session.get(CommunicationCampaign, campaign_id).status == "cancelled"
        assert CommunicationDelivery.query.filter_by(campaign_id=campaign_id).count() == 0
    assert mail_stub == []
