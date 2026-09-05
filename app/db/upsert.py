"""Dialect-portable upsert helpers (SQLite / PostgreSQL), shared by the
backfill CLI (Phase 0-A/B) and the EDDN collector (Phase 1) so both use
the same idempotency mechanism rather than duplicating the dialect
dispatch.
"""
from __future__ import annotations

from sqlalchemy.orm import Session


def dialect_insert_for(session: Session):
    """Public for callers that need a custom on_conflict_do_update this
    module doesn't provide a canned helper for (e.g. an incrementing
    counter) — see app/collectors/eddn.py's station_activity bump."""
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise NotImplementedError(f"unsupported database dialect for upsert: {dialect}")
    return dialect_insert


_dialect_insert = dialect_insert_for  # internal alias used below


def upsert_ignore(session: Session, model, rows: list[dict], index_elements: list[str]) -> None:
    """Insert rows, silently skipping any that violate the unique
    constraint on `index_elements` (re-running over the same input must
    not duplicate rows)."""
    if not rows:
        return
    dialect_insert = _dialect_insert(session)
    stmt = dialect_insert(model).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
    session.execute(stmt)


def upsert_if_newer(
    session: Session,
    model,
    rows: list[dict],
    index_elements: list[str],
    timestamp_column: str,
) -> None:
    """Insert rows, and on a conflict with `index_elements`, overwrite the
    existing row only if the incoming row's `timestamp_column` is strictly
    newer. Delivery order isn't guaranteed (EDDN messages, out-of-order
    backfill), so a plain "last write wins" upsert could let a stale
    observation clobber a fresher one — this is why market_latest needs
    this instead of upsert_ignore."""
    if not rows:
        return
    dialect_insert = _dialect_insert(session)
    stmt = dialect_insert(model).values(rows)
    update_columns = {col for col in rows[0] if col not in index_elements}
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={col: getattr(stmt.excluded, col) for col in update_columns},
        where=(getattr(stmt.excluded, timestamp_column) > getattr(model, timestamp_column)),
    )
    session.execute(stmt)
    # This UPDATE happens at the Core level, bypassing the ORM unit-of-work —
    # any already-loaded instance of an updated row would otherwise keep
    # showing its pre-upsert attribute values for the rest of the session
    # (expire_on_commit=False is the project-wide default, so a later
    # commit() won't refresh it either).
    session.expire_all()


def upsert_preserve_columns(
    session: Session,
    model,
    rows: list[dict],
    index_elements: list[str],
    preserve_columns: set[str],
) -> None:
    """Insert rows, and on a conflict with `index_elements`, update every
    column except those in `preserve_columns` — those keep their existing
    stored value (e.g. a `first_observed_at` that should never regress).
    A first-time insert still writes `preserve_columns` from `rows`
    normally; only the conflict/update branch excludes them."""
    if not rows:
        return
    dialect_insert = _dialect_insert(session)
    stmt = dialect_insert(model).values(rows)
    update_columns = {col for col in rows[0] if col not in index_elements and col not in preserve_columns}
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={col: getattr(stmt.excluded, col) for col in update_columns},
    )
    session.execute(stmt)
    session.expire_all()  # see upsert_if_newer's comment on why this is needed
