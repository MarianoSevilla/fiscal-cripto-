"""U04 persistent PayPal reconciliation; additive, no historical inference."""
from alembic import op
import sqlalchemy as sa

revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None

def upgrade():
    from paypal_models import PayPalPaymentAttempt, PayPalPaymentEvent
    from paypal_schema import verify_structure, install_guards
    connection = op.get_bind()
    columns = {c["name"] for c in sa.inspect(connection).get_columns("fiscal_advisory_requests")}
    if "paypal_quote_generation" not in columns:
        op.add_column("fiscal_advisory_requests", sa.Column("paypal_quote_generation", sa.Uuid(as_uuid=False), nullable=True))
    if "paypal_review_hold" not in columns:
        op.add_column("fiscal_advisory_requests", sa.Column("paypal_review_hold", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Import-time create_all may already have created both tables. Never replace
    # or reshape incompatible pre-existing structures.
    tables = {PayPalPaymentAttempt.__table__, PayPalPaymentEvent.__table__}
    present = {t.name for t in tables if sa.inspect(connection).has_table(t.name)}
    if present and present != {t.name for t in tables}:
        raise RuntimeError("U04 partial financial schema; manual review required")
    if not present:
        metadata = sa.MetaData()
        for t in tables:
            t.to_metadata(metadata)
        # Referenced parent tables are supplied by the existing model metadata.
        from models import db
        for t in (db.metadata.tables["users"], db.metadata.tables["fiscal_advisory_requests"]):
            t.to_metadata(metadata)
        metadata.create_all(connection, tables=[metadata.tables["paypal_payment_attempt"], metadata.tables["paypal_payment_event"]])
    verify_structure(connection, triggers=False)
    if connection.dialect.name == "postgresql":
        install_guards(connection)
        verify_structure(connection)

def downgrade():
    raise RuntimeError("U04 destructive downgrade prohibited: preserve attempts, evidence and holds; use compatible read-only rollback")
