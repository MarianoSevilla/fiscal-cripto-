"""Biblioteca de Recursos — tablas resources y resource_requests

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-05-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision      = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on    = None


def upgrade():
    bind       = op.get_bind()
    inspector  = sa_inspect(bind)
    existing   = inspector.get_table_names()
    existing_ix = {
        idx["name"]
        for tbl in existing
        for idx in inspector.get_indexes(tbl)
    }

    if "resources" not in existing:
        op.create_table(
            "resources",
            sa.Column("id",                            sa.Integer(),     nullable=False),
            sa.Column("slug",                          sa.String(100),   nullable=False),
            sa.Column("title",                         sa.String(200),   nullable=False),
            sa.Column("headline",                      sa.String(300),   nullable=True),
            sa.Column("subtitle",                      sa.Text(),        nullable=True),
            sa.Column("description",                   sa.Text(),        nullable=True),
            sa.Column("what_you_get",                  sa.Text(),        nullable=True),
            sa.Column("requirements",                  sa.Text(),        nullable=True),
            sa.Column("cta_text",                      sa.String(100),   nullable=True),
            sa.Column("category",                      sa.String(50),    nullable=True),
            sa.Column("resource_type",                 sa.String(30),    nullable=False),
            sa.Column("interest_category",             sa.String(50),    nullable=True),
            sa.Column("is_active",                     sa.Boolean(),     nullable=False),
            sa.Column("requires_request",              sa.Boolean(),     nullable=False),
            sa.Column("requires_affiliate_validation", sa.Boolean(),     nullable=False),
            sa.Column("storage_provider",              sa.String(30),    nullable=True),
            sa.Column("storage_key",                   sa.String(500),   nullable=True),
            sa.Column("version",                       sa.String(20),    nullable=True),
            sa.Column("created_at",                    sa.DateTime(),    nullable=False),
            sa.Column("updated_at",                    sa.DateTime(),    nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_resources_slug" not in existing_ix:
        op.create_index("ix_resources_slug", "resources", ["slug"], unique=True)

    if "resource_requests" not in existing:
        op.create_table(
            "resource_requests",
            sa.Column("id",                sa.Integer(),     nullable=False),
            sa.Column("resource_id",       sa.Integer(),     nullable=False),
            sa.Column("name",              sa.String(150),   nullable=False),
            sa.Column("email",             sa.String(254),   nullable=False),
            sa.Column("exchange",          sa.String(50),    nullable=True),
            sa.Column("bitvavo_status",    sa.String(50),    nullable=True),
            sa.Column("uid",               sa.String(100),   nullable=True),
            sa.Column("uid_unknown",       sa.Boolean(),     nullable=False),
            sa.Column("telegram_user",     sa.String(100),   nullable=True),
            sa.Column("source",            sa.String(50),    nullable=True),
            sa.Column("legal_accepted",    sa.Boolean(),     nullable=False),
            sa.Column("marketing_consent", sa.Boolean(),     nullable=False),
            sa.Column("status",            sa.String(30),    nullable=False),
            sa.Column("internal_notes",    sa.Text(),        nullable=True),
            sa.Column("ip",                sa.String(45),    nullable=True),
            sa.Column("created_at",        sa.DateTime(),    nullable=False),
            sa.Column("updated_at",        sa.DateTime(),    nullable=True),
            sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for ix_name, tbl, col in [
        ("ix_resource_requests_email",       "resource_requests", "email"),
        ("ix_resource_requests_resource_id", "resource_requests", "resource_id"),
        ("ix_resource_requests_status",      "resource_requests", "status"),
    ]:
        if ix_name not in existing_ix:
            op.create_index(ix_name, tbl, [col])

    # Seed: Dossier Experimento Bitcoin (idempotente — no falla si el slug ya existe)
    op.execute("""
        INSERT INTO resources (
            slug, title, headline, subtitle, description,
            what_you_get, requirements, cta_text,
            category, resource_type, interest_category,
            is_active, requires_request, requires_affiliate_validation,
            storage_provider, storage_key, version,
            created_at, updated_at
        )
        SELECT
            'experimento-bitcoin',
            'Dossier Experimento Bitcoin',
            '¿Qué pasaría si invirtieras una cantidad fija en Bitcoin cada mes durante un año?',
            'Un análisis real, con datos reales, sobre una estrategia DCA aplicada a Bitcoin. Sin promesas, sin humo. Solo números.',
            'Dossier completo sobre el experimento de inversión periódica en Bitcoin. Análisis de resultados, metodología y conclusiones.',
            '- Metodología del experimento explicada paso a paso
- Datos reales de precio y fechas de compra
- Análisis de rentabilidad acumulada
- Reflexiones sobre DCA en Bitcoin a largo plazo
- Gráficas y tablas exportables',
            'Para recibir este dossier necesitas:
- Haberte registrado en Bitvavo a través de uno de los enlaces del canal, o
- Tener ya una cuenta activa en Bitvavo, o
- Estar dispuesto a abrir una cuenta en Bitvavo

Si no tienes claro cuál es tu situación, puedes indicarlo en el formulario y lo revisamos juntos.',
            'Solicitar el dossier',
            'bitcoin',
            'dossier',
            'bitcoin',
            TRUE, TRUE, TRUE,
            NULL, NULL, '1.0',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM resources WHERE slug = 'experimento-bitcoin'
        )
    """)


def downgrade():
    op.drop_index("ix_resource_requests_status",      table_name="resource_requests")
    op.drop_index("ix_resource_requests_resource_id", table_name="resource_requests")
    op.drop_index("ix_resource_requests_email",       table_name="resource_requests")
    op.drop_table("resource_requests")
    op.drop_index("ix_resources_slug", table_name="resources")
    op.drop_table("resources")
