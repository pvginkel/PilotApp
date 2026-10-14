"""
Empty String to NULL Normalization

This module implements SQLAlchemy event handlers that automatically convert
empty strings (including whitespace-only strings) to NULL values before
records are written to the database.

This ensures:
1. Data consistency - prevents both NULL and empty string for "no value"
2. Data integrity - required fields with empty strings are caught by NOT NULL constraints
3. Query simplification - only need to check IS NULL instead of multiple conditions
"""

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.sql.sqltypes import String, Text

from app.extensions import db


def normalize_empty_strings(mapper: Any, connection: Any, target: Any) -> None:
    """
    Normalize empty strings to NULL for all String/Text columns.

    This function is called before insert and update operations via SQLAlchemy events.
    It converts empty strings and whitespace-only strings to None (NULL in database).

    Args:
        mapper: SQLAlchemy mapper for the model class
        connection: Database connection
        target: The model instance being saved
    """
    # Get all columns for this model
    columns = inspect(mapper.class_).columns

    # Process each column
    for column in columns:
        # Only process String and Text columns
        if isinstance(column.type, String | Text):
            # Get current value
            value = getattr(target, column.name, None)

            # Check if it's a string and is empty/whitespace-only
            if isinstance(value, str) and value.strip() == "":
                # Set to None (NULL in database)
                setattr(target, column.name, None)


# Register event listeners for all models that inherit from db.Model
@event.listens_for(db.Model, "before_insert", propagate=True)
def normalize_empty_strings_on_insert(mapper: Any, connection: Any, target: Any) -> None:
    """Handle empty string normalization before insert operations."""
    normalize_empty_strings(mapper, connection, target)


@event.listens_for(db.Model, "before_update", propagate=True)
def normalize_empty_strings_on_update(mapper: Any, connection: Any, target: Any) -> None:
    """Handle empty string normalization before update operations."""
    normalize_empty_strings(mapper, connection, target)
