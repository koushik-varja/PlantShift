"""Initial PlantShift schema: Timescale telemetry + global idempotency ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interventions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
    )
    op.create_index("ix_scenario_runs_name", "scenario_runs", ["name"])
    op.create_index("ix_scenario_runs_created_at", "scenario_runs", ["created_at"])

    op.create_table(
        "processed_event_ids",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_processed_event_ids_first_seen_at",
        "processed_event_ids",
        ["first_seen_at"],
    )

    op.create_table(
        "telemetry_events",
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "timestamp"),
    )
    op.create_index(
        "ix_telemetry_events_machine_id",
        "telemetry_events",
        ["machine_id"],
    )
    op.create_index("ix_telemetry_events_timestamp", "telemetry_events", ["timestamp"])
    op.create_index(
        "ix_telemetry_events_ingest_timestamp",
        "telemetry_events",
        ["ingest_timestamp"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SELECT create_hypertable('telemetry_events', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE)")


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_events_ingest_timestamp",
        table_name="telemetry_events",
    )
    op.drop_index("ix_telemetry_events_timestamp", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_machine_id", table_name="telemetry_events")
    op.drop_table("telemetry_events")
    op.drop_index(
        "ix_processed_event_ids_first_seen_at",
        table_name="processed_event_ids",
    )
    op.drop_table("processed_event_ids")
    op.drop_index("ix_scenario_runs_created_at", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_name", table_name="scenario_runs")
    op.drop_table("scenario_runs")
