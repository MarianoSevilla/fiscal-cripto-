"""fase2a fifo_reports telemetry columns

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-14 00:00:00.000000

Añade 10 columnas de telemetría estratégica a fifo_reports para product
analytics: complejidad FIFO, resultado fiscal, años cubiertos.
Todas son nullable para mantener compatibilidad con registros anteriores.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("fifo_reports") as batch_op:
        batch_op.add_column(sa.Column("fifo_operations",   sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("fifo_swaps",        sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("fifo_rendimientos", sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("fifo_movimientos",  sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("fifo_advertencias", sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("fifo_desconocidas", sa.Integer(),     nullable=True))
        batch_op.add_column(sa.Column("resultado_neto",    sa.Float(),       nullable=True))
        batch_op.add_column(sa.Column("ganancias_brutas",  sa.Float(),       nullable=True))
        batch_op.add_column(sa.Column("perdidas_brutas",   sa.Float(),       nullable=True))
        batch_op.add_column(sa.Column("fiscal_years_str",  sa.String(50),    nullable=True))


def downgrade():
    with op.batch_alter_table("fifo_reports") as batch_op:
        batch_op.drop_column("fiscal_years_str")
        batch_op.drop_column("perdidas_brutas")
        batch_op.drop_column("ganancias_brutas")
        batch_op.drop_column("resultado_neto")
        batch_op.drop_column("fifo_desconocidas")
        batch_op.drop_column("fifo_advertencias")
        batch_op.drop_column("fifo_movimientos")
        batch_op.drop_column("fifo_rendimientos")
        batch_op.drop_column("fifo_swaps")
        batch_op.drop_column("fifo_operations")
