"""Migration-only PostgreSQL guards and structural verification for U04."""
import re
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateTable
from paypal_models import PayPalPaymentAttempt as Attempt, PayPalPaymentEvent as Event
from paypal_payments import TRANSITIONS

TABLES = (Attempt.__table__, Event.__table__)
TRIGGERS = ("u04_attempt_guard", "u04_attempt_delete", "u04_event_append",
            "u04_event_truncate", "u04_attempt_truncate", "u04_advisory_guard")

def _norm(value):
    return re.sub(r"[\s()\"']", "", str(value).lower().replace("::text", "").replace("::character varying", ""))

def verify_structure(connection, *, triggers=True):
    """Refuse incompatible model-created tables; never repair arbitrary shapes."""
    inspector = inspect(connection)
    for table in TABLES:
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        if set(columns) != set(c.name for c in table.columns):
            raise RuntimeError("U04 incompatible columns: " + table.name)
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != [c.name for c in table.primary_key.columns]:
            raise RuntimeError("U04 incompatible primary key: " + table.name)
        for c in table.columns:
            actual = columns[c.name]
            expected_type = c.type.compile(dialect=connection.dialect)
            if _norm(actual["type"].compile(dialect=connection.dialect)) != _norm(expected_type) or actual["nullable"] != c.nullable:
                raise RuntimeError("U04 incompatible column type/nullability: " + table.name + "." + c.name)
            expected_default = c.server_default.arg if c.server_default else None
            if _norm(actual.get("default")) != _norm(expected_default):
                raise RuntimeError("U04 incompatible column default: " + table.name + "." + c.name)
        expected_checks = {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        checks = {c["name"]: c for c in inspector.get_check_constraints(table.name)}
        if not expected_checks.issubset(checks):
            raise RuntimeError("U04 missing check constraints: " + table.name)
        expected_uniques = {c.name: tuple(col.name for col in c.columns) for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"}
        uniques = {c["name"]: tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        if any(uniques.get(k) != v for k, v in expected_uniques.items()):
            raise RuntimeError("U04 incompatible unique constraints: " + table.name)
        foreigns = inspector.get_foreign_keys(table.name)
        for fk in table.foreign_key_constraints:
            target = next(iter(fk.elements)).column.table.name
            candidates = [f for f in foreigns if f["constrained_columns"] == [c.name for c in fk.columns]
                          and f["referred_table"] == target
                          and f["referred_columns"] == [e.column.name for e in fk.elements]]
            if not candidates or str(candidates[0]["options"].get("ondelete", "")).upper() != str(fk.ondelete).upper():
                raise RuntimeError("U04 incompatible foreign key: " + table.name)
            if fk.deferrable and (not candidates[0]["options"].get("deferrable") or candidates[0]["options"].get("initially", "").upper() != "DEFERRED"):
                raise RuntimeError("U04 resolution FK must be deferred")
        indexes = {i["name"]: i for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            actual = indexes.get(index.name)
            if not actual or bool(actual["unique"]) != index.unique or actual["column_names"] != [c.name for c in index.columns]:
                raise RuntimeError("U04 incompatible index: " + index.name)
        if table.name == Attempt.__tablename__:
            predicate = indexes["uq_paypal_blocking_advisory"]["dialect_options"].get("postgresql_where", "")
            if connection.dialect.name == "postgresql" and _norm(predicate) != _norm("state <> 'CLOSED_NO_CHARGE'"):
                raise RuntimeError("U04 unsafe blocking index predicate")
    parent = {c["name"]: c for c in inspector.get_columns("fiscal_advisory_requests")}
    if parent["paypal_review_hold"]["nullable"] or _norm(parent["paypal_review_hold"].get("default")) not in ("true", "1"):
        raise RuntimeError("U04 unsafe legacy hold default")
    if not parent["paypal_quote_generation"]["nullable"] or parent["paypal_quote_generation"].get("default") is not None or _norm(parent["paypal_quote_generation"]["type"]) != "uuid":
        if connection.dialect.name == "postgresql":
            raise RuntimeError("U04 incompatible quote generation")
    if connection.dialect.name == "postgresql":
        # Compare CHECK definitions after PostgreSQL itself canonicalizes the model
        # expressions on temporary probe tables. Names alone cannot prove semantics.
        for table in TABLES:
            probe = "u04_probe_" + table.name
            columns = ", ".join(c.name + " " + c.type.compile(dialect=connection.dialect) for c in table.columns)
            checks = ", ".join("CONSTRAINT " + c.name + " CHECK (" + str(c.sqltext) + ")"
                               for c in table.constraints if c.__class__.__name__ == "CheckConstraint")
            connection.execute(text("DROP TABLE IF EXISTS pg_temp." + probe))
            connection.execute(text("CREATE TEMP TABLE " + probe + " (" + columns + ", " + checks + ") ON COMMIT DROP"))
            rows = connection.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype='c'"), {"table": table.name}).all()
            expected = dict(connection.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype='c'"), {"table": probe}).all())
            if any(name in expected and value != expected[name] for name, value in rows):
                raise RuntimeError("U04 altered check semantics: " + table.name)
        if triggers:
            present = set(connection.execute(text(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgenabled = 'O' "
                "AND tgrelid IN ('paypal_payment_attempt'::regclass, 'paypal_payment_event'::regclass, "
                "'fiscal_advisory_requests'::regclass)")).scalars())
            if not set(TRIGGERS).issubset(present):
                raise RuntimeError("U04 financial triggers missing or disabled")
            bindings = {r[0]: tuple(r[1:]) for r in connection.execute(text(
                "SELECT tgname,tgrelid::regclass::text,tgfoid::regproc::text,tgtype,tgnargs,tgqual IS NULL "
                "FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'u04_%'"))}
            expected_bindings = {
                "u04_attempt_guard": ("paypal_payment_attempt", "u04_attempt_guard_fn", 23, 0, True),
                "u04_attempt_delete": ("paypal_payment_attempt", "u04_no_delete_fn", 11, 0, True),
                "u04_event_append": ("paypal_payment_event", "u04_event_append_fn", 27, 0, True),
                "u04_advisory_guard": ("fiscal_advisory_requests", "u04_advisory_guard_fn", 27, 0, True),
                "u04_event_truncate": ("paypal_payment_event", "u04_no_delete_fn", 34, 0, True),
                "u04_attempt_truncate": ("paypal_payment_attempt", "u04_no_delete_fn", 34, 0, True),
            }
            if any(bindings.get(k) != v for k, v in expected_bindings.items()):
                raise RuntimeError("U04 incompatible financial trigger binding")
            class Collector:
                def __init__(self): self.statements = []
                def execute(self, stmt): self.statements.append(str(stmt))
            collector = Collector()
            install_guards(collector)
            expected_bodies = {}
            for statement in collector.statements:
                for match in re.finditer(r"FUNCTION (u04_\w+)\(\) RETURNS trigger LANGUAGE plpgsql AS \$\$(.*?)\$\$;", statement, re.S):
                    expected_bodies[match.group(1)] = match.group(2).strip()
            actual_bodies = dict(connection.execute(text(
                "SELECT proname, prosrc FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname LIKE 'u04_%'")).all())
            if any(actual_bodies.get(k, "").strip() != v for k, v in expected_bodies.items()):
                raise RuntimeError("U04 altered financial trigger function")


def install_guards(connection):
    clauses = []
    for old, allowed in TRANSITIONS.items():
        if allowed:
            targets = ",".join("'" + s + "'" for s in sorted(allowed))
            clauses.append("(OLD.state = '" + old + "' AND NEW.state IN (" + targets + "))")
    transitions = " OR ".join(clauses)
    immutable = ("id", "advisory_id", "origin", "quote_generation", "quote_evidence_ref",
                 "quoted_amount_cents", "currency", "expected_custom_id", "provider_account_scope",
                 "environment", "create_request_id", "quote_sent_at", "quote_expires_at", "created_at",
                 "request_contract_hash")
    checks = " OR ".join("NEW." + c + " IS DISTINCT FROM OLD." + c for c in immutable)
    write_once = " OR ".join("(OLD." + c + " IS NOT NULL AND NEW." + c + " IS DISTINCT FROM OLD." + c + ")"
                            for c in ("paypal_order_id", "paypal_capture_id", "capture_request_id", "claim_id", "capture_started_at", "resolved_at", "resolution_event_id", "resolution_reason", "customer_notification_claimed_at", "owner_notification_claimed_at"))
    connection.execute(text("""
CREATE OR REPLACE FUNCTION u04_attempt_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p fiscal_advisory_requests%ROWTYPE; evidence paypal_payment_event%ROWTYPE;
BEGIN
 SELECT * INTO p FROM fiscal_advisory_requests WHERE id=NEW.advisory_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'U04 parent required'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.origin='managed' AND (p.paypal_review_hold OR p.amount_paid IS NOT NULL OR
    p.paid_at IS NOT NULL OR p.status <> 'quote_sent' OR p.paypal_quote_generation IS DISTINCT FROM NEW.quote_generation OR
    p.quoted_amount IS DISTINCT FROM NEW.quoted_amount_cents OR NEW.state <> 'ORDER_CREATING') THEN
   RAISE EXCEPTION 'U04 managed contract required';
  END IF;
 ELSE
  IF """ + checks + " OR " + write_once + """ THEN RAISE EXCEPTION 'U04 immutable financial identity'; END IF;
  IF NEW.version <= OLD.version THEN RAISE EXCEPTION 'U04 version must advance'; END IF;
  IF NEW.customer_notification_state IS DISTINCT FROM OLD.customer_notification_state AND NOT (
     (OLD.customer_notification_state='UNCLAIMED' AND NEW.customer_notification_state IN ('CLAIMED','SKIPPED')) OR
     (OLD.customer_notification_state='CLAIMED' AND NEW.customer_notification_state IN ('ACKNOWLEDGED','UNKNOWN'))) THEN
   RAISE EXCEPTION 'U04 notification cannot be replayed';
  END IF;
  IF NEW.owner_notification_state IS DISTINCT FROM OLD.owner_notification_state AND NOT (
     (OLD.owner_notification_state='UNCLAIMED' AND NEW.owner_notification_state IN ('CLAIMED','SKIPPED')) OR
     (OLD.owner_notification_state='CLAIMED' AND NEW.owner_notification_state IN ('ACKNOWLEDGED','UNKNOWN'))) THEN
   RAISE EXCEPTION 'U04 notification cannot be replayed';
  END IF;
  IF NEW.state <> OLD.state AND NOT (""" + transitions + """) THEN RAISE EXCEPTION 'U04 forbidden transition'; END IF;
  IF OLD.state='UNCERTAIN' AND NEW.state='ORDER_CREATED' AND OLD.capture_started_at IS NOT NULL THEN
   RAISE EXCEPTION 'U04 no capture replay';
  END IF;
  IF OLD.state IN ('RECONCILED','CLOSED_NO_CHARGE') AND NEW.state <> OLD.state THEN RAISE EXCEPTION 'U04 terminal state'; END IF;
  IF NEW.capture_request_id IS DISTINCT FROM OLD.capture_request_id AND
     (OLD.state <> 'READY_TO_CAPTURE' OR NEW.state <> 'CAPTURE_STARTED' OR p.paypal_review_hold OR
      p.paypal_quote_generation IS DISTINCT FROM NEW.quote_generation OR p.quoted_amount IS DISTINCT FROM NEW.quoted_amount_cents OR
      p.amount_paid IS NOT NULL OR p.paid_at IS NOT NULL OR p.status <> 'quote_sent') THEN
   RAISE EXCEPTION 'U04 capture claim denied';
  END IF;
 END IF;
 IF NEW.state IN ('RECONCILED','CLOSED_NO_CHARGE') AND (TG_OP='INSERT' OR NEW.state IS DISTINCT FROM OLD.state) THEN
  SELECT * INTO evidence FROM paypal_payment_event WHERE id=NEW.resolution_event_id;
  IF NOT FOUND OR evidence.attempt_id IS DISTINCT FROM NEW.id OR NOT evidence.authenticated OR NOT evidence.contract_valid THEN
   RAISE EXCEPTION 'U04 verified resolution event required';
  END IF;
  IF NEW.state='RECONCILED' AND (
    evidence.kind='completed_contract' AND evidence.capture_status='COMPLETED' AND evidence.order_status='COMPLETED' AND
    evidence.amount_cents IS NOT DISTINCT FROM NEW.quoted_amount_cents AND evidence.currency='EUR' AND
    evidence.paypal_capture_id IS NOT DISTINCT FROM NEW.paypal_capture_id AND
    evidence.paypal_order_id IS NOT DISTINCT FROM NEW.paypal_order_id
  ) IS NOT TRUE THEN RAISE EXCEPTION 'U04 invalid completion evidence'; END IF;
  IF NEW.state='CLOSED_NO_CHARGE' AND (
    (evidence.kind='closed_without_capture' AND NEW.capture_started_at IS NULL) OR
    (evidence.kind='terminal_no_charge' AND evidence.source='manual' AND evidence.actor_user_id IS NOT NULL AND
     evidence.operational_reference IS NOT NULL AND evidence.order_status='VOIDED' AND
     evidence.paypal_order_id IS NOT DISTINCT FROM NEW.paypal_order_id AND NEW.paypal_capture_id IS NULL)
  ) IS NOT TRUE THEN
   RAISE EXCEPTION 'U04 insufficient negative evidence';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""))
    connection.execute(text("""
CREATE OR REPLACE FUNCTION u04_no_delete_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'U04 financial records are protected'; END $$;
CREATE OR REPLACE FUNCTION u04_event_append_fn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 -- FK anonymization may remove an actor; financial evidence cannot be rewritten.
 IF TG_OP='UPDATE' AND pg_trigger_depth()>1 AND OLD.actor_user_id IS NOT NULL AND NEW.actor_user_id IS NULL AND
    (to_jsonb(NEW)-'actor_user_id')=(to_jsonb(OLD)-'actor_user_id') THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'U04 events are append-only';
END $$;
CREATE OR REPLACE FUNCTION u04_advisory_guard_fn() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE blocked boolean; paid paypal_payment_attempt%ROWTYPE;
BEGIN
 SELECT EXISTS(SELECT 1 FROM paypal_payment_attempt WHERE advisory_id=OLD.id AND state <> 'CLOSED_NO_CHARGE') INTO blocked;
 IF TG_OP='DELETE' THEN
  IF OLD.paypal_review_hold OR EXISTS(SELECT 1 FROM paypal_payment_attempt WHERE advisory_id=OLD.id) THEN
   RAISE EXCEPTION 'U04 protected advisory cannot be deleted';
  END IF; RETURN OLD;
 END IF;
 IF (blocked OR OLD.paypal_review_hold) AND
    (NEW.quoted_amount IS DISTINCT FROM OLD.quoted_amount OR NEW.paypal_quote_generation IS DISTINCT FROM OLD.paypal_quote_generation OR
     NEW.quote_sent_at IS DISTINCT FROM OLD.quote_sent_at OR NEW.quote_expires_at IS DISTINCT FROM OLD.quote_expires_at OR
     NEW.payment_link_token IS DISTINCT FROM OLD.payment_link_token OR (NEW.status='quote_sent' AND OLD.status <> 'quote_sent')) THEN
  RAISE EXCEPTION 'U04 quote is financially protected';
 END IF;
 IF OLD.paypal_review_hold AND NOT NEW.paypal_review_hold AND NOT EXISTS(
   SELECT 1 FROM paypal_payment_attempt a JOIN paypal_payment_event e ON e.attempt_id=a.id
   WHERE a.advisory_id=OLD.id AND a.origin='legacy_verified' AND a.state='CLOSED_NO_CHARGE' AND
     a.resolution_reason='legacy_scope_verified_no_charge' AND a.paypal_order_id=OLD.paypal_order_id AND
     a.quoted_amount_cents=OLD.quoted_amount AND a.quote_evidence_ref IS NOT NULL AND
     e.kind='legacy_scope_no_charge' AND e.source='manual' AND e.authenticated AND e.contract_valid AND
     e.xmin=pg_current_xact_id()::xid AND
     e.actor_user_id IS NOT NULL AND e.operational_reference IS NOT NULL AND e.order_status='VOIDED' AND
     NOT blocked AND OLD.amount_paid IS NULL AND OLD.paid_at IS NULL AND OLD.paypal_capture_id IS NULL
 ) THEN RAISE EXCEPTION 'U04 hold requires operational evidence'; END IF;
 IF blocked AND NEW.status='paid_received' AND NEW.status IS DISTINCT FROM OLD.status AND
    NOT EXISTS(SELECT 1 FROM paypal_payment_attempt WHERE advisory_id=OLD.id AND state='RECONCILED') THEN
  RAISE EXCEPTION 'U04 completion must be reconciled';
 END IF;
 IF blocked AND (NEW.amount_paid IS DISTINCT FROM OLD.amount_paid OR NEW.currency IS DISTINCT FROM OLD.currency OR
   NEW.paid_at IS DISTINCT FROM OLD.paid_at OR NEW.payment_provider IS DISTINCT FROM OLD.payment_provider OR
   NEW.paypal_order_id IS DISTINCT FROM OLD.paypal_order_id OR NEW.paypal_capture_id IS DISTINCT FROM OLD.paypal_capture_id) THEN
  SELECT * INTO paid FROM paypal_payment_attempt WHERE advisory_id=OLD.id AND state='RECONCILED';
  IF NOT FOUND OR NEW.amount_paid IS DISTINCT FROM paid.quoted_amount_cents OR NEW.currency <> 'eur' OR
   NEW.payment_provider <> 'paypal' OR NEW.paid_at IS NULL OR NEW.paypal_order_id IS DISTINCT FROM paid.paypal_order_id OR
   NEW.paypal_capture_id IS DISTINCT FROM paid.paypal_capture_id THEN RAISE EXCEPTION 'U04 invalid financial projection'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""))
    for name, table, timing, function in (
        ("u04_attempt_guard", "paypal_payment_attempt", "BEFORE INSERT OR UPDATE", "u04_attempt_guard_fn"),
        ("u04_attempt_delete", "paypal_payment_attempt", "BEFORE DELETE", "u04_no_delete_fn"),
        ("u04_event_append", "paypal_payment_event", "BEFORE UPDATE OR DELETE", "u04_event_append_fn"),
        ("u04_advisory_guard", "fiscal_advisory_requests", "BEFORE UPDATE OR DELETE", "u04_advisory_guard_fn"),
    ):
        connection.execute(text("DROP TRIGGER IF EXISTS " + name + " ON " + table))
        connection.execute(text("CREATE TRIGGER " + name + " " + timing + " ON " + table +
                                " FOR EACH ROW EXECUTE FUNCTION " + function + "()"))
    for name, table in (("u04_event_truncate", "paypal_payment_event"), ("u04_attempt_truncate", "paypal_payment_attempt")):
        connection.execute(text("DROP TRIGGER IF EXISTS " + name + " ON " + table))
        connection.execute(text("CREATE TRIGGER " + name + " BEFORE TRUNCATE ON " + table +
                                " FOR EACH STATEMENT EXECUTE FUNCTION u04_no_delete_fn()"))
