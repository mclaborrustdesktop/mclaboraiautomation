"""Small SQL helpers shared by search and duplicate detection.

They produce SQL that is correct and index-friendly on the three databases the app runs on:

* SQL Server (staging / production copy of McLabor): the database uses a case-insensitive collation (the
  SQL Server default), so plain ``=`` and ``LIKE`` already ignore case. Wrapping a column in LOWER() there
  would stop SQL Server using an index, and LOWER() is not allowed on ``ntext`` note columns at all.
* PostgreSQL (the cloud database, deploy/railway): ``=`` and ``LIKE`` are case-sensitive, so equality lowers
  both sides and 'contains' uses ILIKE (an index on lower(column) or a trigram index serves these).
* SQLite (demo): ``=`` is case-sensitive, so equality lowers both sides. ``LIKE`` is already
  case-insensitive for ASCII.

Every value is passed as a bound parameter; nothing here builds SQL from user text.
"""
from __future__ import annotations

from sqlalchemy import func

from .config import settings

_PHONE_PUNCTUATION = ("(", ")", "-", ".", " ", "+")


def like_escape(text: str) -> str:
    """Escape LIKE wildcards in user text (``%``, ``_`` and SQL Server's ``[``). Use with escape='\\\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")


def _like(column, pattern: str):
    if settings.is_postgres:
        return column.ilike(pattern, escape="\\")
    return column.like(pattern, escape="\\")


def ci_eq(column, value):
    """Case-insensitive equality."""
    if settings.is_sql_server:
        return column == value
    return func.lower(column) == str(value).lower()


def contains(column, text: str):
    """Case-insensitive 'contains'."""
    return _like(column, f"%{like_escape(text)}%")


def starts_with(column, text: str):
    """Case-insensitive 'starts with' (can use an index on SQL Server)."""
    return _like(column, f"{like_escape(text)}%")


def word_start(column, text: str):
    """True when the text starts the value or starts a word inside it."""
    t = like_escape(text)
    return _like(column, f"{t}%") | _like(column, f"% {t}%")


def ci_order(column):
    """Case-insensitive ordering key."""
    return column if settings.is_sql_server else func.lower(column)


def digits_only(column):
    """The column with phone punctuation removed, for digit-by-digit phone matching."""
    expr = column
    for ch in _PHONE_PUNCTUATION:
        expr = func.replace(expr, ch, "")
    return expr


def text_length(column):
    return func.len(column) if settings.is_sql_server else func.length(column)
