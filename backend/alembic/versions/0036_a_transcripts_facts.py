"""A transcript's facts: Transcript, Launch, Prompt, Call and what hangs on them.

The tables a collector's publication of a transcript fills, with the
collector's reference entities, whose rows a publication writes and no
revision (DB decisions 79 and 81; §2.6, §2.7, §2.9 Repository, §2.11 and §7.7;
the assertions of §4.31 and §4.33). A Call's tokens are a column per Token
Kind on its own row.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFERENCE_TABLES = (
    "components",
    "prompt_sources",
    "compaction_triggers",
    "models",
    "stop_reasons",
    "miss_causes",
    "denial_kinds",
    "context_part_kinds",
)
"""The collector's reference entities that hold a code and a name alone."""


def upgrade() -> None:
    """Upgrade database schema."""
    for table in REFERENCE_TABLES:
        op.create_table(
            table,
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("code"),
        )
    op.create_table(
        "tools",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mcp_server", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "event_kinds",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_error", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "component_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("component_code", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["component_code"], ["components.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("component_code", "version"),
        sa.UniqueConstraint("id", "component_code"),
    )
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("main_id", sa.Uuid(), nullable=True),
        sa.Column("spawned_by_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("working_directory", sa.Text(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("environment_id", sa.Text(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replayed_size", sa.BigInteger(), nullable=False),
        sa.Column("read_under_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "agent_id IS NOT NULL OR (main_id IS NULL AND spawned_by_id IS NULL)",
            name="ck_transcripts_main_thread",
        ),
        sa.CheckConstraint(
            "agent_id IS NULL OR environment_id IS NULL",
            name="ck_transcripts_environment",
        ),
        sa.CheckConstraint("file_size >= 0", name="ck_transcripts_file_size"),
        sa.CheckConstraint(
            "replayed_size >= 0 AND replayed_size <= file_size",
            name="ck_transcripts_replayed_size",
        ),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"]),
        sa.ForeignKeyConstraint(["main_id"], ["transcripts.id"]),
        sa.ForeignKeyConstraint(["read_under_id"], ["component_versions.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_transcripts_session_id_agent_id",
        "transcripts",
        ["session_id", "agent_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_transcripts_spawned_by_id",
        "transcripts",
        ["spawned_by_id"],
        postgresql_where=sa.text("spawned_by_id IS NOT NULL"),
    )
    op.create_table(
        "launches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "id"),
    )
    op.create_table(
        "launch_components",
        sa.Column("launch_id", sa.BigInteger(), nullable=False),
        sa.Column("component_version_id", sa.BigInteger(), nullable=False),
        sa.Column("component_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["component_version_id", "component_code"],
            ["component_versions.id", "component_versions.component_code"],
        ),
        sa.ForeignKeyConstraint(["launch_id"], ["launches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("launch_id", "component_version_id"),
        sa.UniqueConstraint("launch_id", "component_code"),
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("launch_id", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.CheckConstraint("characters >= 0", name="ck_prompts_characters"),
        sa.ForeignKeyConstraint(["source_code"], ["prompt_sources.code"]),
        sa.ForeignKeyConstraint(
            ["transcript_id", "launch_id"],
            ["launches.transcript_id", "launches.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "id"),
    )
    op.create_index("ix_prompts_launch_id", "prompts", ["launch_id"])
    op.create_table(
        "hook_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("prompt_id", sa.BigInteger(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("prevented_end", sa.Boolean(), nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_hook_runs_duration_ms"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hook_runs_prompt_id", "hook_runs", ["prompt_id"])
    op.create_table(
        "compactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_code", sa.Text(), nullable=False),
        sa.Column("tokens_before", sa.Integer(), nullable=False),
        sa.Column("tokens_after", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "tokens_before >= 0 AND tokens_after >= 0", name="ck_compactions_tokens"
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_compactions_duration_ms"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.ForeignKeyConstraint(["trigger_code"], ["compaction_triggers.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "id"),
    )
    op.create_table(
        "calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.BigInteger(), nullable=True),
        sa.Column("predecessor_id", sa.BigInteger(), nullable=True),
        sa.Column("compaction_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_code", sa.Text(), nullable=False),
        sa.Column("requested_model_code", sa.Text(), nullable=True),
        sa.Column("effort", sa.Text(), nullable=True),
        sa.Column("stop_reason_code", sa.Text(), nullable=True),
        sa.Column("thinking_tokens", sa.Integer(), nullable=True),
        sa.Column("attributed_skill", sa.Text(), nullable=True),
        sa.Column("attributed_plugin", sa.Text(), nullable=True),
        sa.Column("miss_cause_code", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_5m_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_1h_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_calls_position"),
        sa.CheckConstraint(
            "requested_model_code <> model_code", name="ck_calls_requested_model"
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND cache_write_5m_tokens >= 0"
            " AND cache_write_1h_tokens >= 0 AND cache_read_tokens >= 0"
            " AND output_tokens >= 0 AND thinking_tokens >= 0",
            name="ck_calls_tokens",
        ),
        sa.ForeignKeyConstraint(["miss_cause_code"], ["miss_causes.code"]),
        sa.ForeignKeyConstraint(["model_code"], ["models.code"]),
        sa.ForeignKeyConstraint(["requested_model_code"], ["models.code"]),
        sa.ForeignKeyConstraint(["stop_reason_code"], ["stop_reasons.code"]),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.ForeignKeyConstraint(
            ["transcript_id", "compaction_id"],
            ["compactions.transcript_id", "compactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "predecessor_id"], ["calls.transcript_id", "calls.id"]
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "prompt_id"], ["prompts.transcript_id", "prompts.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "id"),
        sa.UniqueConstraint("transcript_id", "message_id"),
        sa.UniqueConstraint(
            "transcript_id",
            "position",
            name="uq_calls_transcript_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_use_id", sa.Text(), nullable=False),
        sa.Column("tool_code", sa.Text(), nullable=False),
        sa.Column("first_argument", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("denial_kind_code", sa.Text(), nullable=True),
        sa.Column("result_characters", sa.Integer(), nullable=True),
        sa.Column("saved_characters", sa.Integer(), nullable=True),
        sa.CheckConstraint("exit_code <> 0", name="ck_tool_calls_exit_code"),
        sa.CheckConstraint(
            "denial_kind_code IS DISTINCT FROM 'hook' OR failed",
            name="ck_tool_calls_denied_by_hook",
        ),
        sa.CheckConstraint(
            "result_characters >= 0 AND saved_characters >= 0",
            name="ck_tool_calls_characters",
        ),
        sa.ForeignKeyConstraint(["denial_kind_code"], ["denial_kinds.code"]),
        sa.ForeignKeyConstraint(["tool_code"], ["tools.code"]),
        sa.ForeignKeyConstraint(
            ["transcript_id", "call_id"],
            ["calls.transcript_id", "calls.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "tool_use_id"),
    )
    op.create_index("ix_tool_calls_call_id", "tool_calls", ["call_id"])
    op.create_foreign_key(
        "transcripts_spawned_by_id_fkey",
        "transcripts",
        "tool_calls",
        ["spawned_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("call_id", sa.BigInteger(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind_code NOT IN ('compaction', 'rewind', 'cache_miss', 'past_ttl',"
            " 'model_fallback', 'max_tokens', 'refusal', 'output_saved', 'denied',"
            " 'hook_error')",
            name="ck_events_kind",
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kind_code"], ["event_kinds.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_call_id", "events", ["call_id"])
    op.create_table(
        "context_parts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("call_id", sa.BigInteger(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.CheckConstraint("characters >= 0", name="ck_context_parts_characters"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kind_code"], ["context_part_kinds.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_context_parts_call_id", "context_parts", ["call_id"])


def downgrade() -> None:
    """Downgrade database schema: every transcript's facts are lost."""
    op.drop_table("context_parts")
    op.drop_table("events")
    op.drop_constraint(
        "transcripts_spawned_by_id_fkey", "transcripts", type_="foreignkey"
    )
    op.drop_table("tool_calls")
    op.drop_table("calls")
    op.drop_table("compactions")
    op.drop_table("hook_runs")
    op.drop_table("prompts")
    op.drop_table("launch_components")
    op.drop_table("launches")
    op.drop_table("transcripts")
    op.drop_table("component_versions")
    op.drop_table("repositories")
    op.drop_table("event_kinds")
    op.drop_table("tools")
    for table in reversed(REFERENCE_TABLES):
        op.drop_table(table)
