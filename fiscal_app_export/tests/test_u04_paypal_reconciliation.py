"""Synthetic U04 protocol tests. No application import or real credentials."""
import copy
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock
import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import db, FiscalAdvisoryRequest as Advisory, FiscalAdvisoryStatusHistory as History
from paypal_models import PayPalPaymentAttempt as Attempt, PayPalPaymentEvent as Event, uid
from paypal_payments import Payments, PaymentConflict, InvalidEvidence, money, formatted, contract

class Fake:
    def __init__(self):
        self.creates = self.posts = 0
        self.body = None
        self.timeout = False
        self.complete_on_timeout = True
        self.pending = False
        self.on_post = None
    def create(self, snap, return_url, cancel_url):
        assert not db.session().in_transaction()
        self.creates += 1
        self.body = {"id": "ORDER04TEST", "status": "CREATED", "intent": "CAPTURE",
                     "purchase_units": [{"custom_id": snap["expected_custom_id"],
                                        "amount": {"value": formatted(snap["quoted_amount_cents"]), "currency_code": "EUR"}}],
                     "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER04TEST"}]}
        return copy.deepcopy(self.body)
    def get_order(self, oid):
        assert not db.session().in_transaction()
        assert oid == self.body["id"]
        return copy.deepcopy(self.body)
    def get_capture(self, cid):
        assert not db.session().in_transaction()
        cap = copy.deepcopy(self.body["purchase_units"][0]["payments"]["captures"][0])
        cap["supplementary_data"] = {"related_ids": {"order_id": self.body["id"]}}
        return cap
    def capture(self, snap):
        assert not db.session().in_transaction()
        self.posts += 1
        if self.on_post:
            self.on_post()
        if not self.timeout or self.complete_on_timeout:
            self.body["status"] = "COMPLETED"
            self.body["purchase_units"][0]["payments"] = {"captures": [{
                "id": "CAPTURE04TEST", "status": "PENDING" if self.pending else "COMPLETED",
                "amount": copy.deepcopy(self.body["purchase_units"][0]["amount"])}]}
        if self.timeout:
            raise TimeoutError("synthetic only")
        return copy.deepcopy(self.body)

@pytest.fixture
def case():
    app = Flask("u04-synthetic")
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        row = Advisory(full_name="Synthetic", email="synthetic@example.invalid",
                       tax_residence_country="Synthetic", tax_year=2026, service_type="revision_basica",
                       case_description="Synthetic only", status="quote_sent", paypal_review_hold=False,
                       paypal_quote_generation=uid(), quoted_amount=10001, payment_link_token="u04-synthetic",
                       quote_sent_at=datetime.utcnow(), quote_expires_at=datetime.utcnow()+timedelta(days=1))
        db.session.add(row)
        db.session.commit()
        fake = Fake()
        service = Payments(fake, "sandbox", writes_enabled=True)
        yield service, fake, row.id
        db.session.remove()
        db.drop_all()

def prepared(case):
    service, fake, ident = case
    service.start("u04-synthetic", "https://app.example.invalid")
    attempt = Attempt.query.one()
    aid = attempt.id
    db.session.rollback()
    fake.body["status"] = "APPROVED"
    return service, fake, ident, aid

@pytest.mark.parametrize("value,cents", [("0.29",29),("100.01",10001),("1",100),("1.0",100)])
def test_decimal_exact(value,cents):
    assert money(value) == cents
    assert money(formatted(cents)) == cents

@pytest.mark.parametrize("value", [None,0.29,{},[], "", "NaN","Infinity","-1","0","1.001","1e2","1,00"," 1.00","9999999999999.00"])
def test_invalid_money(value):
    with pytest.raises(InvalidEvidence):
        money(value)

def test_completed_and_retry_button(case):
    service,fake,_,aid=prepared(case)
    service.start("u04-synthetic","https://app.example.invalid")
    assert fake.creates == 1
    assert service.capture(aid,"ORDER04TEST") == "RECONCILED"
    assert service.capture(aid,"ORDER04TEST") == "RECONCILED"
    assert fake.posts == 1
    assert History.query.filter_by(status="paid_received").count() == 1
    assert Advisory.query.one().amount_paid == 10001

@pytest.mark.parametrize("charged",[True,False])
def test_timeout_never_replays(case,charged):
    service,fake,_,aid=prepared(case)
    fake.timeout=True
    fake.complete_on_timeout=charged
    with pytest.raises(TimeoutError): service.capture(aid,"ORDER04TEST")
    assert Attempt.query.one().state == "UNCERTAIN"
    db.session.rollback()
    assert service.recover(aid) == ("RECONCILED" if charged else "UNCERTAIN")
    with pytest.raises(PaymentConflict): service.start("u04-synthetic","https://app.example.invalid")
    assert fake.creates == fake.posts == 1

def test_pending_capture(case):
    service,fake,_,aid=prepared(case);fake.pending=True
    assert service.capture(aid,"ORDER04TEST") == "PROVIDER_PENDING"
    assert Advisory.query.one().paid_at is None
    db.session.rollback()
    assert service.capture(aid,"ORDER04TEST") == "PROVIDER_PENDING"
    fake.body["purchase_units"][0]["payments"]["captures"][0]["status"]="COMPLETED"
    assert service.recover(aid) == "RECONCILED"
    assert fake.posts == 1

def test_finalization_failure_leaves_claim(case,monkeypatch):
    service,fake,_,aid=prepared(case)
    original=db.session.commit
    def fail_final():
        if any(isinstance(x,History) for x in db.session.new):
            raise RuntimeError("synthetic commit failure")
        original()
    monkeypatch.setattr(db.session,"commit",fail_final)
    with pytest.raises(RuntimeError): service.capture(aid,"ORDER04TEST")
    assert fake.posts == 1
    assert Advisory.query.one().paid_at is None
    db.session.rollback()
    monkeypatch.setattr(db.session,"commit",original)
    assert service.recover(aid) == "RECONCILED"
    assert fake.posts == 1

def test_reservation_commit_failure_no_post(case,monkeypatch):
    service,fake,_,aid=prepared(case)
    def fail(): raise RuntimeError("synthetic commit")
    monkeypatch.setattr(db.session,"commit",fail)
    with pytest.raises(RuntimeError): service.capture(aid,"ORDER04TEST")
    assert fake.posts == 0
    db.session.rollback()
    assert Attempt.query.one().state == "ORDER_CREATED"

def test_create_commit_failure_no_post(case,monkeypatch):
    service,fake,_=case
    monkeypatch.setattr(db.session,"commit",Mock(side_effect=RuntimeError("synthetic")))
    with pytest.raises(RuntimeError): service.start("u04-synthetic","https://app.example.invalid")
    assert fake.creates == 0
    db.session.rollback()
    assert Attempt.query.count() == 0

def test_create_timeout_preserves_unknown_id(case):
    service,fake,_=case
    def fail(*args): fake.creates+=1;raise TimeoutError("synthetic")
    fake.create=fail
    with pytest.raises(TimeoutError): service.start("u04-synthetic","https://app.example.invalid")
    a=Attempt.query.one()
    assert a.state == "UNCERTAIN" and a.paypal_order_id is None and a.uncertainty_phase=="CREATE"
    db.session.rollback()
    with pytest.raises(PaymentConflict): service.start("u04-synthetic","https://app.example.invalid")
    assert fake.creates == 1

def test_hold_and_quote_guard(case):
    service,fake,ident,aid=prepared(case)
    parent=service._parent(ident)
    with pytest.raises(PaymentConflict): service.guard_quote(parent)
    db.session.rollback()
    service.writes_enabled=False
    with pytest.raises(PaymentConflict): service.capture(aid,"ORDER04TEST")
    assert fake.posts == 0

def test_read_only_rollback_still_recovers(case):
    service,fake,_,aid=prepared(case);fake.timeout=True
    with pytest.raises(TimeoutError): service.capture(aid,"ORDER04TEST")
    service.writes_enabled=False
    assert service.recover(aid)=="RECONCILED"
    assert fake.posts==1

def test_duplicate_notices_ambiguous_ack(case):
    service,fake,_,aid=prepared(case)
    service.capture(aid,"ORDER04TEST")
    sender=Mock(side_effect=[True,TimeoutError("accepted but ack lost")])
    service.notify(aid,sender)
    service.notify(aid,sender)
    a=Attempt.query.one()
    assert sender.call_count==2
    assert a.customer_notification_state=="ACKNOWLEDGED"
    assert a.owner_notification_state=="UNKNOWN"

def test_late_webhook_no_duplicate_effects(case):
    service,fake,_,aid=prepared(case);fake.timeout=True
    with pytest.raises(TimeoutError): service.capture(aid,"ORDER04TEST")
    resource=fake.get_capture("CAPTURE04TEST")
    event={"id":"WH-SYNTHETIC-04","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":resource}
    assert service.webhook(event)==aid
    assert service.webhook(event)==aid
    assert Event.query.filter_by(provider_event_id=event["id"]).count()==1
    assert History.query.filter_by(status="paid_received").count()==1
    assert fake.posts==1

def test_unlinked_historical_webhook_quarantine(case):
    service,fake,_=case
    service.webhook({"id":"WH-UNKNOWN","resource":{"id":"UNKNOWNCAPTURE","custom_id":"1",
        "supplementary_data":{"related_ids":{"order_id":"UNKNOWNORDER"}}}})
    e=Event.query.one()
    assert e.attempt_id is None and e.kind=="quarantine"
    assert Advisory.query.one().paid_at is None and fake.posts==fake.creates==0

@pytest.mark.parametrize("mutation", ["amount","currency","custom","missing","multiple","wrong_order","status","empty_capture","float","precision","intent"])
def test_contradictory_contract_never_confirms(case,mutation):
    service,fake,_,aid=prepared(case)
    fake.capture(service.read(aid))
    snap=service.read(aid)
    b=copy.deepcopy(fake.body);u=b["purchase_units"][0];c=u["payments"]["captures"][0]
    if mutation=="amount": c["amount"]["value"]="100.00"
    if mutation=="currency": c["amount"]["currency_code"]="USD"
    if mutation=="custom": u["custom_id"]="different"
    if mutation=="missing": u.pop("amount")
    if mutation=="multiple": u["payments"]["captures"].append(copy.deepcopy(c))
    if mutation=="wrong_order": b["id"]="OTHER"
    if mutation=="status": c["status"]="FAILED"
    if mutation=="empty_capture": c["id"]=""
    if mutation=="float": c["amount"]["value"]=100.01
    if mutation=="precision": c["amount"]["value"]="100.010"
    if mutation=="intent": b["intent"]="AUTHORIZE"
    with pytest.raises(InvalidEvidence): contract(b,snap,completed=True)
    assert Advisory.query.one().paid_at is None

def test_close_never_reserved_only(case):
    service,fake,_,aid=prepared(case)
    service.close_uncaptured(aid,actor=None)
    assert Attempt.query.one().state=="CLOSED_NO_CHARGE"
    db.session.rollback()
    with pytest.raises(PaymentConflict): service.capture(aid,"ORDER04TEST")
    assert fake.posts==0


def test_webhook_before_order_saved_preserves_quarantine_and_blocks_capture(case):
    service,fake,ident=case
    original=fake.create
    def early(*args):
        body=original(*args)
        service.webhook({'id':'WH-EARLY','resource':{'id':'EARLYCAP','status':'COMPLETED',
            'amount':{'value':'100.01','currency_code':'EUR'},
            'supplementary_data':{'related_ids':{'order_id':body['id']}}}})
        return body
    fake.create=early
    service.start('u04-synthetic','https://app.example.invalid')
    original_event=Event.query.filter_by(provider_event_id='WH-EARLY').one()
    assert original_event.attempt_id is None and original_event.kind=='quarantine'
    assert Event.query.filter_by(kind='quarantine_correlated',correlation_event_id=original_event.id).count()==1
    a=Attempt.query.one();assert a.state=='REVIEW_REQUIRED'
    aid=a.id;db.session.rollback()
    service.capture(aid,'ORDER04TEST')
    assert fake.posts==0 and Advisory.query.one().paid_at is None


def test_minimal_capture_response_requires_get(case):
    service,fake,_,aid=prepared(case)
    original=fake.capture
    def minimal(snap):
        body=original(snap)
        return {'id':body['id'],'status':'COMPLETED','links':[]}
    fake.capture=minimal
    assert service.capture(aid,'ORDER04TEST')=='RECONCILED'
    assert fake.posts==1 and Advisory.query.one().amount_paid==10001


def test_get_failure_after_timeout_keeps_same_order(case):
    service,fake,_,aid=prepared(case);fake.timeout=True;fake.complete_on_timeout=False
    with pytest.raises(TimeoutError): service.capture(aid,'ORDER04TEST')
    fake.get_order=Mock(side_effect=TimeoutError('synthetic GET unavailable'))
    with pytest.raises(TimeoutError): service.recover(aid)
    a=Attempt.query.one()
    assert a.state=='UNCERTAIN' and a.paypal_order_id=='ORDER04TEST'
    assert fake.posts==fake.creates==1


def test_capture_commit_ack_lost_never_posts(case,monkeypatch):
    service,fake,_,aid=prepared(case)
    original=db.session.commit
    def ack_lost():
        original()
        raise RuntimeError('synthetic commit succeeded but ACK lost')
    monkeypatch.setattr(db.session,'commit',ack_lost)
    with pytest.raises(RuntimeError): service.capture(aid,'ORDER04TEST')
    monkeypatch.setattr(db.session,'commit',original)
    assert service.read(aid)['state']=='CAPTURE_STARTED'
    assert fake.posts==0
    assert service.recover(aid)=='UNCERTAIN' and fake.posts==0


def test_creation_id_commit_failure_never_recreates(case,monkeypatch):
    service,fake,_=case
    original=db.session.commit;calls=0
    def fail_second():
        nonlocal calls
        calls+=1
        if calls==2: raise RuntimeError('synthetic TC2 failure')
        original()
    monkeypatch.setattr(db.session,'commit',fail_second)
    with pytest.raises(RuntimeError): service.start('u04-synthetic','https://app.example.invalid')
    monkeypatch.setattr(db.session,'commit',original)
    assert fake.creates==1
    with pytest.raises(PaymentConflict): service.start('u04-synthetic','https://app.example.invalid')
    assert fake.creates==1 and Attempt.query.one().state=='UNCERTAIN'


def test_expired_quote_keeps_reserved_payment(case):
    service,fake,ident,aid=prepared(case);fake.timeout=True;fake.complete_on_timeout=False
    with pytest.raises(TimeoutError): service.capture(aid,'ORDER04TEST')
    parent=db.session.get(Advisory,ident);parent.quote_expires_at=datetime.utcnow()-timedelta(days=1);db.session.commit()
    assert service.capture(aid,'ORDER04TEST')=='UNCERTAIN'
    assert fake.posts==1


def test_legacy_adoption_requires_verified_get_and_keeps_hold(case):
    service,fake,ident=case
    parent=db.session.get(Advisory,ident)
    parent.paypal_quote_generation=None;parent.paypal_review_hold=True;parent.paypal_order_id='ORDER04TEST'
    db.session.commit()
    # Synthetic provider operation predates the protocol; no application POST.
    fake.body={'id':'ORDER04TEST','status':'COMPLETED','intent':'CAPTURE','purchase_units':[{
        'custom_id':str(ident),'amount':{'value':'100.01','currency_code':'EUR'},'payments':{'captures':[{
        'id':'CAPTURE04TEST','status':'COMPLETED','amount':{'value':'100.01','currency_code':'EUR'}}]}}]}
    aid=service.adopt_current_completed(ident,'quote-evidence-04',actor=None)
    a=Attempt.query.one();parent=db.session.get(Advisory,ident)
    assert a.id==aid and a.origin=='legacy_verified' and a.quote_generation is None
    assert a.capture_request_id is None and a.capture_started_at is None
    assert a.state=='RECONCILED' and parent.paypal_review_hold and parent.amount_paid==10001
    assert fake.creates==fake.posts==0


def test_legacy_reference_alone_never_confirms(case):
    service,fake,ident=case
    parent=db.session.get(Advisory,ident);parent.paypal_quote_generation=None
    parent.paypal_review_hold=True;parent.paypal_order_id='ORDER04TEST';db.session.commit()
    fake.body={'id':'ORDER04TEST','status':'COMPLETED'}
    with pytest.raises(InvalidEvidence): service.adopt_current_completed(ident,'quote-evidence-04',actor=None)
    assert Attempt.query.count()==0 and Advisory.query.one().paid_at is None
    assert fake.creates==fake.posts==0


def test_terminal_reference_and_approved_get_do_not_release(case):
    service,fake,_,aid=prepared(case);fake.timeout=True;fake.complete_on_timeout=False
    with pytest.raises(TimeoutError): service.capture(aid,'ORDER04TEST')
    with pytest.raises(PaymentConflict): service.close_terminal_verified(aid,'paypal-confirmation-04',actor=123)
    assert service.read(aid)['state']=='UNCERTAIN' and fake.posts==1
