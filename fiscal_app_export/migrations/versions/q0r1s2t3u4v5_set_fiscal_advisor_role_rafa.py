"""Asigna role='fiscal_advisor' a rafaramosmart@gmail.com

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-06-04 00:00:00.000000

Cambio
------
  UPDATE users SET role='fiscal_advisor'
  WHERE email='rafaramosmart@gmail.com' AND role='user'

  Idempotente: solo actualiza si el rol actual es 'user'.
  Si ya tiene 'fiscal_advisor' o 'admin', no hace nada.
"""

from alembic import op

revision      = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on    = None


def upgrade():
    op.execute(
        "UPDATE users SET role = 'fiscal_advisor' "
        "WHERE email = 'rafaramosmart@gmail.com' AND role = 'user'"
    )


def downgrade():
    op.execute(
        "UPDATE users SET role = 'user' "
        "WHERE email = 'rafaramosmart@gmail.com' AND role = 'fiscal_advisor'"
    )
