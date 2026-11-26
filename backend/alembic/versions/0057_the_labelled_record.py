"""The labelled record.

Slice 052 (DB §2.6 to §2.9; decisions 79 and 81, assertions 533, 551 to 556
and 561): a Transcript's `labelled_under`, the labeller's own version, and
its `records_stamp`; a Launch's Work Unit; a Call's Wait Cause, Segment, Call
Class and Avoidable Kind; a Tool Call's Command Class and Tool Effect Kind
with its subject; a Document's Ask Category; an Event and a Context Part
marked `labelled` where the labeller gave them; and `work_units`,
`work_unit_measures`, `segments`, `rule_breaches`, `test_suites`, `tests`,
`test_runs`, `test_failures`, `ci_builds` and `ci_waits`. Nothing writes a
label here: every Event and Context Part held is the collector's.

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABELS: dict[str, list[tuple[str, str]]] = {
    "calls": [
        ("wait_cause_code", "wait_causes.code"),
        ("call_class_code", "call_classes.code"),
        ("avoidable_kind_code", "avoidable_kinds.code"),
    ],
    "tool_calls": [
        ("command_class_code", "command_classes.code"),
        ("effect_kind_code", "tool_effect_kinds.code"),
    ],
    "documents": [("ask_category_code", "ask_categories.code")],
}
"""The labels that are a reference entity's code, by the table that holds
them: each column and the key it names."""

MARKED = ("events", "context_parts")
"""The tables whose rows are the collector's or the labeller's."""


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "work_units",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("part_of_id", sa.BigInteger(), nullable=True),
        sa.Column("part_of_kind_code", sa.Text(), nullable=True),
        sa.Column("occasioned_by_id", sa.BigInteger(), nullable=True),
        sa.Column("rework_kind_code", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("outcome_code", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("card", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(part_of_id IS NULL) = (part_of_kind_code IS NULL)",
            name="ck_work_units_part_of",
        ),
        sa.CheckConstraint(
            "part_of_id <> id AND occasioned_by_id <> id",
            name="ck_work_units_not_itself",
        ),
        sa.CheckConstraint("round >= 1", name="ck_work_units_round"),
        sa.ForeignKeyConstraint(["kind_code"], ["work_unit_kinds.code"]),
        sa.ForeignKeyConstraint(
            ["kind_code", "part_of_kind_code"],
            [
                "work_unit_kind_nestings.inner_code",
                "work_unit_kind_nestings.outer_code",
            ],
        ),
        sa.ForeignKeyConstraint(["occasioned_by_id"], ["work_units.id"]),
        sa.ForeignKeyConstraint(["outcome_code"], ["unit_outcomes.code"]),
        sa.ForeignKeyConstraint(
            ["part_of_id", "part_of_kind_code"],
            ["work_units.id", "work_units.kind_code"],
        ),
        sa.ForeignKeyConstraint(["rework_kind_code"], ["rework_kinds.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "kind_code"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "work_unit_measures",
        sa.Column("work_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("measure_code", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["measure_code"], ["unit_measures.code"]),
        sa.ForeignKeyConstraint(["work_unit_id"], ["work_units.id"]),
        sa.PrimaryKeyConstraint("work_unit_id", "measure_code"),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_segments_position"),
        sa.ForeignKeyConstraint(["kind_code"], ["segment_kinds.code"]),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "position"),
    )
    op.create_table(
        "test_suites",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "tests",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("suite_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["suite_id"], ["test_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "suite_id"),
        sa.UniqueConstraint("suite_id", "name"),
    )
    op.create_table(
        "ci_builds",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("job", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.Text(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("number >= 1", name="ck_ci_builds_number"),
        sa.ForeignKeyConstraint(["result_code"], ["build_results.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job", "number"),
    )

    op.add_column(
        "transcripts",
        sa.Column(
            "labelled_under_id",
            sa.BigInteger(),
            sa.ForeignKey("component_versions.id"),
            nullable=True,
        ),
    )
    op.add_column("transcripts", sa.Column("records_stamp", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_transcripts_records_stamp",
        "transcripts",
        "records_stamp IS NULL OR labelled_under_id IS NOT NULL",
    )
    op.add_column(
        "launches",
        sa.Column(
            "work_unit_id",
            sa.BigInteger(),
            sa.ForeignKey("work_units.id"),
            nullable=True,
        ),
    )
    for table, columns in LABELS.items():
        for column, key in columns:
            op.add_column(
                table, sa.Column(column, sa.Text(), sa.ForeignKey(key), nullable=True)
            )
    op.add_column("calls", sa.Column("segment_position", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "calls_transcript_id_segment_position_fkey",
        "calls",
        "segments",
        ["transcript_id", "segment_position"],
        ["transcript_id", "position"],
    )
    op.add_column("tool_calls", sa.Column("effect_subject", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_tool_calls_effect_subject",
        "tool_calls",
        "effect_subject IS NULL OR effect_kind_code IS NOT NULL",
    )
    op.create_unique_constraint(
        "tool_calls_transcript_id_id_key", "tool_calls", ["transcript_id", "id"]
    )
    for table in MARKED:
        op.add_column(
            table,
            sa.Column(
                "labelled", sa.Boolean(), server_default=sa.false(), nullable=False
            ),
        )

    op.create_table(
        "test_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.BigInteger(), nullable=True),
        sa.Column("work_unit_id", sa.BigInteger(), nullable=True),
        sa.Column("ci_build_id", sa.BigInteger(), nullable=True),
        sa.Column("suite_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("tests", sa.Integer(), nullable=False),
        sa.Column("retries_allowed", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "num_nonnulls(tool_call_id, work_unit_id, ci_build_id) = 1",
            name="ck_test_runs_runner",
        ),
        sa.CheckConstraint(
            "tests >= 0 AND retries_allowed >= 0", name="ck_test_runs_counts"
        ),
        sa.ForeignKeyConstraint(["ci_build_id"], ["ci_builds.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["test_suites.id"]),
        sa.ForeignKeyConstraint(
            ["transcript_id", "tool_call_id"],
            ["tool_calls.transcript_id", "tool_calls.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.ForeignKeyConstraint(["work_unit_id"], ["work_units.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "suite_id"),
    )
    op.create_index(
        "ix_test_runs_transcript_id_tool_call_id",
        "test_runs",
        ["transcript_id", "tool_call_id"],
    )
    op.create_table(
        "test_failures",
        sa.Column("test_run_id", sa.BigInteger(), nullable=False),
        sa.Column("test_id", sa.BigInteger(), nullable=False),
        sa.Column("suite_id", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("flaky", sa.Boolean(), nullable=False),
        sa.CheckConstraint("attempts >= 1", name="ck_test_failures_attempts"),
        sa.ForeignKeyConstraint(
            ["test_id", "suite_id"], ["tests.id", "tests.suite_id"]
        ),
        sa.ForeignKeyConstraint(
            ["test_run_id", "suite_id"],
            ["test_runs.id", "test_runs.suite_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("test_run_id", "test_id"),
    )
    op.create_table(
        "ci_waits",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=False),
        sa.Column("ci_build_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["ci_build_id"], ["ci_builds.id"]),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tool_call_id", "ci_build_id"),
    )
    op.create_table(
        "rule_breaches",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["rule_code"], ["rules.code"]),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tool_call_id", "rule_code"),
    )


def downgrade() -> None:
    """Downgrade database schema: every label is lost, and the labeller's
    Events and Context Parts with them."""
    op.drop_table("rule_breaches")
    op.drop_table("ci_waits")
    op.drop_table("test_failures")
    op.drop_index("ix_test_runs_transcript_id_tool_call_id", table_name="test_runs")
    op.drop_table("test_runs")
    for table in reversed(MARKED):
        op.execute(sa.text(f"DELETE FROM {table} WHERE labelled"))
        op.drop_column(table, "labelled")
    op.drop_constraint("tool_calls_transcript_id_id_key", "tool_calls", type_="unique")
    op.drop_constraint("ck_tool_calls_effect_subject", "tool_calls", type_="check")
    op.drop_column("tool_calls", "effect_subject")
    op.drop_constraint(
        "calls_transcript_id_segment_position_fkey", "calls", type_="foreignkey"
    )
    op.drop_column("calls", "segment_position")
    for table, columns in reversed(LABELS.items()):
        for column, _ in reversed(columns):
            op.drop_column(table, column)
    op.drop_column("launches", "work_unit_id")
    op.drop_constraint("ck_transcripts_records_stamp", "transcripts", type_="check")
    op.drop_column("transcripts", "records_stamp")
    op.drop_column("transcripts", "labelled_under_id")
    op.drop_table("ci_builds")
    op.drop_table("tests")
    op.drop_table("test_suites")
    op.drop_table("segments")
    op.drop_table("work_unit_measures")
    op.drop_table("work_units")
