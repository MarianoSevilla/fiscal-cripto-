"""Actualiza headline y subtitle del Dossier Experimento Bitcoin

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-06-01 00:00:00.000000

Cambio
------
  headline: nuevo título editorial
  subtitle: nuevo subtítulo con <em> para resalte verde
"""

from alembic import op
import sqlalchemy as sa

revision      = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on    = None

_SLUG = "experimento-bitcoin"

_NEW_HEADLINE = (
    "El Experimento Bitcoin: La diferencia entre "
    "una <em>estrategia</em> y una predicción"
)

_NEW_SUBTITLE = (
    "Un experimento de inversión documentado públicamente. "
    "Analizamos patrones históricos, contrastamos los datos actuales "
    "y adaptamos la estrategia cuando aparecen nuevas evidencias. "
    "<em>Sin promesas. Sin predicciones. Solo análisis.</em>"
)

_OLD_HEADLINE = (
    "¿Qué pasaría si invirtieras una cantidad fija "
    "en Bitcoin cada mes durante un año?"
)

_OLD_SUBTITLE = (
    "Un análisis real, con datos reales, sobre una estrategia DCA "
    "aplicada a Bitcoin. Sin promesas, sin humo. Solo números."
)


def upgrade():
    op.execute(
        sa.text(
            "UPDATE resources SET headline = :h, subtitle = :s "
            "WHERE slug = :slug"
        ).bindparams(h=_NEW_HEADLINE, s=_NEW_SUBTITLE, slug=_SLUG)
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE resources SET headline = :h, subtitle = :s "
            "WHERE slug = :slug"
        ).bindparams(h=_OLD_HEADLINE, s=_OLD_SUBTITLE, slug=_SLUG)
    )
