"""Saved View, View Star, Dimension Favourite, Quick Filter and Custom Ratio
(DB §2.10): what the analysis dashboard stores, the views, quick filters and
ratios everyone shares and a person's favourites (DB decisions 79 and 80).

A stored expression is one value, kept as the query engine writes it and
read whole (DB §7.7): a Saved View's `state`, a Quick Filter's `condition`
and a Custom Ratio's two measures. A key one names that is gone is dropped
where it is read, never here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import FAVOURITE_MENU, ORIGIN, FavouriteMenu, Origin

SYSTEM = "origin_code <> 'person'"
"""A row's `system`, carried from its Origin: whether that Origin is
managed, Pilot's own or the workflow's."""


class SavedView(db.Model):  # type: ignore[name-defined]
    """A view of the dashboard kept under a name, for everyone: a system
    view, Pilot's own or the workflow's, or one a person saved.

    A name stands once among the system views and once among the others
    (DB 602), the unique index on `system` and the name. A system view has
    a `key`, unique within its Origin, by which a release or a load matches
    it; one a person saved has none (DB 603). `state` is the view whole in
    its normal form, without the address's `#dash/`.
    """

    __tablename__ = "saved_views"
    __table_args__ = (
        CheckConstraint(
            "(origin_code = 'person') = (key IS NULL)", name="ck_saved_views_key"
        ),
        UniqueConstraint("origin_code", "key"),
        UniqueConstraint("system", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin_code: Mapped[Origin] = mapped_column(ORIGIN)
    system: Mapped[bool] = mapped_column(Boolean, Computed(SYSTEM, persisted=True))
    key: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ViewStar(db.Model):  # type: ignore[name-defined]
    """One User's star on one Saved View, a system view's and a saved one's
    alike, listed in the order of `starred_at`. It goes with its view (DB
    604)."""

    __tablename__ = "view_stars"
    __table_args__ = (
        # Read when a view goes, to take its stars with it.
        Index("ix_view_stars_saved_view_id", "saved_view_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    saved_view_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_views.id", ondelete="CASCADE"), primary_key=True
    )
    starred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DimensionFavourite(db.Model):  # type: ignore[name-defined]
    """One User's marking of one dimension as a favourite in By's list or
    Color's. A dimension is no row: `dimension` is the catalogue's key."""

    __tablename__ = "dimension_favourites"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    menu_code: Mapped[FavouriteMenu] = mapped_column(FAVOURITE_MENU, primary_key=True)
    dimension: Mapped[str] = mapped_column(Text, primary_key=True)


class QuickFilter(db.Model):  # type: ignore[name-defined]
    """A filter kept under a label, for everyone, that a view turns on by
    its `code` with one click. `condition` is the chip it applies as a
    view's state writes it, and `marks` whether it marks what the chip keeps
    rather than filters to it, so the condition carries no mark of its own;
    `amount_figure` the catalogue's key of the figure shown beside its
    count. The ones Pilot ships are written once by revision 0054 and
    removed as any other."""

    __tablename__ = "quick_filters"
    __table_args__ = (
        CheckConstraint("condition NOT LIKE '~%'", name="ck_quick_filters_condition"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(Text)
    marks: Mapped[bool] = mapped_column(Boolean)
    amount_figure: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomRatio(db.Model):  # type: ignore[name-defined]
    """A ratio of two measures kept under a name, for everyone: loaded with
    the workflow's views, or made by a person; never Pilot's own, whose
    ratios are the catalogue's (DB 600).

    A name stands once among the loaded and once among a person's (DB 602),
    as a Saved View's does. `key` is what a view's state names it by after
    `r:`, written there as it stands, so it is a word of lower-case letters,
    digits and underscores. `numerator` and `denominator` are measures as a
    view's state writes them.
    """

    __tablename__ = "custom_ratios"
    __table_args__ = (
        CheckConstraint("origin_code <> 'pilot'", name="ck_custom_ratios_origin"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*$'", name="ck_custom_ratios_key"),
        UniqueConstraint("system", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin_code: Mapped[Origin] = mapped_column(ORIGIN)
    system: Mapped[bool] = mapped_column(Boolean, Computed(SYSTEM, persisted=True))
    key: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    numerator: Mapped[str] = mapped_column(Text)
    denominator: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
