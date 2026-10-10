"""Dev-only additive schema sync for the SQLite preview DB.

`scripts/dev_preview_seed.py` builds `dev_preview.db` with
`Base.metadata.create_all`, and `scripts/dev_preview.sh` only calls it when the
file is *absent*. So every model change made after the file was created leaves
the preview DB behind the models, and the failure is confusing: the ORM SELECTs
a column the table doesn't have, so *every* query on that table dies with
`OperationalError: no such column`, not just the feature that added it.

That is exactly what happened with `0005_login_lockout`: signup broke with
`no such column: users.failed_login_attempts`, because `get_by_email` selects
the full column list.

This script closes the gap by diffing `Base.metadata` against the file and
applying the drift that SQLite can apply in place:

  * missing tables   -> create_all (creates only what's absent)
  * missing columns  -> ALTER TABLE ADD COLUMN
  * missing indexes  -> CREATE INDEX

Anything else — a dropped/renamed column, a changed type, a NOT NULL column with
no server_default (SQLite rejects `ADD COLUMN NOT NULL` without a default) — is
reported and the script exits non-zero telling you to re-seed, because a
destructive rewrite of a dev DB should be your call, not a launcher's.

Prod is unaffected: it runs the real Alembic migrations against Postgres. This
script refuses to touch anything that isn't a SQLite URL.

Run:
    DATABASE_URL="sqlite+aiosqlite:///./dev_preview.db" \
        ./venv/bin/python scripts/dev_preview_sync.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev_preview.db")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.dialects import sqlite as sqlite_dialect  # noqa: E402
from sqlalchemy.schema import CreateColumn, CreateIndex  # noqa: E402

import app.models  # noqa: F401,E402  — registers every mapper on Base.metadata
from app.core.config import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402

DIALECT = sqlite_dialect.dialect()


def _sqlite_path(url: str) -> Path:
    """Extract the file path from a sqlite URL (`sqlite+aiosqlite:///./x.db`)."""
    _, _, tail = url.partition(":///")
    return Path(tail or ":memory:")


def _reflect(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Return `{table: {column: declared_type}}` and the file's index names.

    The declared type comes back from PRAGMA exactly as it was written into the
    CREATE TABLE — and it was written by this same SQLAlchemy type compiler
    during `create_all` — so comparing it against `type.compile()` is a reliable
    drift check here, not the usual cross-dialect guesswork.
    """
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    columns = {
        name: {row[1]: (row[2] or "").upper() for row in conn.execute(f"PRAGMA table_info({name})")}
        for name in tables
    }
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL"
        )
    }
    return columns, indexes


def _plan(existing: dict[str, dict[str, str]], indexes: set[str]) -> dict:
    """Diff the models against the file. Additive drift is fixable in place."""
    plan: dict = {"tables": [], "columns": [], "indexes": [], "blocked": [], "stale": []}

    for name, table in Base.metadata.tables.items():
        if name not in existing:
            plan["tables"].append(name)
            continue  # create_all builds the table with its columns and indexes

        have = existing[name]
        for col in table.columns:
            if col.name not in have:
                if not col.nullable and col.server_default is None:
                    plan["blocked"].append(
                        f"{name}.{col.name} is NOT NULL with no server_default — "
                        "SQLite cannot ADD COLUMN without one"
                    )
                else:
                    plan["columns"].append((name, col))
                continue
            want_type = col.type.compile(DIALECT).upper()
            if have[col.name] and have[col.name] != want_type:
                plan["blocked"].append(
                    f"{name}.{col.name} is {have[col.name]} but the model says "
                    f"{want_type} — SQLite cannot change a column type in place"
                )

        for ix in table.indexes:
            if ix.name not in indexes:
                plan["indexes"].append(ix)

        for orphan in sorted(set(have) - {c.name for c in table.columns}):
            plan["stale"].append(f"{name}.{orphan} exists in the DB but not in the models")

    for orphan in sorted(set(existing) - set(Base.metadata.tables) - {"sqlite_sequence"}):
        plan["stale"].append(f"table {orphan} exists in the DB but not in the models")

    return plan


def _apply(plan: dict, conn: sqlite3.Connection, path: Path) -> None:
    """Run the additive DDL. Tables first, then columns, then indexes."""
    if plan["tables"]:
        engine = create_engine(f"sqlite:///{path}")
        try:
            Base.metadata.create_all(engine, checkfirst=True)
        finally:
            engine.dispose()
        for name in plan["tables"]:
            print(f"  + table   {name}")

    for table_name, col in plan["columns"]:
        spec = CreateColumn(col).compile(dialect=DIALECT).string
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {spec}")
        print(f"  + column  {table_name}.{col.name}  ({spec})")

    for ix in plan["indexes"]:
        conn.execute(CreateIndex(ix).compile(dialect=DIALECT).string)
        print(f"  + index   {ix.name}  on {ix.table.name}")

    conn.commit()


def main() -> int:
    url = get_settings().DATABASE_URL
    if not url.startswith("sqlite"):
        print(
            "dev_preview_sync: refusing to run — DATABASE_URL is not SQLite.\n"
            f"  got: {url.split('://')[0]}://…\n"
            "  This script only patches the local dev preview DB. Postgres is "
            "migrated with `alembic upgrade head`.",
            file=sys.stderr,
        )
        return 2

    path = _sqlite_path(url)
    if not path.exists():
        print(f"dev_preview_sync: {path} does not exist — run scripts/dev_preview_seed.py first.")
        return 1

    conn = sqlite3.connect(path)
    try:
        existing, indexes = _reflect(conn)
        plan = _plan(existing, indexes)

        for note in plan["stale"]:
            print(f"  ! {note}")

        if plan["blocked"]:
            print(f"\ndev_preview_sync: {path} has drift SQLite cannot patch in place:")
            for note in plan["blocked"]:
                print(f"  - {note}")
            print(
                "\nRe-seed to rebuild it from the current models (this deletes the "
                "preview data):\n"
                '  DATABASE_URL="sqlite+aiosqlite:///./dev_preview.db" '
                "./venv/bin/python scripts/dev_preview_seed.py",
                file=sys.stderr,
            )
            return 1

        pending = len(plan["tables"]) + len(plan["columns"]) + len(plan["indexes"])
        if not pending:
            print(f"dev_preview_sync: {path} matches the models — nothing to do.")
            return 0

        print(f"dev_preview_sync: patching {path} ({pending} change(s)) —")
        _apply(plan, conn, path)
        print("dev_preview_sync: done.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
