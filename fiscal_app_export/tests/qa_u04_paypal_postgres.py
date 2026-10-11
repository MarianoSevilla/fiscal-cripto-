"""Real PostgreSQL + multiprocess + loopback HTTP adversarial U04 QA.

Only a GitHub Actions ephemeral database is permitted. No real provider or
application credentials are inherited. SQLite does not run this evidence.
"""
import copy
import json
import multiprocessing as mp
import os
import signal
import socket
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import db, FiscalAdvisoryRequest as Advisory, FiscalAdvisoryStatusHistory as History
from paypal_models import PayPalPaymentAttempt as Attempt, PayPalPaymentEvent as Event, uid
from paypal_payments import Payments, PayPalClient, PaymentConflict
from paypal_schema import verify_structure
from qa_db_bootstrap_postgres import _create_db, _bootstrap, _env, _db_conn

class Provider(BaseHTTPRequestHandler):
    orders = {}
    posts = []
    notices = []
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()
    pause = False
    def log_message(self, *args): pass
    def reply(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        with self.lock:
            if "/captures/" in self.path:
                cid = self.path.rsplit("/",1)[-1]
                for body in self.orders.values():
                    captures = body["purchase_units"][0].get("payments",{}).get("captures",[])
                    if captures and captures[0]["id"] == cid:
                        cap = copy.deepcopy(captures[0])
                        cap["supplementary_data"] = {"related_ids":{"order_id":body["id"]}}
                        return self.reply(cap)
                self.send_error(404); return
            oid = self.path.rsplit("/",1)[-1]
            body = copy.deepcopy(self.orders.get(oid))
        if body is None: self.send_error(404)
        else: self.reply(body)
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        if self.path == "/notices":
            with self.lock: self.notices.append(payload)
            return self.reply({"id":"accepted"})
        key = self.headers.get("PayPal-Request-Id")
        assert key and self.headers.get("Prefer") == "return=representation"
        with self.lock: self.posts.append((self.path, key))
        if self.path == "/v2/checkout/orders":
            with self.lock:
                oid = "U04ORDER" + str(len(self.orders)+1)
                body = {"id":oid,"intent":"CAPTURE","status":"APPROVED",
                        "purchase_units":payload["purchase_units"],
                        "links":[{"rel":"approve","href":"https://www.sandbox.paypal.com/checkoutnow?token="+oid}]}
                self.orders[oid] = body
            return self.reply(body)
        oid = self.path.split("/")[-2]
        if self.pause:
            self.entered.set()
            if not self.release.wait(25): raise AssertionError("deterministic HTTP barrier not released")
        with self.lock:
            body = self.orders[oid]
            assert not body["purchase_units"][0].get("payments"), "second capture reached provider"
            body["status"]="COMPLETED"
            body["purchase_units"][0]["payments"]={"captures":[{"id":"U04CAP"+oid,
                "status":"COMPLETED","amount":copy.deepcopy(body["purchase_units"][0]["amount"])}]}
            result=copy.deepcopy(body)
        self.reply(result)

class LoopbackClient(PayPalClient):
    def __init__(self, url, before=None, after=None, release=None):
        assert url.startswith("http://127.0.0.1:")
        self.base_url,self.token_provider=url,lambda:"synthetic-only"
        self.before,self.after,self.release=before,after,release
    def capture(self, snap):
        if self.before:
            self.before.set()
            assert self.release.wait(25)
        body=super().capture(snap)
        if self.after:
            self.after.set()
            assert self.release.wait(25)
        return body

def app_for(uri):
    assert uri.startswith("postgresql://postgres:ci-only-test-password@127.0.0.1:5432/u04_")
    app=Flask("u04-postgres-synthetic")
    app.config.update(SQLALCHEMY_DATABASE_URI=uri.replace("postgresql://", "postgresql+psycopg2://", 1))
    db.init_app(app)
    return app

def worker(uri,url,operation,ident,queue,before=None,after=None,release=None,barrier=None):
    app=app_for(uri)
    with app.app_context():
        service=Payments(LoopbackClient(url,before,after,release),"sandbox",writes_enabled=True)
        if barrier: barrier.wait(15)
        try:
            if operation=="capture":
                snap=service.read(ident)
                state=service.capture(ident,snap["paypal_order_id"])
            elif operation=="start":
                try: state=service.start(ident,"https://app.example.invalid")
                except PaymentConflict: state="CONFLICT_BLOCKED"
            elif operation=="recover": state=service.recover(ident)
            elif operation=="webhook":
                snap=service.read(ident)
                cap=service.client.get_capture("U04CAP"+snap["paypal_order_id"])
                state=service.webhook({"id":"WH-"+snap["paypal_order_id"],"resource":cap})
            elif operation=="notice":
                import requests
                def send(advisory,who):
                    return bool(requests.post(url+"/notices",json={"advisory":advisory,"who":who},timeout=5).json()["id"])
                service.notify(ident,send); state="notified"
            else: raise AssertionError(operation)
            queue.put((operation,state))
        except Exception as exc:
            db.session.rollback()
            queue.put((operation,"ERROR:"+type(exc).__name__))
        finally: db.session.remove()

def main():
    assert os.environ.get("U04_EPHEMERAL_POSTGRES")=="1", "only explicit ephemeral CI execution allowed"
    name=_create_db("u04_paypal_ci")
    _bootstrap(name)
    uri=_env(name)["DATABASE_URL"]
    server=ThreadingHTTPServer(("127.0.0.1",0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url="http://127.0.0.1:"+str(server.server_port)
    ctx=mp.get_context("spawn")
    q=ctx.Queue()
    app=app_for(uri)
    def launch(op,ident,**kwargs):
        p=ctx.Process(target=worker,args=(uri,url,op,ident,q),kwargs=kwargs);p.start();return p
    def joined(p):
        p.join(30);assert not p.is_alive() and p.exitcode==0,(p.pid,p.exitcode)
        result=q.get(timeout=5);assert not result[1].startswith("ERROR:"),result;return result
    with app.app_context():
        with db.engine.begin() as conn: verify_structure(conn)
        service=Payments(LoopbackClient(url),"sandbox",writes_enabled=True)
        def prepare(label, start=True):
            parent=Advisory(full_name="Synthetic",email="u04@example.invalid",tax_residence_country="Synthetic",
                tax_year=2026,service_type="revision_basica",case_description="Synthetic only",status="quote_sent",
                paypal_review_hold=False,paypal_quote_generation=uid(),quoted_amount=10001,
                payment_link_token=label,quote_sent_at=datetime.utcnow(),quote_expires_at=datetime.utcnow()+timedelta(days=1))
            db.session.add(parent);db.session.commit()
            if not start:
                db.session.rollback();return label
            service.start(label,"https://app.example.invalid")
            a=Attempt.query.filter_by(advisory_id=parent.id).one();ident=a.id;db.session.rollback();return ident
        # Two creation contenders with no attempt; parent lock and index serialize.
        label=prepare("u04-dual-start",start=False)
        barrier=ctx.Barrier(2);count=len(Provider.posts)
        a=launch("start",label,barrier=barrier);b=launch("start",label,barrier=barrier)
        joined(a);joined(b)
        assert len(Provider.posts)==count+1
        assert Attempt.query.filter_by(advisory_id=Advisory.query.filter_by(payment_link_token=label).one().id).count()==1
        db.session.rollback()
        print("PG real: simultaneous creation, one durable attempt and one POST PASS")
        # Two independent processes; first blocks in HTTP after its durable commit.
        ident=prepare("u04-race")
        Provider.pause=True;Provider.entered.clear();Provider.release.clear()
        first=launch("capture",ident)
        assert Provider.entered.wait(15)
        snap=service.read(ident)
        with db.engine.begin() as conn:
            conn.execute(text("SELECT id FROM fiscal_advisory_requests WHERE id=:id FOR UPDATE NOWAIT"),{"id":snap["advisory_id"]})
        parent=service._parent(snap["advisory_id"])
        try: service.guard_quote(parent);raise AssertionError("requote authorized")
        except PaymentConflict: db.session.rollback()
        second=launch("capture",ident)
        assert joined(second)[1]=="UNCERTAIN"
        Provider.release.set();assert joined(first)[1]=="RECONCILED";Provider.pause=False
        assert sum(path.endswith("/"+snap["paypal_order_id"]+"/capture") for path,key in Provider.posts)==1
        print("PG real: two workers, one POST; SQL lock released during HTTP; requote blocked PASS")
        # Kill after TP1 but before POST; restart another process, only GET.
        ident=prepare("u04-kill-before")
        entered,release=ctx.Event(),ctx.Event()
        p=launch("capture",ident,before=entered,release=release);assert entered.wait(15)
        os.kill(p.pid,signal.SIGKILL);p.join(10);assert p.exitcode==-signal.SIGKILL
        snap=service.read(ident);assert snap["state"]=="CAPTURE_STARTED"
        count=len(Provider.posts)
        assert joined(launch("recover",ident))[1]=="UNCERTAIN"
        assert len(Provider.posts)==count
        print("PG real: SIGKILL before POST, durable claim, restarted GET-only recovery PASS")
        # Fresh bootstrap and a new process must preserve this pending reservation.
        _bootstrap(name)
        assert service.read(ident)["capture_request_id"]==snap["capture_request_id"]
        assert joined(launch("recover",ident))[1]=="UNCERTAIN"
        assert len(Provider.posts)==count
        print("PG real: repeated bootstrap with pending claim preserves identity PASS")
        # Kill after actual POST completion but before TF.
        ident=prepare("u04-kill-after")
        entered,release=ctx.Event(),ctx.Event()
        p=launch("capture",ident,after=entered,release=release);assert entered.wait(15)
        os.kill(p.pid,signal.SIGKILL);p.join(10);assert p.exitcode==-signal.SIGKILL
        snap=service.read(ident);assert snap["state"]=="CAPTURE_STARTED"
        barrier=ctx.Barrier(2)
        a=launch("recover",ident,barrier=barrier);b=launch("webhook",ident,barrier=barrier)
        joined(a);joined(b)
        db.session.rollback()
        assert Attempt.query.filter_by(id=ident).one().state=="RECONCILED"
        assert History.query.filter_by(request_id=snap["advisory_id"],status="paid_received").count()==1
        db.session.rollback()
        assert sum(path.endswith("/"+snap["paypal_order_id"]+"/capture") for path,key in Provider.posts)==1
        barrier=ctx.Barrier(2)
        a=launch("notice",ident,barrier=barrier);b=launch("notice",ident,barrier=barrier)
        joined(a);joined(b)
        assert len([x for x in Provider.notices if x["advisory"]==snap["advisory_id"]])==2
        print("PG real: SIGKILL after POST, concurrent GET/webhook, one history, two notification slots PASS")
        # Ambiguous COMMIT acknowledgment after the actual PostgreSQL commit.
        ambiguous=prepare("u04-commit-ack-lost")
        original_commit=db.session.commit
        lost=False
        def ambiguous_commit():
            nonlocal lost
            original_commit()
            if not lost:
                lost=True
                raise RuntimeError("synthetic committed reservation with lost ACK")
        count=len(Provider.posts)
        with patch.object(db.session,"commit",side_effect=ambiguous_commit):
            try: service.capture(ambiguous,service.read(ambiguous)["paypal_order_id"]);raise AssertionError("missing commit failure")
            except RuntimeError: pass
        assert service.read(ambiguous)["state"]=="CAPTURE_STARTED"
        assert len(Provider.posts)==count
        assert service.recover(ambiguous)=="UNCERTAIN"
        assert len(Provider.posts)==count
        # Lose the actual SQL connection after external capture, before TF.
        broken=prepare("u04-connection-loss-after-charge")
        disconnected=False
        def disconnect_confirmation():
            nonlocal disconnected
            if not disconnected and any(isinstance(x,History) for x in db.session.new):
                disconnected=True
                db.session.connection().invalidate()
            original_commit()
        try:
            with patch.object(db.session,"commit",side_effect=disconnect_confirmation):
                service.capture(broken,service.read(broken)["paypal_order_id"])
            raise AssertionError("missing connection failure")
        except AssertionError: raise
        except Exception: db.session.rollback()
        assert disconnected and service.read(broken)["state"] in ("CAPTURE_STARTED","UNCERTAIN")
        count=len(Provider.posts)
        assert service.recover(broken)=="RECONCILED"
        assert len(Provider.posts)==count
        print("PG real: lost COMMIT ACK prevents POST; lost SQL connection after charge recovers via GET PASS")
        # Real DDL guards resist incorrect SQL and rollback leaves evidence intact.
        failures=[
            ("UPDATE paypal_payment_attempt SET quoted_amount_cents=1 WHERE id=:id",{"id":ident}),
            ("UPDATE paypal_payment_attempt SET state='ORDER_CREATED', version=version+1 WHERE id=:id",{"id":ident}),
            ("DELETE FROM paypal_payment_attempt WHERE id=:id",{"id":ident}),
            ("UPDATE paypal_payment_event SET kind='forged' WHERE attempt_id=:id",{"id":ident}),
            ("DELETE FROM fiscal_advisory_requests WHERE id=:id",{"id":snap["advisory_id"]}),
            ("UPDATE fiscal_advisory_requests SET quoted_amount=1 WHERE id=:id",{"id":snap["advisory_id"]}),
            ("TRUNCATE paypal_payment_event CASCADE",{}),
            ("UPDATE paypal_payment_attempt SET customer_notification_state='UNCLAIMED',version=version+1 WHERE id=:id",{"id":ident}),
        ]
        for statement,args in failures:
            try:
                with db.engine.begin() as conn: conn.execute(text(statement),args)
                raise AssertionError("SQL guard bypass:"+statement)
            except AssertionError: raise
            except Exception: pass
        assert service.read(ident)["state"]=="RECONCILED"
        service.writes_enabled=False
        assert service.recover(ident)=="RECONCILED"
        preserved=service.read(ident)
        assert preserved["paypal_order_id"]==snap["paypal_order_id"]
        print("PG real: immutable SQL, append-only evidence, protected deletion and compatible rollback PASS")
        # Destructive downgrade must fail while preserving all rows.
        from qa_db_bootstrap_postgres import _run
        failed=_run(name,"from app import app\nfrom flask_migrate import downgrade\nwith app.app_context(): downgrade()",success=False)
        assert "destructive downgrade prohibited" in failed.stdout
        print("PG real: downgrade refused, financial records preserved PASS")
        db.session.remove()
    server.shutdown();server.server_close()

if __name__=="__main__": main()
