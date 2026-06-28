"""Create incidents table

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-06-28 00:00:00.000000

Cambios
-------
  1. CREATE TABLE incidents
     Tabla de Incidencias — Sprint 2 de Observabilidad.
     Agrupa N ProcessingError por fingerprint (relación lógica, sin FK).
     UNIQUE CONSTRAINT en fingerprint garantiza unicidad bajo concurrencia.
     Idempotente con IF NOT EXISTS.

  Índices creados:
    - ix_incidents_status       ON incidents (status)
    - ix_incidents_last_seen_at ON incidents (last_seen_at)
    - ix_incidents_exchange     ON incidents (exchange)
    (fingerprint ya tiene índice implícito por UNIQUE CONSTRAINT)

  Nota: el backfill de fingerprints históricos es un paso separado
  ejecutado fuera de esta migración (backfill_incidents_from_processing_errors).
"""
from alembic import op


revision      = 'v5w6x7y8z9a0'
down_revision = 'u4v5w6x7y8z9'
branch_labels = None
depends_on    = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id               SERIAL PRIMARY KEY,
            fingerprint      VARCHAR(16)  NOT NULL,
            exchange         VARCHAR(50),
            stage            VARCHAR(50),
            error_type       VARCHAR(100),
            error_category   VARCHAR(50),
            error_code       VARCHAR(50),
            status           VARCHAR(30)  NOT NULL DEFAULT 'nueva',
            title            VARCHAR(200),
            notes            TEXT,
            first_seen_at    TIMESTAMP    NOT NULL,
            last_seen_at     TIMESTAMP    NOT NULL,
            event_count      INTEGER      NOT NULL DEFAULT 1,
            regression_count INTEGER      NOT NULL DEFAULT 0,
            created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
            resolved_at      TIMESTAMP,
            CONSTRAINT uq_incidents_fingerprint UNIQUE (fingerprint)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_incidents_status "
        "ON incidents (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_incidents_last_seen_at "
        "ON incidents (last_seen_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_incidents_exchange "
        "ON incidents (exchange)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS incidents")
