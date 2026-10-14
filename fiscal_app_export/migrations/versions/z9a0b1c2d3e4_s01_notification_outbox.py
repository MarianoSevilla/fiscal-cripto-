"""S01 TEST: outbox de avisos atómica con la confirmación Stripe.

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3

Sin enviar emails, sin datos personales ni backfill automático. La migración
no debe aplicarse en producción mientras #29 y secuencia S01 no se reconcilien.
"""
from alembic import op

revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    # El proyecto ejecuta ORM create_all durante el arranque; no reconstruir
    # tablas ya creadas al iniciar una base de datos fresca en CI.
    op.execute("""
        CREATE TABLE IF NOT EXISTS s01_stripe_notification_outbox (
            id SERIAL PRIMARY KEY,
            attempt_id VARCHAR(36) NOT NULL
                REFERENCES s01_stripe_checkout_attempts(id) ON DELETE RESTRICT,
            kind VARCHAR(40) NOT NULL,
            delivery_key VARCHAR(128) NOT NULL UNIQUE,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMP,
            CONSTRAINT uq_s01_outbox_attempt_kind UNIQUE (attempt_id, kind),
            CONSTRAINT ck_s01_outbox_kind CHECK (
                kind IN ('customer_payment_confirmed',
                         'advisor_payment_confirmed')
            ),
            CONSTRAINT ck_s01_outbox_status CHECK (
                status IN ('pending','sent','suppressed')
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_s01_outbox_status
        ON s01_stripe_notification_outbox (status)
    """)


def downgrade():
    raise RuntimeError(
        "S01 notification outbox is part of the financial audit trail; "
        "destructive downgrade is prohibited."
    )
