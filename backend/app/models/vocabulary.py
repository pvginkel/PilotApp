"""The labeller's reference entities (DB §2.11) and Work Unit Kind Nesting
(§2.8): the lists a label takes its value from, stored as the labeller
declares them, so that Pilot's code names none of their values (DB decisions
79.12, 79.23 and 79.40).

No revision writes a row: a collector's declaration of the vocabularies does
(`vocabulary_service`). Each value holds, beside its code and its name, its
`description`, the line that says what it is, and its `position`, its place
in its list, none once the labeller no longer declares it: such a value stays
while a row names it.
"""

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.extensions import db


def declared_value_args(table: str, *more: Any) -> tuple[Any, ...]:
    """The constraints of a table that holds the labeller's values: no two
    hold one place in the list, and each place is from 1."""
    return (
        # Checked at the commit, so a declaration that reorders a list moves
        # its values through a repeated place on the way.
        UniqueConstraint(
            "position",
            name=f"uq_{table}_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position >= 1", name=f"ck_{table}_position"),
        *more,
    )


class _DeclaredValue:
    """A value of one of the labeller's lists."""

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:
        return declared_value_args(cls.__tablename__)


class WorkUnitKind(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of Work Unit."""

    __tablename__ = "work_unit_kinds"


class WorkUnitKindNesting(db.Model):  # type: ignore[name-defined]
    """A pairing the labeller declares: units of the `inner` Work Unit Kind
    may sit in units of the `outer`."""

    __tablename__ = "work_unit_kind_nestings"

    inner_code: Mapped[str] = mapped_column(
        ForeignKey("work_unit_kinds.code"), primary_key=True
    )
    outer_code: Mapped[str] = mapped_column(
        ForeignKey("work_unit_kinds.code"), primary_key=True
    )


class UnitOutcome(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of end a Work Unit comes to."""

    __tablename__ = "unit_outcomes"


class ReworkKind(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of work done again."""

    __tablename__ = "rework_kinds"


class UnitMeasure(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of figure read for a Work Unit; `unit` what it counts."""

    __tablename__ = "unit_measures"

    unit: Mapped[str] = mapped_column(Text)


class SegmentKind(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of activity a Segment's stretch is spent on."""

    __tablename__ = "segment_kinds"


class WaitCause(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of reason a Transcript sat between two Calls."""

    __tablename__ = "wait_causes"


class CallClass(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of Call, by what it did."""

    __tablename__ = "call_classes"


class AvoidableKind(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of reason a Call need not have been made."""

    __tablename__ = "avoidable_kinds"


class CommandClass(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of command a Tool Call runs."""

    __tablename__ = "command_classes"


class BuildResult(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of end of a CI Build, in Jenkins's words."""

    __tablename__ = "build_results"


class FileClass(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of file, by what it is for; `counted` whether its Files are
    written work, which the figures count."""

    __tablename__ = "file_classes"

    counted: Mapped[bool] = mapped_column(Boolean)


class ToolEffectKind(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of change a Tool Call makes outside its Transcript."""

    __tablename__ = "tool_effect_kinds"


class Rule(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """One convention the sessions are held to; `home` the file that states
    it."""

    __tablename__ = "rules"

    home: Mapped[str] = mapped_column(Text)


class AskCategory(_DeclaredValue, db.Model):  # type: ignore[name-defined]
    """A kind of ask a Document puts."""

    __tablename__ = "ask_categories"
