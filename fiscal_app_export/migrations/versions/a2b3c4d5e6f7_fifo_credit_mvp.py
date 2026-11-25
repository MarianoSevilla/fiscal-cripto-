"""FIFO credit pilot ledger; dormant until separately enabled.

Revision ID: a2b3c4d5e6f7
Revises: z9a0b1c2d3e4

No balances are backfilled, no payment is created and no existing FIFO data is
changed. Feature flags stay off by default. Do not enable commercial purchases
until separate product/legal/data-retention approval.
"""
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_wallets (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
            available_credits INTEGER NOT NULL DEFAULT 0
                CONSTRAINT ck_credit_wallet_available CHECK (available_credits >= 0),
            reserved_credits INTEGER NOT NULL DEFAULT 0
                CONSTRAINT ck_credit_wallet_reserved CHECK (reserved_credits >= 0),
            frozen BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_ledger_entries (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            entry_type VARCHAR(24) NOT NULL,
            available_delta INTEGER NOT NULL,
            reserved_delta INTEGER NOT NULL DEFAULT 0,
            idempotency_key VARCHAR(160) NOT NULL UNIQUE,
            reference_id VARCHAR(100),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_credit_ledger_nonzero
                CHECK (available_delta <> 0 OR reserved_delta <> 0)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_purchases (
            id VARCHAR(36) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            package_key VARCHAR(20) NOT NULL,
            amount_cents INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'eur',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            idempotency_key VARCHAR(100) NOT NULL UNIQUE,
            checkout_session_id VARCHAR(255) UNIQUE,
            payment_intent_id VARCHAR(255),
            stripe_event_id VARCHAR(255) UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            paid_at TIMESTAMP,
            CONSTRAINT ck_credit_purchase_status
                CHECK (status IN ('pending','paid','refund_review','refunded','cancelled')),
            CONSTRAINT ck_credit_purchase_amount_credits
                CHECK (amount_cents > 0 AND credits > 0),
            CONSTRAINT ck_credit_purchase_currency CHECK (currency = 'eur')
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_purchases_user_id ON credit_purchases(user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_stripe_event_receipts (
            stripe_event_id VARCHAR(255) PRIMARY KEY,
            purchase_id VARCHAR(36) NOT NULL REFERENCES credit_purchases(id) ON DELETE RESTRICT,
            event_type VARCHAR(100) NOT NULL,
            received_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_analyses (
            id VARCHAR(36) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            idempotency_key VARCHAR(100) NOT NULL,
            exchange VARCHAR(40) NOT NULL,
            fiscal_years VARCHAR(50) NOT NULL,
            csv_rows INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            file_fingerprint VARCHAR(64) NOT NULL,
            reserved_credits INTEGER NOT NULL,
            charged_credits INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(24) NOT NULL DEFAULT 'reserved',
            result_type VARCHAR(24),
            correction_of_id VARCHAR(36) REFERENCES credit_analyses(id) ON DELETE RESTRICT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            correction_expires_at TIMESTAMP NOT NULL,
            CONSTRAINT ck_credit_analysis_status
                CHECK (status IN ('reserved','consumed','released','settlement_unknown')),
            CONSTRAINT ck_credit_analysis_amounts
                CHECK (reserved_credits >= 0 AND charged_credits >= 0 AND charged_credits <= reserved_credits),
            CONSTRAINT uq_credit_analysis_user_key UNIQUE (user_id,idempotency_key),
            CONSTRAINT uq_credit_analysis_free_correction UNIQUE (correction_of_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_analysis_user_created ON credit_analyses(user_id,created_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_report_artifacts (
            analysis_id VARCHAR(36) PRIMARY KEY REFERENCES credit_analyses(id) ON DELETE RESTRICT,
            ciphertext BYTEA NOT NULL,
            key_version VARCHAR(30) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_report_artifacts_expires_at ON credit_report_artifacts(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_ledger_user_created ON credit_ledger_entries(user_id,created_at)")


def downgrade():
    raise RuntimeError("FIFO credit ledger history is financial evidence; destructive downgrade is prohibited")
