"""Work Unit, Work Unit Measure and Segment (DB §2.8), and Rule Breach, Test
Suite, Test, Test Run, Test Failure, CI Build and CI Wait (§2.9): what the
labeller recognised in a Transcript and in the run records, which Pilot holds
as labels (DB decisions 79.23 and 81, assertion 561).

A Work Unit, a Test Suite, a Test and a CI Build are written by their keys
and stay at a relabel: no one Transcript's labels own them. A Work Unit
Measure is its unit's, written with it as a labelling that gives the unit
lists them. Every other row here is a label of one Transcript's, replaced
with its labels.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

PLACING = (
    "work_units_part_of_id_part_of_kind_code_fkey",
    "work_units_kind_code_part_of_kind_code_fkey",
)
"""The keys that place a Work Unit in another, checked at each statement
unless a transaction defers them."""


class WorkUnit(db.Model):  # type: ignore[name-defined]
    """A piece of work the labeller recognised, at any level its Work Unit
    Kinds declare, by the labeller's `key`, which is the same at every
    relabel.

    `part_of_kind_code` is the kind of the unit it sits in, and follows that
    unit's kind, so that it sits there only where a Work Unit Kind Nesting
    pairs the two kinds, its own as inner (DB 551). That no unit is part of
    itself or occasioned by itself through others (DB 552) is the writer's to
    keep.
    """

    __tablename__ = "work_units"
    __table_args__ = (
        # What a unit's key to the unit it sits in references.
        UniqueConstraint("id", "kind_code"),
        ForeignKeyConstraint(
            ["part_of_id", "part_of_kind_code"],
            ["work_units.id", "work_units.kind_code"],
            name=PLACING[0],
            onupdate="CASCADE",
            deferrable=True,
        ),
        ForeignKeyConstraint(
            ["kind_code", "part_of_kind_code"],
            [
                "work_unit_kind_nestings.inner_code",
                "work_unit_kind_nestings.outer_code",
            ],
            name=PLACING[1],
            deferrable=True,
        ),
        CheckConstraint(
            "(part_of_id IS NULL) = (part_of_kind_code IS NULL)",
            name="ck_work_units_part_of",
        ),
        CheckConstraint(
            "part_of_id <> id AND occasioned_by_id <> id",
            name="ck_work_units_not_itself",
        ),
        CheckConstraint("round >= 1", name="ck_work_units_round"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(Text, unique=True)
    kind_code: Mapped[str] = mapped_column(ForeignKey("work_unit_kinds.code"))
    part_of_id: Mapped[int | None] = mapped_column(BigInteger)
    part_of_kind_code: Mapped[str | None] = mapped_column(Text)
    occasioned_by_id: Mapped[int | None] = mapped_column(ForeignKey("work_units.id"))
    rework_kind_code: Mapped[str | None] = mapped_column(
        ForeignKey("rework_kinds.code")
    )
    title: Mapped[str] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    round: Mapped[int | None] = mapped_column(Integer)
    outcome_code: Mapped[str | None] = mapped_column(ForeignKey("unit_outcomes.code"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    card: Mapped[str | None] = mapped_column(Text)


class WorkUnitMeasure(db.Model):  # type: ignore[name-defined]
    """A figure the labeller read for one Work Unit, of one Unit Measure, in
    that measure's unit."""

    __tablename__ = "work_unit_measures"

    work_unit_id: Mapped[int] = mapped_column(
        ForeignKey("work_units.id"), primary_key=True
    )
    measure_code: Mapped[str] = mapped_column(
        ForeignKey("unit_measures.code"), primary_key=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric)


class Segment(db.Model):  # type: ignore[name-defined]
    """A stretch of one Transcript the labeller classified by what its
    Transcript was doing, at `position` among its Transcript's Segments,
    from 1. A Call names the Segment it falls in by that `position`, as the
    labeller does. That a Transcript's Segments hold the positions 1 to
    their number and cover its Calls in their order (DB 554) is the
    writer's to keep."""

    __tablename__ = "segments"
    __table_args__ = (
        # What a Call's key to the Segment it falls in references.
        UniqueConstraint("transcript_id", "position"),
        CheckConstraint("position >= 1", name="ck_segments_position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id"))
    position: Mapped[int] = mapped_column(Integer)
    kind_code: Mapped[str] = mapped_column(ForeignKey("segment_kinds.code"))


class RuleBreach(db.Model):  # type: ignore[name-defined]
    """A breach of one Rule by one Tool Call, as the labeller's pattern
    recognises it."""

    __tablename__ = "rule_breaches"

    tool_call_id: Mapped[int] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), primary_key=True
    )
    rule_code: Mapped[str] = mapped_column(ForeignKey("rules.code"), primary_key=True)


class TestSuite(db.Model):  # type: ignore[name-defined]
    """A suite of tests a project can run, by the labeller's `code` for it."""

    # pytest collects a class whose name starts with `Test` from a test
    # module that imports it.
    __test__ = False

    __tablename__ = "test_suites"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class Test(db.Model):  # type: ignore[name-defined]
    """A test case as its Test Suite names it."""

    __test__ = False

    __tablename__ = "tests"
    __table_args__ = (
        UniqueConstraint("suite_id", "name"),
        # What a Test Failure's key references, so its Test is of its Test
        # Run's suite.
        UniqueConstraint("id", "suite_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("test_suites.id"))
    name: Mapped[str] = mapped_column(Text)


class TestRun(db.Model):  # type: ignore[name-defined]
    """A run of one Test Suite, whole or a selection, on one tree, by exactly
    one of a Tool Call, a Work Unit and a CI Build (DB 533).

    `transcript_id` is the Transcript whose labels carry it: a Tool Call's
    run carries its Tool Call's Transcript, which a key holds, and a Work
    Unit's the Transcript the labeller hands that unit's stage with.
    `retries_allowed` is how often a failing test is tried again, as the run
    shows it.
    """

    __test__ = False

    __tablename__ = "test_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transcript_id", "tool_call_id"],
            ["tool_calls.transcript_id", "tool_calls.id"],
            ondelete="CASCADE",
        ),
        # What a Test Failure's key references.
        UniqueConstraint("id", "suite_id"),
        # Read when a Transcript's labels are replaced, and when a Tool Call
        # goes, to take its runs with it.
        Index(
            "ix_test_runs_transcript_id_tool_call_id", "transcript_id", "tool_call_id"
        ),
        CheckConstraint(
            "num_nonnulls(tool_call_id, work_unit_id, ci_build_id) = 1",
            name="ck_test_runs_runner",
        ),
        CheckConstraint(
            "tests >= 0 AND retries_allowed >= 0", name="ck_test_runs_counts"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id"))
    tool_call_id: Mapped[int | None] = mapped_column(BigInteger)
    work_unit_id: Mapped[int | None] = mapped_column(ForeignKey("work_units.id"))
    ci_build_id: Mapped[int | None] = mapped_column(ForeignKey("ci_builds.id"))
    suite_id: Mapped[int] = mapped_column(ForeignKey("test_suites.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    passed: Mapped[bool] = mapped_column(Boolean)
    tests: Mapped[int] = mapped_column(Integer)
    retries_allowed: Mapped[int | None] = mapped_column(Integer)


class TestFailure(db.Model):  # type: ignore[name-defined]
    """A Test that failed at least one attempt in one Test Run; `flaky`
    whether a later attempt of the same run passed. It carries its run's
    Test Suite, which its Test is named by (DB 556)."""

    __test__ = False

    __tablename__ = "test_failures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["test_run_id", "suite_id"],
            ["test_runs.id", "test_runs.suite_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["test_id", "suite_id"], ["tests.id", "tests.suite_id"]),
        CheckConstraint("attempts >= 1", name="ck_test_failures_attempts"),
    )

    test_run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    test_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    suite_id: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer)
    flaky: Mapped[bool] = mapped_column(Boolean)


class CIBuild(db.Model):  # type: ignore[name-defined]
    """A Jenkins build a Tool Call waited on, or a pipeline such a build
    triggered that the same wait followed, by its `job` and `number`, as the
    wait gave it.

    `commit_sha` is the hash its wait's command named, by which it reaches
    the Commit it built; none where the command named none. `deployed_at`
    is when the deploy it triggered finished: the moment the wait returned,
    where its summary says the roll finished.
    """

    __tablename__ = "ci_builds"
    __table_args__ = (
        UniqueConstraint("job", "number"),
        CheckConstraint("number >= 1", name="ck_ci_builds_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job: Mapped[str] = mapped_column(Text)
    number: Mapped[int] = mapped_column(Integer)
    commit_sha: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_code: Mapped[str | None] = mapped_column(ForeignKey("build_results.code"))
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CIWait(db.Model):  # type: ignore[name-defined]
    """A wait of one Tool Call on one CI Build."""

    __tablename__ = "ci_waits"

    tool_call_id: Mapped[int] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), primary_key=True
    )
    ci_build_id: Mapped[int] = mapped_column(
        ForeignKey("ci_builds.id"), primary_key=True
    )
