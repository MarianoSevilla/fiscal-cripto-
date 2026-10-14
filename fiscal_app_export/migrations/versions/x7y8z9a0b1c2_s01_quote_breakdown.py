"""S01: snapshots del desglose de presupuestos de asesoramiento.

Revision ID: x7y8z9a0b1c2
Revises: v5w6x7y8z9a0

No se realiza backfill de presupuestos legacy: nunca debe atribuirse
retroactivamente una comisión a un presupuesto cuyo desglose se desconoce.
Esta revisión parte de main, y necesitará reconciliarse con la rama U04
(w6x7y8z9a0b1) antes de cualquier integración conjunta.
"""
from alembic import op

revision = "x7y8z9a0b1c2"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "ADD COLUMN IF NOT EXISTS rafa_fee_cents INTEGER"
    )
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "ADD COLUMN IF NOT EXISTS commission_cents INTEGER"
    )
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "ADD COLUMN IF NOT EXISTS commission_rate_bps INTEGER"
    )


def downgrade():
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "DROP COLUMN IF EXISTS commission_rate_bps"
    )
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "DROP COLUMN IF EXISTS commission_cents"
    )
    op.execute(
        "ALTER TABLE fiscal_advisory_requests "
        "DROP COLUMN IF EXISTS rafa_fee_cents"
    )
