"""Audit log de asesoramiento, campo is_test y estado archived

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-06-05 00:00:00.000000

Cambios
-------
  1. CREATE TABLE advisory_audit_log
       id, request_id (nullable), admin_id (FK users), action, detail, created_at
  2. ALTER TABLE fiscal_advisory_requests ADD COLUMN is_test BOOLEAN DEFAULT FALSE
       Idempotente con IF NOT EXISTS.
"""

from alembic import op
import sqlalchemy as sa

revision      = "r1s2t3u4v5w6"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on    = None


def upgrade():
    # 1. Tabla de auditoría
    op.execute("""
        CREATE TABLE IF NOT EXISTS advisory_audit_log (
            id         SERIAL PRIMARY KEY,
            request_id INTEGER,
            admin_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action     VARCHAR(50) NOT NULL,
            detail     TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_advisory_audit_log_request_id ON advisory_audit_log(request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_advisory_audit_log_action     ON advisory_audit_log(action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_advisory_audit_log_created_at ON advisory_audit_log(created_at)")

    # 2. Campo is_test
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS advisory_audit_log")
    op.execute("ALTER TABLE fiscal_advisory_requests DROP COLUMN IF EXISTS is_test")
