from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType

import sqlalchemy as sa
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import SchemaItem


def test_identity_migration_resource_exists(identity_settings):
    """The plugin exposes its initial revision as an importable package resource."""
    (descriptor,) = IdentityPlugin(
        settings=identity_settings,
        refresh_store=InMemoryRefreshTokenStore(),
    ).migrations()

    assert descriptor.name == "identity"
    assert descriptor.versions.joinpath("0001_identity.py").is_file()


class RecordingOperations:
    def __init__(self) -> None:
        self.tables: dict[str, sa.Table] = {}
        self.events: list[tuple[str, str]] = []
        self.indexes: list[tuple[str, str, tuple[str, ...], bool]] = []

    def create_table(self, name: str, *items: SchemaItem) -> sa.Table:
        table = sa.Table(name, sa.MetaData(), *items)
        self.tables[name] = table
        self.events.append(("create_table", name))
        return table

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool = False,
    ) -> None:
        self.indexes.append((name, table_name, tuple(columns), unique))
        self.events.append(("create_index", name))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.events.append(("drop_index", f"{table_name}.{name}"))

    def drop_table(self, name: str) -> None:
        self.events.append(("drop_table", name))


def _run_revision(function_name: str, monkeypatch) -> RecordingOperations:
    operations = RecordingOperations()
    alembic = ModuleType("alembic")
    alembic.op = operations  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "alembic", alembic)
    sys.modules.pop("calango_identity.migrations.versions.0001_identity", None)
    revision = import_module("calango_identity.migrations.versions.0001_identity")

    getattr(revision, function_name)()
    sys.modules.pop("calango_identity.migrations.versions.0001_identity", None)

    return operations


def test_identity_upgrade_emits_complete_postgresql_schema(monkeypatch):
    """The shipped revision creates every current table, constraint, and index."""
    operations = _run_revision("upgrade", monkeypatch)

    assert [event for event in operations.events if event[0] == "create_table"] == [
        ("create_table", "identity_users"),
        ("create_table", "identity_roles"),
        ("create_table", "identity_permissions"),
        ("create_table", "identity_user_roles"),
        ("create_table", "identity_role_permissions"),
    ]
    assert operations.indexes == [("ix_identity_users_email", "identity_users", ("email",), True)]

    expected_columns = {
        "identity_users": {
            "id": "UUID",
            "email": "VARCHAR(320)",
            "hashed_password": "VARCHAR(1024)",
            "is_active": "BOOLEAN",
            "is_superuser": "BOOLEAN",
            "is_verified": "BOOLEAN",
            "created_at": "TIMESTAMP WITHOUT TIME ZONE",
            "updated_at": "TIMESTAMP WITHOUT TIME ZONE",
        },
        "identity_roles": {
            "name": "VARCHAR(50)",
            "id": "UUID",
            "created_at": "TIMESTAMP WITHOUT TIME ZONE",
            "updated_at": "TIMESTAMP WITHOUT TIME ZONE",
        },
        "identity_permissions": {
            "code": "VARCHAR(100)",
            "id": "UUID",
            "created_at": "TIMESTAMP WITHOUT TIME ZONE",
            "updated_at": "TIMESTAMP WITHOUT TIME ZONE",
        },
        "identity_user_roles": {"user_id": "UUID", "role_id": "UUID"},
        "identity_role_permissions": {"role_id": "UUID", "permission_id": "UUID"},
    }
    dialect = postgresql.dialect()
    for table_name, columns in expected_columns.items():
        table = operations.tables[table_name]
        assert list(table.columns.keys()) == list(columns)
        assert {
            column.name: column.type.compile(dialect=dialect) for column in table.columns
        } == columns
        assert all(not column.nullable for column in table.columns)

    assert {
        table_name: tuple(column.name for column in table.primary_key.columns)
        for table_name, table in operations.tables.items()
    } == {
        "identity_users": ("id",),
        "identity_roles": ("id",),
        "identity_permissions": ("id",),
        "identity_user_roles": ("user_id", "role_id"),
        "identity_role_permissions": ("role_id", "permission_id"),
    }

    for table_name in ("identity_users", "identity_roles", "identity_permissions"):
        table = operations.tables[table_name]
        created_at_default = table.c.created_at.server_default
        updated_at_default = table.c.updated_at.server_default
        assert isinstance(created_at_default, sa.DefaultClause)
        assert isinstance(updated_at_default, sa.DefaultClause)
        assert str(created_at_default.arg) == "now()"
        assert str(updated_at_default.arg) == "now()"

    assert {
        tuple(column.name for column in constraint.columns)
        for constraint in operations.tables["identity_roles"].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {("name",)}
    assert {
        tuple(column.name for column in constraint.columns)
        for constraint in operations.tables["identity_permissions"].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {("code",)}
    foreign_keys = {
        (foreign_key.parent.table.name, foreign_key.parent.name): (
            foreign_key.target_fullname,
            foreign_key.ondelete,
        )
        for table_name in ("identity_user_roles", "identity_role_permissions")
        for foreign_key in operations.tables[table_name].foreign_keys
    }
    assert foreign_keys == {
        ("identity_user_roles", "user_id"): ("identity_users.id", "CASCADE"),
        ("identity_user_roles", "role_id"): ("identity_roles.id", "CASCADE"),
        ("identity_role_permissions", "role_id"): ("identity_roles.id", "CASCADE"),
        ("identity_role_permissions", "permission_id"): (
            "identity_permissions.id",
            "CASCADE",
        ),
    }


def test_identity_downgrade_drops_tables_in_reverse_order(monkeypatch):
    """Rollback removes dependent association tables before entity tables."""
    operations = _run_revision("downgrade", monkeypatch)
    dropped_tables = [name for operation, name in operations.events if operation == "drop_table"]

    assert dropped_tables == [
        "identity_role_permissions",
        "identity_user_roles",
        "identity_permissions",
        "identity_roles",
        "identity_users",
    ]
