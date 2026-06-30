"""
Lightweight schema migration for SQLite (dev convenience).

This module is intentionally kept around for local/dev SQLite use even
though Phase 12 adds real Alembic migrations (see /alembic) as the
production migration path for PostgreSQL. SQLAlchemy's
Base.metadata.create_all() only creates tables that don't exist yet -- it
will NOT add new columns to a table that's already on disk, and Alembic
migrations don't run automatically on `uvicorn` startup. run_migrations()
is what keeps a developer's local athena.db in sync with the models on
every `git pull` without anyone needing to remember to run `alembic
upgrade head` for day-to-day local development.

run_migrations() is idempotent and safe to call on every startup:
  1. Base.metadata.create_all()  -> creates any missing tables
     (e.g. users, refresh_tokens, password_reset_tokens, documents, ...)
  2. For each existing table, diff its real columns (PRAGMA table_info)
     against the SQLAlchemy model and ALTER TABLE ADD COLUMN for anything
     missing. No data is dropped or rewritten.
  3. Phase 12: a handful of columns that used to be globally UNIQUE
     (documents.filename, folders.name, user_preferences.key,
     voice_settings.key) are now unique per-user instead. Drop the old
     single-column unique index (if present, from a pre-Phase-12 db) and
     create the new composite (user_id, column) unique index.
  4. Phase 12: backfill any pre-existing NULL user_id rows to a
     deterministic "legacy data" account, so nothing becomes silently
     invisible after upgrading an existing single-user install straight
     to multi-user (the same backfill the Alembic migration performs for
     a Postgres deployment).
"""

from sqlalchemy import text, inspect

from backend.database.db import engine
from backend.database.models import Base, User
from backend.core.config import DATABASE_URL


def _column_ddl_type(sa_column):
    """Map a SQLAlchemy column type to a SQLite ALTER TABLE type string."""
    type_name = sa_column.type.__class__.__name__

    if type_name == "Boolean":
        return "BOOLEAN"
    if type_name == "Integer":
        return "INTEGER"
    if type_name == "DateTime":
        return "DATETIME"
    return "TEXT"


# (table, old single-column unique index name, new composite unique index
# name, [columns in the new composite index])
_LEGACY_UNIQUE_INDEX_MIGRATIONS = [
    ("documents", "ix_documents_filename", "uq_documents_user_filename", ["user_id", "filename"]),
    ("folders", "ix_folders_name", "uq_folders_user_name", ["user_id", "name"]),
    ("user_preferences", "ix_user_preferences_key", "uq_user_preferences_user_key", ["user_id", "key"]),
    ("voice_settings", "ix_voice_settings_key", "uq_voice_settings_user_key", ["user_id", "key"]),
]

# Tables whose key column forms part of a composite unique with user_id.
# For these, NULL rows that would conflict with an existing (user_id, key)
# row are deleted instead of updated -- they're duplicates of data that
# already exists for that user.
_COMPOSITE_KEY_TABLES = {
    "user_preferences": "key",
    "voice_settings": "key",
    "documents": "filename",
    "folders": "name",
}

LEGACY_USER_EMAIL = "legacy-data@athena.local"
LEGACY_USER_NAME = "Legacy Data"

_TABLES_WITH_USER_OWNERSHIP = [
    "messages", "notes", "reminders", "documents",
    "user_preferences", "conversations", "folders", "voice_settings",
    # Phase 14 additions
    "goals", "projects",
]


def _migrate_columns(conn, inspector):
    for table in Base.metadata.sorted_tables:

        if table.name not in inspector.get_table_names():
            # brand new table, already created by create_all above
            continue

        existing_columns = {
            col["name"] for col in inspector.get_columns(table.name)
        }

        for column in table.columns:

            if column.name in existing_columns:
                continue

            ddl_type = _column_ddl_type(column)

            default_clause = ""
            if column.default is not None and column.default.is_scalar:
                value = column.default.arg
                if isinstance(value, bool):
                    default_clause = f" DEFAULT {1 if value else 0}"
                elif isinstance(value, (int, float)):
                    default_clause = f" DEFAULT {value}"
                elif isinstance(value, str):
                    default_clause = f" DEFAULT '{value}'"

            conn.execute(
                text(
                    f'ALTER TABLE "{table.name}" '
                    f'ADD COLUMN "{column.name}" {ddl_type}{default_clause}'
                )
            )

            print(
                f"[migrate] added column {table.name}.{column.name} ({ddl_type})"
            )


def _migrate_legacy_unique_indexes(conn, inspector):
    for table_name, old_index_name, new_index_name, columns in _LEGACY_UNIQUE_INDEX_MIGRATIONS:

        if table_name not in inspector.get_table_names():
            continue

        existing_index_names = {idx["name"] for idx in inspector.get_indexes(table_name)}

        if old_index_name in existing_index_names:
            conn.execute(text(f'DROP INDEX "{old_index_name}"'))
            print(f"[migrate] dropped legacy single-column unique index {old_index_name}")
            existing_index_names.discard(old_index_name)

        if new_index_name not in existing_index_names:
            cols_sql = ", ".join(f'"{c}"' for c in columns)
            conn.execute(
                text(
                    f'CREATE UNIQUE INDEX "{new_index_name}" '
                    f'ON "{table_name}" ({cols_sql})'
                )
            )
            print(f"[migrate] created composite unique index {new_index_name}")


def _backfill_legacy_user(conn):
    """
    Phase 12: any row with user_id IS NULL predates multi-user support.
    Rather than leaving it permanently invisible (every API query filters
    on user_id), attach it to a single deterministic "Legacy Data" account
    so an existing single-user Athena install can `pip install -r
    requirements.txt && run` straight into Phase 12 without losing data --
    they just need to log in as that account (or reset its password via
    /auth/forgot-password) to see it.

    Fix: for tables with a composite (user_id, key) unique constraint
    (user_preferences, voice_settings, documents, folders), NULL rows
    whose key value already exists for the legacy user are deleted rather
    than updated -- they are duplicates of data that is already owned by
    that user and updating them would violate the unique constraint.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    has_legacy_rows = False
    for table_name in _TABLES_WITH_USER_OWNERSHIP:
        if table_name not in inspector.get_table_names():
            continue
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if "user_id" not in columns:
            continue
        count = conn.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}" WHERE user_id IS NULL')
        ).scalar()
        if count:
            has_legacy_rows = True
            break

    if not has_legacy_rows:
        return

    from backend.core.security import hash_password
    import secrets

    legacy_user_id = conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": LEGACY_USER_EMAIL},
    ).scalar()

    if not legacy_user_id:
        random_password_hash = hash_password(secrets.token_urlsafe(32))
        result = conn.execute(
            text(
                "INSERT INTO users (name, email, password_hash, is_active, is_verified, created_at, updated_at) "
                "VALUES (:name, :email, :password_hash, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"name": LEGACY_USER_NAME, "email": LEGACY_USER_EMAIL, "password_hash": random_password_hash},
        )
        legacy_user_id = result.lastrowid
        print(f"[migrate] created legacy-data account (user_id={legacy_user_id}) to own pre-multi-user rows")

    for table_name in _TABLES_WITH_USER_OWNERSHIP:
        if table_name not in inspector.get_table_names():
            continue
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if "user_id" not in columns:
            continue

        # For tables with a composite unique constraint on (user_id, key_col),
        # delete NULL rows that would conflict before updating the rest.
        if table_name in _COMPOSITE_KEY_TABLES:
            key_col = _COMPOSITE_KEY_TABLES[table_name]
            if key_col in columns:
                deleted = conn.execute(
                    text(
                        f'DELETE FROM "{table_name}" '
                        f'WHERE user_id IS NULL '
                        f'AND "{key_col}" IN ('
                        f'  SELECT "{key_col}" FROM "{table_name}" '
                        f'  WHERE user_id = :uid'
                        f')'
                    ),
                    {"uid": legacy_user_id},
                ).rowcount
                if deleted:
                    print(
                        f"[migrate] deleted {deleted} duplicate NULL row(s) from "
                        f"{table_name} (already owned by legacy user)"
                    )

        conn.execute(
            text(f'UPDATE "{table_name}" SET user_id = :uid WHERE user_id IS NULL'),
            {"uid": legacy_user_id},
        )

    print("[migrate] backfilled legacy rows to the legacy-data account")


def run_migrations():
    # Phase 12: this lightweight tool only knows SQLite-flavoured DDL
    # (PRAGMA-based column introspection, SQLite ALTER TABLE quirks) and is
    # meant purely as zero-config dev convenience. On PostgreSQL, Alembic
    # (`alembic upgrade head`) is the one and only migration path -- running
    # both against the same database would be a recipe for the two
    # systems fighting each other. Skip entirely (loudly) if not SQLite.
    if not DATABASE_URL.startswith("sqlite"):
        print(
            "[migrate] DATABASE_URL is not SQLite -- skipping the dev "
            "auto-migration tool. Run `alembic upgrade head` to manage "
            "this database's schema instead."
        )
        return

    # Step 1: create any tables that don't exist at all yet.
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)

    with engine.begin() as conn:
        _migrate_columns(conn, inspector)
        _migrate_legacy_unique_indexes(conn, inspector)

    # Separate transaction: needs the columns from step 2 to already exist.
    with engine.begin() as conn:
        _backfill_legacy_user(conn)


if __name__ == "__main__":
    run_migrations()
    print("Migrations complete.")