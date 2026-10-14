"""S01: reserva durable de intento Stripe Checkout (sin activar pagos).

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2

Solo modelos/esquema. NO puede instalarse en producción hasta resolver el
orden de Alembic respecto a U04 #29, y el bloqueo PREFREEZE #30.
"""
from alembic import op

revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    # El esquema financiero se crea exclusivamente por la migración; app.py
    # ya no ejecuta ORM create_all() al importar. Los nombres de CHECK deben
    # coincidir con el contrato del gate de arranque READ ONLY (G04).
    # CREATE IF NOT EXISTS preserva esquemas preexistentes; el gate valida drift.
    op.execute("""
        CREATE TABLE IF NOT EXISTS s01_stripe_checkout_attempts (
            id VARCHAR(36) PRIMARY KEY,
            advisory_id INTEGER NOT NULL
                REFERENCES fiscal_advisory_requests(id) ON DELETE RESTRICT,
            quote_fingerprint VARCHAR(64) NOT NULL,
            idempotency_key VARCHAR(100) NOT NULL UNIQUE,
            expected_amount_cents INTEGER NOT NULL
                CONSTRAINT ck_s01_attempt_amount
                CHECK (expected_amount_cents >= 100 AND expected_amount_cents <= 99999999),
            currency VARCHAR(3) NOT NULL DEFAULT 'eur'
                CONSTRAINT ck_s01_attempt_currency
                CHECK (currency = 'eur'),
            status VARCHAR(24) NOT NULL DEFAULT 'reserved',
            checkout_session_id VARCHAR(255) UNIQUE,
            payment_intent_id VARCHAR(255),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_s01_attempt_advisory UNIQUE (advisory_id),
            CONSTRAINT ck_s01_checkout_status CHECK (
                status IN ('reserved','creating','ready','uncertain','paid','closed')
            )
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS s01_stripe_event_receipts (
            stripe_event_id VARCHAR(255) PRIMARY KEY,
            attempt_id VARCHAR(36) NOT NULL
                REFERENCES s01_stripe_checkout_attempts(id) ON DELETE RESTRICT,
            event_type VARCHAR(100) NOT NULL,
            received_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_s01_attempt_status "
        "ON s01_stripe_checkout_attempts (status)"
    )


def downgrade():
    # No ejecutar downgrade en entornos con eventos/pagos potenciales.
    # Conservar trazabilidad para conciliación y auditoría financiera.
    raise RuntimeError("S01 financial attempt history is non-destructive; downgrade forbidden")
