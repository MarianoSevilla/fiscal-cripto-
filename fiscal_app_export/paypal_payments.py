"""U04: durable claims before financial HTTP. Recovery never invokes POST.

The HTTP client is injected for synthetic tests. Methods materialize snapshots
and end database transactions before network; no job/lease can replay a claim.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID
from models import db, FiscalAdvisoryRequest as Advisory, FiscalAdvisoryStatusHistory as History
from paypal_models import PayPalPaymentAttempt as Attempt, PayPalPaymentEvent as Event, now, uid

PENDING_MESSAGE = ("Estamos comprobando el resultado de tu pago con PayPal. No realices otro pago. "
                   "Conservamos tu solicitud y te informaremos cuando la comprobación termine.")
TRANSITIONS = {
    "ORDER_CREATING": {"ORDER_CREATED", "UNCERTAIN", "REVIEW_REQUIRED"},
    "ORDER_CREATED": {"READY_TO_CAPTURE", "CLOSED_NO_CHARGE", "REVIEW_REQUIRED"},
    "READY_TO_CAPTURE": {"CAPTURE_STARTED", "CLOSED_NO_CHARGE", "REVIEW_REQUIRED"},
    "CAPTURE_STARTED": {"RECONCILED", "PROVIDER_PENDING", "UNCERTAIN", "REVIEW_REQUIRED"},
    "UNCERTAIN": {"ORDER_CREATED", "RECONCILED", "PROVIDER_PENDING", "REVIEW_REQUIRED", "CLOSED_NO_CHARGE"},
    "PROVIDER_PENDING": {"RECONCILED", "REVIEW_REQUIRED", "CLOSED_NO_CHARGE"},
    "REVIEW_REQUIRED": {"RECONCILED", "CLOSED_NO_CHARGE"},
    "RECONCILED": set(), "CLOSED_NO_CHARGE": set(),
}

class PaymentConflict(Exception):
    pass
class InvalidEvidence(ValueError):
    pass

def money(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,2})?", value):
        raise InvalidEvidence("invalid_money")
    amount = Decimal(value)
    cents = int(amount * 100)
    if not 0 < cents <= 2147483647:
        raise InvalidEvidence("invalid_money")
    return cents

def formatted(cents):
    if type(cents) is not int or not 0 < cents <= 2147483647:
        raise InvalidEvidence("invalid_money")
    return format(Decimal(cents) / Decimal(100), ".2f")

def order_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{1,36}", value):
        raise InvalidEvidence("invalid_order_id")
    return value

def capture_id(value):
    # Bound matches the existing projection; no invented provider identifier regex.
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or any(ord(c) < 33 or ord(c) > 126 or c in "/?#\\%" for c in value):
        raise InvalidEvidence("invalid_capture_id")
    return value

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()

def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

def approval_url(body, environment):
    hosts = {"www.paypal.com", "paypal.com"} if environment == "live" else {"www.sandbox.paypal.com", "sandbox.paypal.com"}
    links = body.get("links", [])
    if not isinstance(links, list):
        raise InvalidEvidence("invalid_links")
    for link in links:
        if isinstance(link, dict) and link.get("rel") in ("approve", "payer-action"):
            value = link.get("href")
            if not isinstance(value, str):
                break
            url = urlsplit(value)
            if url.scheme == "https" and url.hostname in hosts and url.port in (None, 443) and not url.username and not url.password:
                return value
    raise InvalidEvidence("missing_approval")

def contract(body, snap, *, completed=False):
    if not isinstance(body, dict) or body.get("id") != snap["paypal_order_id"] or body.get("intent") != "CAPTURE":
        raise InvalidEvidence("order_contract")
    units = body.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        raise InvalidEvidence("purchase_units")
    unit = units[0]
    if "custom_id" in unit and unit["custom_id"] != snap["expected_custom_id"]:
        raise InvalidEvidence("custom_id")
    def amount(obj):
        if not isinstance(obj, dict) or obj.get("currency_code") != "EUR" or money(obj.get("value")) != snap["quoted_amount_cents"]:
            raise InvalidEvidence("amount_contract")
    amount(unit.get("amount"))
    payments = unit.get("payments", {})
    if not isinstance(payments, dict) or payments.get("authorizations") or payments.get("refunds"):
        raise InvalidEvidence("payment_structure")
    captures = payments.get("captures", [])
    if not isinstance(captures, list) or len(captures) > 1:
        raise InvalidEvidence("captures")
    if not captures:
        if completed:
            raise InvalidEvidence("missing_capture")
        return None
    cap = captures[0]
    if not isinstance(cap, dict):
        raise InvalidEvidence("capture_structure")
    cid = capture_id(cap.get("id"))
    if snap["paypal_capture_id"] and cid != snap["paypal_capture_id"]:
        raise InvalidEvidence("capture_identity")
    if "custom_id" in cap and cap["custom_id"] != snap["expected_custom_id"]:
        raise InvalidEvidence("custom_id")
    related = cap.get("supplementary_data", {}).get("related_ids", {})
    if related.get("order_id") and related["order_id"] != snap["paypal_order_id"]:
        raise InvalidEvidence("related_order")
    amount(cap.get("amount"))
    if completed and (body.get("status") != "COMPLETED" or cap.get("status") != "COMPLETED"):
        raise InvalidEvidence("capture_not_completed")
    return cap


class PayPalClient:
    def __init__(self, base_url, token_provider):
        if base_url not in ("https://api-m.paypal.com", "https://api-m.sandbox.paypal.com"):
            raise ValueError("invalid_paypal_base")
        self.base_url, self.token_provider = base_url, token_provider
    def _call(self, method, path, body=None, request_id=None):
        import requests
        with requests.Session() as client:
            # Requests' default adapter has zero retries; explicitly install it.
            client.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
            headers = {"Authorization": "Bearer " + self.token_provider(), "Content-Type": "application/json"}
            if request_id:
                headers.update({"PayPal-Request-Id": str(UUID(request_id)), "Prefer": "return=representation"})
            response = client.request(method, self.base_url + path, headers=headers, json=body,
                                      timeout=15, allow_redirects=False)
            response.raise_for_status()
            if not 200 <= response.status_code < 300:
                raise InvalidEvidence("http_redirect")
            result = response.json()
            if not isinstance(result, dict):
                raise InvalidEvidence("response_type")
            return result
    def create(self, snap, return_url, cancel_url):
        body = {"intent": "CAPTURE", "purchase_units": [{"custom_id": snap["expected_custom_id"],
                "amount": {"currency_code": "EUR", "value": formatted(snap["quoted_amount_cents"])}}],
                "application_context": {"brand_name": "Mariano Sevilla", "user_action": "PAY_NOW",
                                        "return_url": return_url, "cancel_url": cancel_url}}
        return self._call("POST", "/v2/checkout/orders", body, snap["create_request_id"])
    def capture(self, snap):
        return self._call("POST", "/v2/checkout/orders/" + order_id(snap["paypal_order_id"]) + "/capture",
                          {}, snap["capture_request_id"])
    def get_order(self, oid):
        return self._call("GET", "/v2/checkout/orders/" + order_id(oid))
    def get_capture(self, cid):
        return self._call("GET", "/v2/payments/captures/" + capture_id(cid))


class Payments:
    def __init__(self, client, environment, *, writes_enabled=False, scope="marianosevilla-paypal-primary"):
        if environment not in ("live", "sandbox"):
            raise PaymentConflict("invalid_environment")
        self.client, self.environment, self.scope = client, environment, scope
        self.writes_enabled = writes_enabled
    def _parent(self, ident):
        return Advisory.query.filter_by(id=ident).populate_existing().with_for_update().one()
    def _attempt(self, ident):
        return Attempt.query.filter_by(id=ident).populate_existing().with_for_update().one()
    def _event(self, attempt, kind, source="local", *, authenticated=False, valid=False,
               body=None, provider_event_id=None, actor=None, correlation=None):
        # Whitelist only normalized financial metadata; never persist raw payload.
        cap = None
        try:
            cap = contract(body, attempt.snapshot()) if attempt and body else None
        except (ValueError, TypeError, AttributeError):
            pass
        data = {"order_id": attempt.paypal_order_id if attempt else None,
                "capture_id": cap.get("id") if cap else None,
                "order_status": body.get("status") if isinstance(body, dict) and body.get("status") in
                ("CREATED", "SAVED", "APPROVED", "VOIDED", "COMPLETED", "PAYER_ACTION_REQUIRED") else None,
                "capture_status": cap.get("status") if cap and cap.get("status") in
                ("COMPLETED", "PENDING", "FAILED", "DECLINED", "REFUNDED", "PARTIALLY_REFUNDED") else None,
                "amount_cents": attempt.quoted_amount_cents if valid and attempt else None}
        event = Event(id=uid(), attempt_id=attempt.id if attempt else None,
                      provider_account_scope=self.scope, environment=self.environment,
                      source=source, kind=kind, authenticated=authenticated, contract_valid=valid,
                      provider_event_id=provider_event_id, actor_user_id=actor,
                      correlation_event_id=correlation, evidence_hash=digest(data),
                      observed_at=now(), paypal_order_id=data["order_id"], paypal_capture_id=data["capture_id"],
                      order_status=data["order_status"], capture_status=data["capture_status"],
                      amount_cents=data["amount_cents"], currency="EUR" if valid else None)
        db.session.add(event)
        return event
    def _move(self, attempt, state):
        if state == attempt.state:
            return
        if state not in TRANSITIONS[attempt.state]:
            raise PaymentConflict("forbidden_transition")
        if attempt.state == "UNCERTAIN" and state == "ORDER_CREATED" and attempt.capture_started_at:
            raise PaymentConflict("capture_not_replayable")
        attempt.state, attempt.version = state, attempt.version + 1
    def _eligible(self, parent, *, quote=False):
        if not self.writes_enabled or parent.paypal_review_hold or parent.amount_paid is not None or parent.paid_at or parent.status not in (("submitted", "quote_sent") if quote else ("quote_sent",)):
            raise PaymentConflict("financial_hold")
        if not quote and (not parent.paypal_quote_generation or not parent.quoted_amount or
                          aware(parent.quote_expires_at) and aware(parent.quote_expires_at) < now()):
            raise PaymentConflict("invalid_quote")
    def guard_quote(self, parent):
        self._eligible(parent, quote=True)
        if Attempt.query.filter(Attempt.advisory_id == parent.id, Attempt.state != "CLOSED_NO_CHARGE").first():
            raise PaymentConflict("preserved_attempt")
    def _scope(self, snap):
        if snap["environment"] != self.environment or snap["provider_account_scope"] != self.scope:
            raise PaymentConflict("provider_scope")
    def read(self, ident):
        db.session.rollback()
        a = db.session.get(Attempt, ident)
        if not a:
            raise PaymentConflict("unknown_attempt")
        snap = a.snapshot()
        db.session.rollback()
        self._scope(snap)
        return snap
    def uncertain(self, ident, *, review=False):
        db.session.rollback()
        snap = self.read(ident)
        self._parent(snap["advisory_id"])
        a = self._attempt(ident)
        if a.state not in ("RECONCILED", "CLOSED_NO_CHARGE", "REVIEW_REQUIRED", "PROVIDER_PENDING"):
            self._move(a, "REVIEW_REQUIRED" if review else "UNCERTAIN")
            if not review:
                a.uncertainty_phase = "CAPTURE" if a.capture_started_at else "CREATE"
                a.uncertain_at = a.uncertain_at or now()
            self._event(a, "invalid_evidence" if review else "uncertain")
        db.session.commit()
    def start(self, token, base_url, *, acceptance=None):
        db.session.rollback()
        parent = Advisory.query.filter_by(payment_link_token=token).populate_existing().with_for_update().first()
        if not parent:
            raise PaymentConflict("invalid_link")
        self._eligible(parent)
        existing = Attempt.query.filter(Attempt.advisory_id == parent.id, Attempt.state != "CLOSED_NO_CHARGE").first()
        if existing:
            snap = existing.snapshot()
            db.session.rollback()
            if snap["state"] not in ("ORDER_CREATED", "READY_TO_CAPTURE") or snap["capture_started_at"]:
                raise PaymentConflict("financial_hold")
            self._scope(snap)
            body = self.client.get_order(snap["paypal_order_id"])
            if contract(body, snap):
                self.observe(snap["id"], body)
                raise PaymentConflict("financial_hold")
            return approval_url(body, self.environment)
        aid = uid()
        a = Attempt(id=aid, advisory_id=parent.id, quote_generation=parent.paypal_quote_generation,
                    quoted_amount_cents=parent.quoted_amount, expected_custom_id=str(parent.id),
                    provider_account_scope=self.scope, environment=self.environment, origin="managed",
                    currency="EUR", create_request_id=uid(), state="ORDER_CREATING",
                    quote_sent_at=parent.quote_sent_at, quote_expires_at=parent.quote_expires_at,
                    request_contract_hash=digest({"advisory": parent.id, "generation": parent.paypal_quote_generation,
                                                "cents": parent.quoted_amount, "currency": "EUR", "operation": "create"}))
        if acceptance:
            parent.quote_accepted_at = datetime.utcnow()
            parent.quote_acceptance_ip, parent.quote_acceptance_user_agent = acceptance
        db.session.add(a)
        db.session.flush()
        self._event(a, "create_reserved")
        snap = a.snapshot()
        db.session.commit()  # TC1: an exception here MUST escape without POST.
        try:
            body = self.client.create(snap, base_url + "/api/pago/paypal/capture?request_id=" + str(snap["advisory_id"]),
                                      base_url + "/pagar/" + token + "?cancelado=1")
            oid = order_id(body.get("id"))
            db.session.rollback()
            self._parent(snap["advisory_id"])
            a = self._attempt(aid)
            if a.paypal_order_id and a.paypal_order_id != oid:
                raise InvalidEvidence("order_identity")
            a.paypal_order_id, a.order_created_at = oid, now()
            self._event(a, "order_identified", "create_response", authenticated=True)
            # Preserve the validated ID even if the economic representation is incomplete.
            a.version += 1
            db.session.commit()
            snap = self.read(aid)
            try:
                contract(body, snap)
            except InvalidEvidence:
                body = self.client.get_order(oid)
                contract(body, snap)
            url = approval_url(body, self.environment)
            self._parent(snap["advisory_id"])
            a = self._attempt(aid)
            self._move(a, "ORDER_CREATED")
            self._event(a, "order_created", "get_order", authenticated=True, valid=True, body=body)
            db.session.commit()  # TC2 completes before delivering the approval URL.
            self.correlate(aid)
            return url
        except Exception:
            db.session.rollback()
            try:
                self.uncertain(aid)
            except Exception:
                db.session.rollback()
            raise
    def capture(self, ident, expected_order):
        snap = self.read(ident)
        if snap["paypal_order_id"] != order_id(expected_order):
            raise PaymentConflict("order_identity")
        if snap["state"] == "RECONCILED":
            return "RECONCILED"
        if snap["state"] not in ("ORDER_CREATED", "READY_TO_CAPTURE") or snap["capture_started_at"]:
            return self.recover(ident)
        body = self.client.get_order(expected_order)
        cap = contract(body, snap)
        if cap:
            return self.observe(ident, body)
        if body.get("status") != "APPROVED":
            raise PaymentConflict("approval_required")
        parent = self._parent(snap["advisory_id"])
        a = self._attempt(ident)
        self._eligible(parent)
        if a.version != snap["version"] or a.state not in ("ORDER_CREATED", "READY_TO_CAPTURE") or a.capture_started_at:
            db.session.rollback()
            return self.recover(ident)
        if a.origin != "managed" or a.quote_generation != parent.paypal_quote_generation or a.quoted_amount_cents != parent.quoted_amount:
            raise PaymentConflict("quote_identity")
        if a.state == "ORDER_CREATED":
            self._move(a, "READY_TO_CAPTURE")
            a.approval_verified_at = now()
            db.session.flush()
        self._move(a, "CAPTURE_STARTED")
        a.capture_request_id, a.claim_id, a.capture_started_at = uid(), uid(), now()
        self._event(a, "capture_reserved", "get_order", authenticated=True, valid=True, body=body)
        snap = a.snapshot()
        db.session.commit()  # TP1: never place POST in a retryable transaction.
        try:
            body = self.client.capture(snap)
            try:
                contract(body, snap, completed=True)
            except InvalidEvidence:
                body = self.client.get_order(snap["paypal_order_id"])
            return self.observe(ident, body)
        except Exception:
            db.session.rollback()
            try:
                self.uncertain(ident)
            except Exception:
                db.session.rollback()
            raise
    def recover(self, ident, *, actor=None):
        snap = self.read(ident)
        if not snap["paypal_order_id"] or snap["state"] == "CLOSED_NO_CHARGE":
            raise PaymentConflict("financial_hold")
        try:
            body = self.client.get_order(snap["paypal_order_id"])
            # A known capture GET corroborates rather than substitutes the order.
            cap = contract(body, snap)
            if cap:
                detail = self.client.get_capture(cap["id"])
                related = detail.get("supplementary_data", {}).get("related_ids", {})
                if detail.get("id") != cap["id"] or related.get("order_id") != snap["paypal_order_id"] or detail.get("amount") != cap.get("amount") or detail.get("status") != cap.get("status"):
                    raise InvalidEvidence("capture_get_identity")
            return self.observe(ident, body, actor=actor)
        except InvalidEvidence:
            self.uncertain(ident, review=True)
            return "REVIEW_REQUIRED"
        except Exception:
            db.session.rollback()
            try:
                self.uncertain(ident)
            except Exception:
                db.session.rollback()
            raise
    def observe(self, ident, body, *, actor=None):
        snap = self.read(ident)
        try:
            cap = contract(body, snap)
        except (InvalidEvidence, TypeError, AttributeError):
            self.uncertain(ident, review=True)
            return "REVIEW_REQUIRED"
        parent = self._parent(snap["advisory_id"])
        a = self._attempt(ident)
        if a.state in ("RECONCILED", "CLOSED_NO_CHARGE"):
            if a.state == "CLOSED_NO_CHARGE" and cap:
                parent.paypal_review_hold = True
                self._event(a, "closed_order_payment", "get_order", authenticated=True, body=body, actor=actor)
            db.session.commit()
            return a.state
        a.last_observed_at = now()
        if a.version != snap["version"]:
            db.session.rollback()
            return self.recover(ident, actor=actor)
        a.version += 1
        if cap and cap.get("status") == "COMPLETED" and body.get("status") == "COMPLETED":
            contract(body, snap, completed=True)
            if not a.capture_started_at or a.origin != "managed" or a.quote_generation != parent.paypal_quote_generation or a.quoted_amount_cents != parent.quoted_amount or parent.paypal_review_hold:
                self._move(a, "REVIEW_REQUIRED")
                self._event(a, "quote_review", "get_order", authenticated=True, body=body, actor=actor)
            else:
                evidence = self._event(a, "completed_contract", "get_order", authenticated=True, valid=True, body=body, actor=actor)
                db.session.flush([evidence])
                a.paypal_capture_id = cap["id"]
                self._move(a, "RECONCILED")
                a.resolved_at, a.resolution_reason, a.resolution_event_id = now(), "verified_completed", evidence.id
                db.session.flush()
                parent.status, parent.amount_paid, parent.currency = "paid_received", a.quoted_amount_cents, "eur"
                parent.payment_provider, parent.paid_at = "paypal", datetime.utcnow()
                parent.paypal_order_id, parent.paypal_capture_id = a.paypal_order_id, a.paypal_capture_id
                db.session.add(History(request_id=parent.id, status="paid_received",
                                       note="Pago PayPal conciliado. Intento: " + a.id))
        elif cap and cap.get("status") == "PENDING" and a.capture_started_at:
            a.paypal_capture_id = cap["id"]
            self._move(a, "PROVIDER_PENDING")
            self._event(a, "provider_pending", "get_order", authenticated=True, body=body, actor=actor)
        elif cap:
            self._move(a, "REVIEW_REQUIRED")
            self._event(a, "capture_review", "get_order", authenticated=True, body=body, actor=actor)
        elif a.capture_started_at:
            if a.state == "CAPTURE_STARTED":
                self._move(a, "UNCERTAIN")
                a.uncertainty_phase, a.uncertain_at = "CAPTURE", now()
            self._event(a, "no_conclusive_capture", "get_order", authenticated=True, body=body, actor=actor)
        elif a.state == "UNCERTAIN" and a.uncertainty_phase == "CREATE":
            self._move(a, "ORDER_CREATED")
            self._event(a, "create_recovered", "get_order", authenticated=True, valid=True, body=body, actor=actor)
        state = a.state
        db.session.commit()  # TF: ledger + projection + history; no email before commit.
        return state
    def webhook(self, event):
        # Caller has authenticated the signature; never expose this as an unsigned endpoint.
        resource = event.get("resource")
        if not isinstance(resource, dict):
            resource = {}
        related = resource.get("supplementary_data", {}).get("related_ids", {})
        try:
            oid = order_id(related.get("order_id"))
            cid = capture_id(resource.get("id"))
        except (ValueError, TypeError, AttributeError):
            oid, cid = None, None
        event_id = event.get("id")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 100:
            event_id = None
        db.session.rollback()
        attempt = Attempt.query.filter_by(provider_account_scope=self.scope, environment=self.environment, paypal_order_id=oid).first() if oid else None
        aid = attempt.id if attempt else None
        if aid:
            self._parent(attempt.advisory_id)
            attempt = self._attempt(aid)
        existing = Event.query.filter_by(provider_account_scope=self.scope, environment=self.environment, provider_event_id=event_id).first() if event_id else None
        if not existing:
            e = self._event(attempt, "webhook_observed" if aid else "quarantine", "webhook",
                            authenticated=True, provider_event_id=event_id)
            e.paypal_order_id, e.paypal_capture_id = oid, cid
            e.evidence_hash = digest({"order": oid, "capture": cid, "event": event_id})
        if aid and (not cid or attempt.paypal_capture_id and cid != attempt.paypal_capture_id or
                    "custom_id" in resource and resource["custom_id"] != attempt.expected_custom_id):
            self._move(attempt, "REVIEW_REQUIRED") if attempt.state not in ("RECONCILED", "CLOSED_NO_CHARGE") else None
            db.session.commit()
            return aid
        if aid:
            try:
                if resource.get("status") != "COMPLETED" or resource.get("amount", {}).get("currency_code") != "EUR" or money(resource.get("amount", {}).get("value")) != attempt.quoted_amount_cents:
                    raise InvalidEvidence("webhook_contract")
            except (ValueError, TypeError, AttributeError):
                if attempt.state not in ("RECONCILED", "CLOSED_NO_CHARGE"):
                    self._move(attempt, "REVIEW_REQUIRED")
                db.session.commit()
                return aid
        db.session.commit()
        if aid:
            self.recover(aid)
        return aid
    def correlate(self, ident):
        snap = self.read(ident)
        self._parent(snap["advisory_id"])
        a = self._attempt(ident)
        events = Event.query.filter_by(attempt_id=None, paypal_order_id=a.paypal_order_id,
                                      provider_account_scope=self.scope, environment=self.environment,
                                      authenticated=True, kind="quarantine").all()
        for e in events:
            if not Event.query.filter_by(attempt_id=ident, correlation_event_id=e.id).first():
                self._event(a, "quarantine_correlated", correlation=e.id, authenticated=True)
        db.session.commit()
        if events:
            self.recover(ident)
    def close_uncaptured(self, ident, *, actor):
        snap = self.read(ident)
        if snap["origin"] != "managed" or snap["capture_started_at"] or snap["state"] not in ("ORDER_CREATED", "READY_TO_CAPTURE"):
            raise PaymentConflict("negative_evidence_required")
        body = self.client.get_order(snap["paypal_order_id"])
        if contract(body, snap) or body.get("status") not in ("CREATED", "APPROVED", "SAVED", "PAYER_ACTION_REQUIRED", "VOIDED"):
            raise PaymentConflict("negative_evidence_required")
        self._parent(snap["advisory_id"])
        a = self._attempt(ident)
        if a.version != snap["version"] or a.capture_started_at or a.state not in ("ORDER_CREATED", "READY_TO_CAPTURE"):
            raise PaymentConflict("concurrent_capture")
        evidence = self._event(a, "closed_without_capture", "manual", authenticated=True, valid=True, body=body, actor=actor)
        db.session.flush([evidence])
        self._move(a, "CLOSED_NO_CHARGE")
        a.resolved_at, a.resolution_reason, a.resolution_event_id = now(), "never_reserved_capture", evidence.id
        db.session.commit()
    def adopt_current_completed(self, advisory_id, quote_reference, *, actor):
        """Restricted owner operation after reviewing the existing quote evidence.

        No inferred historical generation, no capture POST, no clearing legacy
        hold. Only the currently preserved legacy order can be adopted here.
        """
        if not isinstance(quote_reference, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", quote_reference):
            raise PaymentConflict("quote_evidence_required")
        db.session.rollback()
        parent = db.session.get(Advisory, advisory_id)
        if not parent or not parent.paypal_review_hold or parent.paypal_quote_generation or parent.amount_paid is not None or parent.paid_at or not parent.paypal_order_id or not parent.quoted_amount:
            raise PaymentConflict("legacy_review_required")
        oid, cents, sent = parent.paypal_order_id, parent.quoted_amount, parent.quote_sent_at
        snap = {"paypal_order_id": oid, "paypal_capture_id": None, "expected_custom_id": str(advisory_id),
                "quoted_amount_cents": cents}
        db.session.rollback()
        body = self.client.get_order(oid)
        cap = contract(body, snap, completed=True)
        detail = self.client.get_capture(cap["id"])
        if detail.get("id") != cap["id"] or detail.get("status") != "COMPLETED" or detail.get("amount") != cap["amount"] or detail.get("supplementary_data", {}).get("related_ids", {}).get("order_id") != oid:
            raise InvalidEvidence("legacy_capture_relationship")
        parent = self._parent(advisory_id)
        if parent.paypal_order_id != oid or parent.quoted_amount != cents or parent.quote_sent_at != sent or parent.amount_paid is not None or parent.paypal_quote_generation:
            raise PaymentConflict("legacy_changed")
        if Attempt.query.filter(Attempt.advisory_id == advisory_id, Attempt.state != "CLOSED_NO_CHARGE").first():
            raise PaymentConflict("preserved_attempt")
        a = Attempt(id=uid(), advisory_id=advisory_id, origin="legacy_verified", quote_generation=None,
                    quote_evidence_ref=quote_reference, quoted_amount_cents=cents, currency="EUR",
                    expected_custom_id=str(advisory_id), provider_account_scope=self.scope, environment=self.environment,
                    create_request_id=uid(), paypal_order_id=oid, state="REVIEW_REQUIRED",
                    quote_sent_at=parent.quote_sent_at, quote_expires_at=parent.quote_expires_at,
                    request_contract_hash=digest({"legacy_order": oid, "quote_reference": quote_reference, "cents": cents}))
        # create_request_id identifies this local adoption record; it is never
        # represented as a request sent historically to PayPal or used for POST.
        db.session.add(a)
        db.session.flush()
        evidence = self._event(a, "completed_contract", "manual", authenticated=True, valid=True, body=body, actor=actor)
        evidence.operational_reference = quote_reference
        db.session.flush([evidence])
        a.paypal_capture_id = cap["id"]
        self._move(a, "RECONCILED")
        a.resolved_at, a.resolution_reason, a.resolution_event_id = now(), "legacy_verified_completed", evidence.id
        db.session.flush()
        parent.status, parent.amount_paid, parent.currency = "paid_received", cents, "eur"
        parent.payment_provider, parent.paid_at, parent.paypal_capture_id = "paypal", datetime.utcnow(), cap["id"]
        db.session.add(History(request_id=parent.id, status="paid_received", changed_by=actor,
                               note="Pago histórico conciliado con evidencia. Intento: " + a.id))
        ident = a.id
        db.session.commit()
        self.correlate(ident)
        return ident
    def notify(self, ident, sender):
        for who in ("customer", "owner"):
            snap = self.read(ident)
            self._parent(snap["advisory_id"])
            a = self._attempt(ident)
            key = who + "_notification_state"
            if a.state != "RECONCILED" or getattr(a, key) != "UNCLAIMED":
                db.session.rollback()
                continue
            setattr(a, key, "CLAIMED")
            setattr(a, who + "_notification_claimed_at", now())
            a.version += 1
            self._event(a, "notice_claimed_" + who)
            db.session.commit()
            try:
                accepted = sender(snap["advisory_id"], who)
            except Exception:
                accepted = False
            self._parent(snap["advisory_id"])
            a = self._attempt(ident)
            if getattr(a, key) == "CLAIMED":
                setattr(a, key, "ACKNOWLEDGED" if accepted else "UNKNOWN")
                a.version += 1
                self._event(a, "notice_accepted_" + who if accepted else "notice_unknown_" + who)
            db.session.commit()
