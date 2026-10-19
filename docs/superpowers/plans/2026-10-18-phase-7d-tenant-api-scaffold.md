# Phase 7D Tenant API, Scaffold and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist request writes, expose tenant and member endpoints, generate multitenant projects and tenant-scoped resources, and prove isolation end to end in a generated project.

**Architecture:** `get_db` becomes a per-request unit of work (commit on success, rollback on error), used through `DbSession`, a function-scoped dependency alias, so the commit happens before the response is sent. The plugin adds a layered tenant API (`TenantService` over `TenantRepository`). `calango new --multitenancy` generates an application role without RLS bypass; `calango generate resource --tenant-scoped` generates `TenantScoped` models whose routes require a tenant. An end-to-end test drives the generated project over HTTP.

**Tech Stack:** FastAPI `Depends(scope="function")`, SQLAlchemy 2, Typer/Jinja templates, Alembic autogenerate, uvicorn, PostgreSQL and Redis via the shared fixtures.

**Spec:** `docs/superpowers/specs/2026-10-18-phase-7-multitenancy-design.md`

**Depends on:** Phases 7A–7C.

## Global Constraints

- The unit-of-work change was approved on 2026-10-18 (generated resources previously never committed).
- Non-owner and non-member callers of member endpoints receive the identical `403 Tenant access denied`.
- Generated projects pass their own `ruff check`, `ruff format --check` and tests.
- Run the four repository gates after every task.

## File Structure

| File | Responsibility |
|---|---|
| `packages/calango-core/calango/core/database.py` | `get_db` unit of work, `DbSession` |
| `.../calango_multitenancy/schemas.py` | `TenantInput`, `TenantOutput`, `MemberInput`, `MemberOutput` |
| `.../calango_multitenancy/repositories.py` | tenant/member write and read queries |
| `.../calango_multitenancy/services.py` | `TenantService` business rules |
| `.../calango_multitenancy/router.py` | `/tenants` endpoints |
| `packages/calango-cli/calango_cli/commands/new.py` | `--multitenancy` |
| `packages/calango-cli/calango_cli/commands/generate.py` | `--tenant-scoped`, project feature detection |
| `packages/calango-cli/calango_cli/templates/...` | multitenancy plugin module, Postgres role script, compose/CI, conftest fixtures, resource templates |
| `packages/calango-cli/tests/e2e/test_generated_multitenancy.py` | acceptance |

---

### Task 1: Request unit of work

**Files:**
- Modify: `packages/calango-core/calango/core/database.py`
- Modify: `packages/calango-core/calango/__init__.py` (export `DbSession`)
- Modify: `packages/calango-cli/calango_cli/templates/resource/router.py.jinja`
- Test: `packages/calango-core/tests/test_unit_of_work.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from calango import Calango, DbSession
from calango.config import CalangoSettings, SecuritySettings
from calango.core.database import DatabaseRuntime


@pytest.fixture
async def app_and_engine() -> AsyncIterator[tuple[Calango, object]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE items (name TEXT NOT NULL)"))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def sessions() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = Calango(settings=CalangoSettings(security=SecuritySettings(SECRET_KEY="test")))
    app.database = DatabaseRuntime(app.settings, session_dependency=sessions)

    @app.post("/items/{name}")
    async def add(name: str, session: DbSession) -> dict[str, str]:
        await session.execute(text("INSERT INTO items (name) VALUES (:name)"), {"name": name})
        if name == "boom":
            raise RuntimeError("handler failed after writing")
        return {"name": name}

    @app.get("/items")
    async def items(session: DbSession) -> list[str]:
        return list((await session.execute(text("SELECT name FROM items ORDER BY name"))).scalars())

    yield app, engine
    await engine.dispose()


def test_successful_requests_commit_their_writes(app_and_engine):
    app, _ = app_and_engine
    client = TestClient(app)
    assert client.post("/items/apple").status_code == 200
    assert client.get("/items").json() == ["apple"]


def test_failing_requests_roll_back_their_writes(app_and_engine):
    app, _ = app_and_engine
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/items/boom").status_code == 500
    assert client.get("/items").json() == []
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-core/tests/test_unit_of_work.py -q` → `ImportError: cannot import name 'DbSession'`.

- [ ] **Step 3: Implement the unit of work** (replace `get_db` in `calango/core/database.py`)

```python
async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """One unit of work per request: commit when the handler succeeds, else roll back."""
    async with aclosing(request.app.database.session()) as sessions:
        async for session in sessions:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise
            await session.commit()


# Function scope: the commit runs before the response is sent, so a failed commit
# becomes an error response instead of silently lost data.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
```

(imports: `from typing import Annotated`, `from fastapi import Depends`.) Export `DbSession` from `calango/__init__.py`.

- [ ] **Step 4: Use `DbSession` in generated routers**

In `templates/resource/router.py.jinja`, replace the `get_db` import and `get_service` with:

```python
from calango import DbSession
```

```python
def get_service(db: DbSession) -> {{ resource_name }}Service:
    return {{ resource_name }}Service({{ resource_name }}Repository(db))
```

and drop the now-unused `AsyncSession` import. Run `uv run pytest packages/calango-cli -q`; update any generate-command test asserting on the old `get_db` import.

- [ ] **Step 5: Prove GREEN, run all gates, commit**

```bash
git add packages/calango-core packages/calango-cli
git commit -m "fix(core): commit each successful request as one unit of work"
```

### Task 2: Tenant and member endpoints

**Files:**
- Create: `.../calango_multitenancy/schemas.py`, `.../calango_multitenancy/services.py`, `.../calango_multitenancy/router.py`
- Modify: `.../calango_multitenancy/repositories.py`, `.../calango_multitenancy/plugin.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_services.py`, `packages/calango-plugins/calango-multitenancy/tests/integration/test_tenant_api.py`

- [ ] **Step 1: Write the failing service tests** (an in-memory fake repository; business rules only)

```python
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from calango_multitenancy.schemas import TenantInput
from calango_multitenancy.services import TenantService
from pydantic import ValidationError

from calango.exceptions import AuthorizationError, ConflictError, NotFoundError


class FakeTenantRepository:
    def __init__(self) -> None:
        self.tenants: dict[UUID, SimpleNamespace] = {}
        self.roles: dict[tuple[UUID, UUID], str] = {}
        self.users: set[UUID] = set()

    async def slug_exists(self, slug: str) -> bool:
        return any(tenant.slug == slug for tenant in self.tenants.values())

    async def create_with_owner(self, slug: str, name: str, owner_id: UUID):
        tenant = SimpleNamespace(id=uuid4(), slug=slug, name=name)
        self.tenants[tenant.id] = tenant
        self.roles[(tenant.id, owner_id)] = "owner"
        return tenant

    async def list_for_user(self, user_id: UUID):
        return [
            (self.tenants[tenant_id], role)
            for (tenant_id, member_id), role in self.roles.items()
            if member_id == user_id
        ]

    async def role_of(self, tenant_id: UUID, user_id: UUID) -> str | None:
        return self.roles.get((tenant_id, user_id))

    async def user_exists(self, user_id: UUID) -> bool:
        return user_id in self.users

    async def add_member(self, tenant_id: UUID, user_id: UUID) -> None:
        self.roles[(tenant_id, user_id)] = "member"

    async def owner_count(self, tenant_id: UUID) -> int:
        return sum(
            1 for (tid, _), role in self.roles.items() if tid == tenant_id and role == "owner"
        )

    async def remove_member(self, tenant_id: UUID, user_id: UUID) -> None:
        del self.roles[(tenant_id, user_id)]


@pytest.fixture
def service() -> TenantService:
    return TenantService(FakeTenantRepository())


async def test_creator_becomes_owner(service):
    owner = uuid4()
    created = await service.create(TenantInput(slug="acme", name="Acme"), user_id=owner)
    assert created.role == "owner"
    assert [tenant.slug for tenant in await service.list_for(owner)] == ["acme"]


async def test_duplicate_slugs_conflict(service):
    await service.create(TenantInput(slug="acme", name="Acme"), user_id=uuid4())
    with pytest.raises(ConflictError):
        await service.create(TenantInput(slug="acme", name="Other"), user_id=uuid4())


@pytest.mark.parametrize("slug", ["A", "-acme", "acme_co", str(uuid4())])
def test_invalid_or_uuid_shaped_slugs_are_rejected(slug):
    with pytest.raises(ValidationError):
        TenantInput(slug=slug, name="Acme")


async def test_only_owners_add_members_and_others_get_the_same_403(service):
    owner, member, stranger, newcomer = uuid4(), uuid4(), uuid4(), uuid4()
    service.repository.users.update({member, newcomer})
    tenant = await service.create(TenantInput(slug="acme", name="Acme"), user_id=owner)
    await service.add_member(tenant.id, member, actor_id=owner)

    for actor in (member, stranger):
        with pytest.raises(AuthorizationError, match="Tenant access denied"):
            await service.add_member(tenant.id, newcomer, actor_id=actor)


async def test_adding_twice_conflicts_and_unknown_users_are_not_found(service):
    owner, member = uuid4(), uuid4()
    service.repository.users.add(member)
    tenant = await service.create(TenantInput(slug="acme", name="Acme"), user_id=owner)
    await service.add_member(tenant.id, member, actor_id=owner)
    with pytest.raises(ConflictError):
        await service.add_member(tenant.id, member, actor_id=owner)
    with pytest.raises(NotFoundError):
        await service.add_member(tenant.id, uuid4(), actor_id=owner)


async def test_the_last_owner_cannot_be_removed(service):
    owner = uuid4()
    tenant = await service.create(TenantInput(slug="acme", name="Acme"), user_id=owner)
    with pytest.raises(ConflictError, match="owner"):
        await service.remove_member(tenant.id, owner, actor_id=owner)
```

- [ ] **Step 2: Prove RED** — `ModuleNotFoundError: calango_multitenancy.schemas`.

- [ ] **Step 3: Implement the schemas**

```python
from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator

from calango import CalangoModel


class TenantInput(CalangoModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=200)

    @field_validator("slug")
    @classmethod
    def slug_is_not_a_uuid(cls, value: str) -> str:
        try:
            UUID(value)
        except ValueError:
            return value
        raise ValueError("slug must not look like a UUID")


class TenantOutput(CalangoModel):
    id: UUID
    slug: str
    name: str
    role: str


class MemberInput(CalangoModel):
    user_id: UUID


class MemberOutput(CalangoModel):
    user_id: UUID
    role: str
```

- [ ] **Step 4: Add repository methods** (append to `TenantRepository`; writes flush, the request's unit of work commits)

```python
    async def slug_exists(self, slug: str) -> bool:
        statement = select(Tenant.id).where(Tenant.slug == slug)
        return (await self.session.execute(statement)).first() is not None

    async def create_with_owner(self, slug: str, name: str, owner_id: UUID) -> Tenant:
        tenant = Tenant(slug=slug, name=name)
        self.session.add(tenant)
        await self.session.flush()
        self.session.add(TenantMembership(tenant_id=tenant.id, user_id=owner_id, role="owner"))
        await self.session.flush()
        return tenant

    async def list_for_user(self, user_id: UUID) -> list[tuple[Tenant, str]]:
        statement = (
            select(Tenant, TenantMembership.role)
            .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
            .where(TenantMembership.user_id == user_id)
            .order_by(Tenant.slug)
        )
        return [(tenant, role) for tenant, role in (await self.session.execute(statement)).all()]

    async def role_of(self, tenant_id: UUID, user_id: UUID) -> str | None:
        statement = select(TenantMembership.role).where(
            TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def user_exists(self, user_id: UUID) -> bool:
        statement = select(User.id).where(User.id == user_id)
        return (await self.session.execute(statement)).first() is not None

    async def add_member(self, tenant_id: UUID, user_id: UUID) -> None:
        self.session.add(TenantMembership(tenant_id=tenant_id, user_id=user_id, role="member"))
        await self.session.flush()

    async def owner_count(self, tenant_id: UUID) -> int:
        statement = select(func.count()).where(
            TenantMembership.tenant_id == tenant_id, TenantMembership.role == "owner"
        )
        return (await self.session.execute(statement)).scalar_one()

    async def remove_member(self, tenant_id: UUID, user_id: UUID) -> None:
        await self.session.execute(
            delete(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id
            )
        )
```

(imports: `delete`, `func` from `sqlalchemy`; `from calango_identity import User`.)

- [ ] **Step 5: Implement `services.py`**

```python
from __future__ import annotations

from typing import Any
from uuid import UUID

from calango.exceptions import AuthorizationError, ConflictError, NotFoundError
from calango_multitenancy.schemas import MemberOutput, TenantInput, TenantOutput

_DENIED = "Tenant access denied"


class TenantService:
    """Tenant lifecycle rules; persistence goes through the repository."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    async def create(self, data: TenantInput, *, user_id: UUID) -> TenantOutput:
        if await self.repository.slug_exists(data.slug):
            raise ConflictError("Tenant slug already taken")
        tenant = await self.repository.create_with_owner(data.slug, data.name, user_id)
        return TenantOutput(id=tenant.id, slug=tenant.slug, name=tenant.name, role="owner")

    async def list_for(self, user_id: UUID) -> list[TenantOutput]:
        return [
            TenantOutput(id=tenant.id, slug=tenant.slug, name=tenant.name, role=role)
            for tenant, role in await self.repository.list_for_user(user_id)
        ]

    async def _require_owner(self, tenant_id: UUID, actor_id: UUID) -> None:
        if await self.repository.role_of(tenant_id, actor_id) != "owner":
            raise AuthorizationError(_DENIED)

    async def add_member(self, tenant_id: UUID, user_id: UUID, *, actor_id: UUID) -> MemberOutput:
        await self._require_owner(tenant_id, actor_id)
        if await self.repository.role_of(tenant_id, user_id) is not None:
            raise ConflictError("User is already a member")
        if not await self.repository.user_exists(user_id):
            raise NotFoundError("User not found")
        await self.repository.add_member(tenant_id, user_id)
        return MemberOutput(user_id=user_id, role="member")

    async def remove_member(self, tenant_id: UUID, user_id: UUID, *, actor_id: UUID) -> None:
        await self._require_owner(tenant_id, actor_id)
        role = await self.repository.role_of(tenant_id, user_id)
        if role is None:
            raise NotFoundError("Member not found")
        if role == "owner" and await self.repository.owner_count(tenant_id) == 1:
            raise ConflictError("A tenant needs at least one owner")
        await self.repository.remove_member(tenant_id, user_id)
```

- [ ] **Step 6: Implement `router.py` and include it**

```python
from __future__ import annotations

from uuid import UUID

from calango_identity import User, get_current_user
from fastapi import APIRouter, Depends, status

from calango import DbSession
from calango_multitenancy.repositories import TenantRepository
from calango_multitenancy.schemas import MemberInput, MemberOutput, TenantInput, TenantOutput
from calango_multitenancy.services import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service(session: DbSession) -> TenantService:
    return TenantService(TenantRepository(session))


@router.post("", response_model=TenantOutput, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantInput,
    user: User = Depends(get_current_user),  # noqa: B008
    service: TenantService = Depends(get_tenant_service),  # noqa: B008
) -> TenantOutput:
    return await service.create(data, user_id=user.id)


@router.get("", response_model=list[TenantOutput])
async def list_tenants(
    user: User = Depends(get_current_user),  # noqa: B008
    service: TenantService = Depends(get_tenant_service),  # noqa: B008
) -> list[TenantOutput]:
    return await service.list_for(user.id)


@router.post(
    "/{tenant_id}/members", response_model=MemberOutput, status_code=status.HTTP_201_CREATED
)
async def add_member(
    tenant_id: UUID,
    data: MemberInput,
    user: User = Depends(get_current_user),  # noqa: B008
    service: TenantService = Depends(get_tenant_service),  # noqa: B008
) -> MemberOutput:
    return await service.add_member(tenant_id, data.user_id, actor_id=user.id)


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    tenant_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    service: TenantService = Depends(get_tenant_service),  # noqa: B008
) -> None:
    await service.remove_member(tenant_id, user_id, actor_id=user.id)
```

In `MultitenancyPlugin.register`, after the guard: `app.include_router(router)`.

- [ ] **Step 7: Write the HTTP integration tests** (`tests/integration/test_tenant_api.py`, reusing the 7B `tenant_world` fixture: Alice owns `alice-co`, Bob owns `bob-co`)

```python
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


async def test_create_and_list_tenants(tenant_world):
    client, alice = tenant_world.client, tenant_world.alice
    created = await client.post(
        "/tenants", json={"slug": "alice-two", "name": "Alice Two"}, headers=alice.headers
    )
    assert created.status_code == 201, created.text
    listed = await client.get("/tenants", headers=alice.headers)
    assert {(item["slug"], item["role"]) for item in listed.json()} == {
        ("alice-co", "owner"),
        ("alice-two", "owner"),
    }


async def test_duplicate_and_uuid_shaped_slugs(tenant_world):
    client, alice = tenant_world.client, tenant_world.alice
    duplicate = await client.post(
        "/tenants", json={"slug": "bob-co", "name": "Copy"}, headers=alice.headers
    )
    assert duplicate.status_code == 409
    uuid_slug = await client.post(
        "/tenants", json={"slug": str(uuid4()), "name": "Bad"}, headers=alice.headers
    )
    assert uuid_slug.status_code == 422


async def test_member_management_and_access(tenant_world):
    client, alice, bob = tenant_world.client, tenant_world.alice, tenant_world.bob
    bob_id = (await client.get("/users/me", headers=bob.headers)).json()["id"]
    path = f"/tenants/{alice.tenant_id}/members"

    denied = await client.post(path, json={"user_id": bob_id}, headers=bob.headers)
    assert denied.status_code == 403
    added = await client.post(path, json={"user_id": bob_id}, headers=alice.headers)
    assert added.status_code == 201
    again = await client.post(path, json={"user_id": bob_id}, headers=alice.headers)
    assert again.status_code == 409
    as_bob = {**bob.headers, "X-Tenant-ID": alice.slug}
    assert (await client.get("/notes", headers=as_bob)).status_code == 200

    removed = await client.delete(f"{path}/{bob_id}", headers=alice.headers)
    assert removed.status_code == 204
    assert (await client.get("/notes", headers=as_bob)).status_code == 403

    alice_id = (await client.get("/users/me", headers=alice.headers)).json()["id"]
    last_owner = await client.delete(f"{path}/{alice_id}", headers=alice.headers)
    assert last_owner.status_code == 409
```

- [ ] **Step 8: Prove GREEN, run all gates, commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): add tenant and member endpoints"
```

### Task 3: `calango new --multitenancy`

**Files:**
- Modify: `packages/calango-cli/calango_cli/commands/new.py`
- Create: `packages/calango-cli/calango_cli/templates/app/plugins/multitenancy.py.jinja`
- Create: `packages/calango-cli/calango_cli/templates/docker/postgres/01-app-role.sql.jinja`
- Modify templates: `app/main.py.jinja`, `pyproject.toml.jinja`, `compose.yml.jinja`, `github/workflows/ci.yml.jinja`, `tests/conftest.py.jinja`
- Test: `packages/calango-cli/tests/test_new_command.py`

- [ ] **Step 1: Write the failing tests** (append; `_generate` exists from Phase 6)

```python
def test_new_with_multitenancy_implies_identity_and_wires_both(tmp_path):
    project = _generate(tmp_path, "--multitenancy")
    main = (project / "app" / "main.py").read_text()
    assert main.index("identity_plugin()") < main.index("multitenancy_plugin()")
    assert "MultitenancyPlugin" in (project / "app" / "plugins" / "multitenancy.py").read_text()
    assert "calango-multitenancy" in (project / "pyproject.toml").read_text()


def test_new_with_multitenancy_runs_the_app_as_a_role_without_rls_bypass(tmp_path):
    project = _generate(tmp_path, "--multitenancy")
    script = (project / "docker" / "postgres" / "01-app-role.sql").read_text()
    assert "NOSUPERUSER" in script and "NOBYPASSRLS" in script
    assert 'CREATE DATABASE "my-api_dev" OWNER "my-api"' in script
    compose = (project / "compose.yml").read_text()
    assert "POSTGRES_USER: postgres" in compose
    assert "docker-entrypoint-initdb.d" in compose
    ci = (project / ".github" / "workflows" / "ci.yml").read_text()
    assert "01-app-role.sql" in ci


def test_new_multitenancy_conftest_offers_auth_and_tenant_headers(tmp_path):
    conftest = (_generate(tmp_path, "--multitenancy") / "tests" / "conftest.py").read_text()
    assert "async def auth_headers" in conftest
    assert "async def tenant_headers" in conftest
    assert "IDENTITY__RATE_LIMIT_LOGIN_PER_MINUTE" in conftest
```

Also extend the parametrized `test_new_generates_valid_python` and `test_new_project_passes_its_own_ruff_gates` with `("--multitenancy",)` (id `multitenancy`).

- [ ] **Step 2: Prove RED** — `No such option: --multitenancy`.

- [ ] **Step 3: Add the option**

In `new.py`: a `multitenancy: bool = typer.Option(False, "--multitenancy", help="Enable PostgreSQL RLS multitenancy (implies --identity)")` option; a wizard `ask_confirm("Enable multitenancy (PostgreSQL row-level security)?", default=False)` after the Identity question; `identity = identity or multitenancy` before building `context`; add `"multitenancy": multitenancy` to the context and to the `print_info` fields; and

```python
_MULTITENANCY_TEMPLATE_FILES = [
    ("app/plugins/multitenancy.py.jinja", "app/plugins/multitenancy.py"),
    ("docker/postgres/01-app-role.sql.jinja", "docker/postgres/01-app-role.sql"),
]
```

appended by `_template_files` when `context["multitenancy"]`.

- [ ] **Step 4: Write the new templates**

`app/plugins/multitenancy.py.jinja`:

```python
"""Multitenancy configuration: PostgreSQL row-level security per tenant."""

from calango_multitenancy import MultitenancyPlugin


def multitenancy_plugin() -> MultitenancyPlugin:
    """Build multitenancy; requests select a tenant with the X-Tenant-ID header."""
    return MultitenancyPlugin()
```

`docker/postgres/01-app-role.sql.jinja` — plain statements, one per line ending in `;` (it runs once, as the image superuser, on a fresh volume or CI service; `CREATE DATABASE` cannot run inside a transaction, so tooling executes the statements one by one):

```sql
-- The application connects as this role. It owns its databases but cannot
-- bypass row-level security, so tenant isolation always applies.
CREATE ROLE "{{ project_name }}" LOGIN PASSWORD '{{ project_name }}' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE "{{ project_name }}_dev" OWNER "{{ project_name }}";
CREATE DATABASE "{{ project_name }}_test" OWNER "{{ project_name }}";
```

- [ ] **Step 5: Update the shared templates**

`app/main.py.jinja` — add after the identity lines:

```jinja
{%- if multitenancy %}
from app.plugins.multitenancy import multitenancy_plugin
{%- endif %}
```

in the import block (after `identity_plugin`) and `app.include_plugin(multitenancy_plugin())` after `app.include_plugin(identity_plugin())`.

`pyproject.toml.jinja` — after the identity dependency: `{%- if multitenancy %}\n    "calango-multitenancy>=0.1.0",\n{%- endif %}`.

`compose.yml.jinja` — in the `postgres` service, when multitenancy, use the superuser only for initialization and mount the script:

```jinja
    environment:
{%- if multitenancy %}
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
{%- else %}
      POSTGRES_DB: {{ project_name }}_dev
      POSTGRES_USER: {{ project_name }}
      POSTGRES_PASSWORD: {{ project_name }}
{%- endif %}
    volumes:
      - postgres_data:/var/lib/postgresql/data
{%- if multitenancy %}
      - ./docker/postgres:/docker-entrypoint-initdb.d:ro
{%- endif %}
```

and its healthcheck user becomes `postgres` when multitenancy (`pg_isready -U {{ "postgres" if multitenancy else project_name }}`).

`github/workflows/ci.yml.jinja` — in `test-integration`, when multitenancy, the service uses `POSTGRES_USER: postgres` / `POSTGRES_PASSWORD: postgres`, and a step before the tests creates the role and databases:

```jinja
{%- if multitenancy %}
      - name: Create the application role
        run: psql "postgresql://postgres:postgres@localhost:5432/postgres" -f docker/postgres/01-app-role.sql
{%- endif %}
```

`DATABASE__URL` stays `postgresql+asyncpg://{{ project_name }}:{{ project_name }}@localhost:5432/{{ project_name }}_test`.

`tests/conftest.py.jinja` — with identity, raise login limits for test runs (before importing the app) and add the header fixtures:

```jinja
{%- if identity %}
# Test suites log in many times; production limits would answer 429.
os.environ.setdefault("IDENTITY__RATE_LIMIT_LOGIN_PER_MINUTE", "10000")
os.environ.setdefault("IDENTITY__RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL", "10000")
{%- endif %}
```

placed right after `_ensure_identity_signing_keys()`, and at the end of the file:

```jinja
{%- if identity %}


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Bearer headers for a freshly registered user."""
    email = f"member-{uuid4().hex}@example.com"
    password = "TestPassword123!"
    registered = await client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
{%- endif %}
{%- if multitenancy %}


@pytest_asyncio.fixture
async def tenant_headers(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, str]:
    """``auth_headers`` plus ``X-Tenant-ID`` for a tenant the user owns."""
    created = await client.post(
        "/tenants",
        json={"slug": f"t-{uuid4().hex[:12]}", "name": "Test tenant"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    return {**auth_headers, "X-Tenant-ID": created.json()["id"]}
{%- endif %}
```

(with `from uuid import uuid4` added to the imports when identity.)

- [ ] **Step 6: Prove GREEN (including the generated ruff gates for `--multitenancy`), commit**

```bash
git add packages/calango-cli
git commit -m "feat(cli): generate multitenant applications with a non-bypassing role"
```

### Task 4: `calango generate resource --tenant-scoped`

**Files:**
- Modify: `packages/calango-cli/calango_cli/commands/generate.py`
- Modify templates: `resource/model.py.jinja`, `resource/router.py.jinja`, `resource/test_router.py.jinja`
- Test: `packages/calango-cli/tests/test_generate_command.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def _project(tmp_path, *new_options: str):
    result = runner.invoke(app, ["new", "shop", "--path", str(tmp_path), *new_options])
    assert result.exit_code == 0, result.output
    return tmp_path / "shop"


def test_tenant_scoped_resource_uses_the_mixin_and_requires_a_tenant(tmp_path):
    project = _project(tmp_path, "--multitenancy")
    result = runner.invoke(
        app,
        ["generate", "resource", "Notes.Note", "--tenant-scoped", "--path", str(project)],
    )
    assert result.exit_code == 0, result.output
    model = (project / "app/contexts/notes/models/note.py").read_text()
    assert "class Note(TenantScoped, Base):" in model
    router = (project / "app/routers/note.py").read_text()
    assert "Depends(require_tenant)" in router
    test_router = (project / "tests/integration/notes/test_note_router.py").read_text()
    assert "tenant_headers" in test_router


def test_tenant_scoped_requires_multitenancy_in_the_project(tmp_path):
    project = _project(tmp_path)
    result = runner.invoke(
        app,
        ["generate", "resource", "Notes.Note", "--tenant-scoped", "--path", str(project)],
    )
    assert result.exit_code == 1
    assert "multitenancy" in result.output


def test_identity_projects_generate_authenticated_router_tests(tmp_path):
    project = _project(tmp_path, "--identity")
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(project)])
    test_router = (project / "tests/integration/shop/test_order_router.py").read_text()
    assert "auth_headers" in test_router
```

(The paths come from `_render_resource_templates`: `app/routers/<resource>.py` and `tests/integration/<context>/test_<resource>_router.py`.)

- [ ] **Step 2: Prove RED** — `No such option: --tenant-scoped`.

- [ ] **Step 3: Detect project features and add the flag**

In `generate.py`:

```python
def _project_dependencies(project_dir: Path) -> set[str]:
    """Distribution names the project depends on, from its pyproject.toml."""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return set()
    data = tomllib.loads(pyproject.read_text())
    names: set[str] = set()
    for requirement in data.get("project", {}).get("dependencies", []):
        names.add(re.split(r"[\s<>=!~\[;]", requirement, maxsplit=1)[0].lower())
    return names
```

Add `tenant_scoped: bool = typer.Option(False, "--tenant-scoped", help="Isolate rows per tenant (requires multitenancy)")`. At the top of `resource(...)`, before the name prompt, record whether the wizard runs:

```python
    name_was_prompted = name is None
```

After validating the project directory:

```python
    dependencies = _project_dependencies(project_dir)
    has_identity = "calango-identity" in dependencies
    has_multitenancy = "calango-multitenancy" in dependencies
    if name_was_prompted and has_multitenancy:
        tenant_scoped = ask_confirm("Is this resource tenant-scoped?", default=True)
    if tenant_scoped and not has_multitenancy:
        print_error(
            "--tenant-scoped needs the multitenancy plugin.",
            hint="Create the project with calango new --multitenancy.",
        )
        raise typer.Exit(1)
```

(`name_was_prompted` is `True` when the wizard asked for the name.) Add `"tenant_scoped": tenant_scoped`, `"identity": has_identity` to `template_context`.

- [ ] **Step 4: Update the resource templates**

`model.py.jinja`:

```jinja
from calango.db import Base
{%- if tenant_scoped %}
from calango_multitenancy import TenantScoped
{%- endif %}


class {{ resource_name }}({% if tenant_scoped %}TenantScoped, {% endif %}Base):
```

`router.py.jinja` — when tenant-scoped, every route requires a tenant:

```jinja
{%- if tenant_scoped %}
from calango_multitenancy import require_tenant
{%- endif %}
```

```jinja
router = APIRouter(
    prefix="/{{ resource_plural }}",
    tags=["{{ resource_plural }}"],
{%- if tenant_scoped %}
    dependencies=[Depends(require_tenant)],
{%- endif %}
)
```

`test_router.py.jinja` — replace the whole template so every request carries the right headers:

Signatures are always rendered one parameter per line with a trailing comma, so
`ruff format` keeps them stable whatever the resource name length:

```jinja
{%- set headers_fixture = "tenant_headers" if tenant_scoped else ("auth_headers" if identity else "") -%}
{%- set headers_arg = ", headers=" ~ headers_fixture if headers_fixture else "" -%}
{%- macro signature(name) -%}
    async def {{ name }}(
        self,
        client: AsyncClient,
{%- if headers_fixture %}
        {{ headers_fixture }}: dict[str, str],
{%- endif %}
    ):
{%- endmacro -%}
import uuid

from httpx import AsyncClient


class Test{{ resource_name }}Router:
    """Integration tests for {{ resource_name }} router.

    Security cases are generated automatically — implement them.
    """

    {{ signature("test_list_" ~ resource_plural ~ "_returns_200") }}
        """GET /{{ resource_plural }} returns 200."""
        response = await client.get("/{{ resource_plural }}/"{{ headers_arg }})
        assert response.status_code == 200

    {{ signature("test_create_" ~ resource_snake ~ "_returns_201") }}
        """POST /{{ resource_plural }} with valid data returns 201."""
        # TODO: implement with valid payload
        ...

    {{ signature("test_get_nonexistent_" ~ resource_snake ~ "_returns_404") }}
        """GET /{{ resource_plural }}/{nonexistent_id} returns 404."""
        response = await client.get(f"/{{ resource_plural }}/{uuid.uuid4()}"{{ headers_arg }})
        assert response.status_code == 404

    # --- Security cases (OWASP API Security) ---

    async def test_create_{{ resource_snake }}_requires_authentication(
        self,
        client: AsyncClient,
    ):
        """POST /{{ resource_plural }} without token returns 401. (API2: Broken Authentication)"""
        # TODO: implement when identity plugin is active
        ...

    {{ signature("test_" ~ resource_snake ~ "_mass_assignment_is_blocked") }}
        """Fields not in {{ resource_name }}Update schema should be ignored. (API3: Mass Assignment)"""
        # TODO: implement
        ...
```

Add to `test_generate_command.py` (with `import subprocess` and `import sys`):

```python
@pytest.mark.parametrize(
    ("new_options", "resource_options"),
    [(("--identity",), ()), (("--multitenancy",), ("--tenant-scoped",))],
    ids=["identity", "multitenancy"],
)
def test_generated_resources_pass_the_project_ruff_gates(tmp_path, new_options, resource_options):
    project = _project(tmp_path, *new_options)
    result = runner.invoke(
        app,
        ["generate", "resource", "Notes.Note", *resource_options, "--path", str(project)],
    )
    assert result.exit_code == 0, result.output
    for arguments in (["check", "."], ["format", "--check", "."]):
        completed = subprocess.run(
            [sys.executable, "-m", "ruff", *arguments],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
```

This test may also expose lint the resource templates already had (for example the model template importing `Mapped`/`mapped_column` used only in comments); fix those templates in this task so the generated project is clean.

- [ ] **Step 5: Prove GREEN (CLI suite and generated ruff gates), commit**

```bash
git add packages/calango-cli
git commit -m "feat(cli): generate tenant-scoped resources"
```

### Task 5: Generated multitenant project, end to end

**Files:**
- Create: `packages/calango-cli/tests/e2e/conftest.py`
- Modify: `packages/calango-cli/tests/e2e/test_generated_identity.py`
- Create: `packages/calango-cli/tests/e2e/test_generated_multitenancy.py`

- [ ] **Step 1: Move the end-to-end helpers into a fixture**

Several workspace packages own a `tests` package, so end-to-end modules share
helpers through a fixture, never by importing each other. Create
`tests/e2e/conftest.py`:

```python
"""Helpers for end-to-end tests that drive generated projects in subprocesses."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_HOST_SETTING_PREFIXES = ("CALANGO_", "DATABASE__", "REDIS__", "SECURITY__", "IDENTITY__", "PYTEST_")
_LEGACY_HOST_SETTINGS = {"APP_NAME", "VERSION", "ENV", "DEBUG"}


class GeneratedProject:
    """Run commands and the ASGI server of a generated project, isolated from the host."""

    @staticmethod
    def signing_keys() -> tuple[str, str]:
        """A fresh RS256 key pair, PEMs escaped for a double-quoted .env value."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return private.decode().replace("\n", "\\n"), public.decode().replace("\n", "\\n")

    @staticmethod
    def env() -> dict[str, str]:
        """The host environment minus settings that would override the project's .env."""
        return {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(_HOST_SETTING_PREFIXES) and name not in _LEGACY_HOST_SETTINGS
        }

    @classmethod
    def _run_sync(cls, project: Path, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=project,
            env=cls.env(),
            capture_output=True,
            text=True,
            check=False,
        )

    @classmethod
    async def run(cls, project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return await asyncio.to_thread(cls._run_sync, project, arguments)

    @classmethod
    @asynccontextmanager
    async def serve(cls, project: Path) -> AsyncIterator[httpx.AsyncClient]:
        """Start ``app.main:app`` with uvicorn and yield a client once it answers."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=project,
            env=cls.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                deadline = time.monotonic() + 30
                while True:
                    if server.poll() is not None:
                        output = server.stdout.read() if server.stdout else ""
                        pytest.fail(f"generated app exited early:\n{output}")
                    try:
                        await client.get("/")
                        break
                    except httpx.TransportError:
                        if time.monotonic() > deadline:
                            pytest.fail("generated app did not start serving within 30 seconds")
                        await asyncio.sleep(0.2)
                yield client
        finally:
            server.terminate()
            server.wait(timeout=10)
            if server.stdout:
                server.stdout.close()


@pytest.fixture
def generated() -> type[GeneratedProject]:
    return GeneratedProject
```

Refactor `test_generated_identity.py` to use it: delete its `_escaped_pem`,
`_signing_keys`, `_project_env`, `_run_sync`, `_run`, `_free_port` and
`_wait_until_serving` helpers and the `subprocess.Popen` block; take a
`generated` fixture argument in both tests; call `generated.signing_keys()` in
`_scaffold` (pass `generated` to it), `await generated.run(project, ...)` for
Alembic and pytest, and `async with generated.serve(project) as client:` around
the HTTP flow. Run `uv run pytest packages/calango-cli/tests/e2e -q` → both
existing tests still PASS. Commit:

```bash
git add packages/calango-cli/tests/e2e
git commit -m "test(cli): share end-to-end project helpers through a fixture"
```

- [ ] **Step 2: Write the acceptance test**

`tests/e2e/test_generated_multitenancy.py`:

```python
"""A generated multitenant project: role, scaffold, migrate, serve, isolate."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from typer.testing import CliRunner

from calango_cli.main import app as cli

pytestmark = pytest.mark.integration
PASSWORD = "SecurePassword123!"
PROJECT = "tenantapp"
ROUTER_REGISTRATION = (
    "\nfrom app.routers.note import router as note_router  # noqa: E402\n\n"
    "app.include_router(note_router)\n"
)


async def _provision_role(admin_url: str, project: Path) -> str:
    """Run the generated role script as the superuser; return the app-role URL."""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for cleanup in (
                'DROP DATABASE IF EXISTS "tenantapp_dev"',
                'DROP DATABASE IF EXISTS "tenantapp_test"',
                'DROP ROLE IF EXISTS "tenantapp"',
            ):
                await connection.execute(text(cleanup))
            script = (project / "docker/postgres/01-app-role.sql").read_text()
            for statement in script.split(";"):
                if statement.strip():
                    await connection.execute(text(statement))
    finally:
        await engine.dispose()
    url = make_url(admin_url).set(username=PROJECT, password=PROJECT, database=f"{PROJECT}_dev")
    return url.render_as_string(hide_password=False)


async def _member(client, name: str) -> dict[str, str]:
    email = f"{name}@example.com"
    registered = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    tenant = await client.post("/tenants", json={"slug": f"{name}-co", "name": name}, headers=auth)
    assert tenant.status_code == 201, tenant.text
    return {**auth, "X-Tenant-ID": tenant.json()["id"]}


async def test_generated_multitenant_project_isolates_tenants(
    tmp_path, postgres_url, redis_url, generated
):
    created = CliRunner().invoke(cli, ["new", PROJECT, "--path", str(tmp_path), "--multitenancy"])
    assert created.exit_code == 0, created.output
    project = tmp_path / PROJECT
    database_url = await _provision_role(postgres_url, project)
    private_key, public_key = generated.signing_keys()
    (project / ".env").write_text(
        "CALANGO_ENV=development\n"
        "SECURITY__SECRET_KEY=multitenancy-e2e-secret\n"
        f"DATABASE__URL={database_url}\n"
        f"REDIS__URL={redis_url}\n"
        f'IDENTITY__PRIVATE_KEY="{private_key}"\n'
        f'IDENTITY__PUBLIC_KEY="{public_key}"\n'
        f"IDENTITY__REDIS_URL={redis_url}\n"
    )
    resource = CliRunner().invoke(
        cli, ["generate", "resource", "Notes.Note", "--tenant-scoped", "--path", str(project)]
    )
    assert resource.exit_code == 0, resource.output
    # Registering a generated router in app/main.py is the documented manual step.
    main = project / "app" / "main.py"
    main.write_text(main.read_text() + ROUTER_REGISTRATION)

    revision = await generated.run(
        project, "-m", "alembic", "revision", "--autogenerate", "-m", "notes"
    )
    assert revision.returncode == 0, revision.stdout + revision.stderr
    (revision_file,) = (project / "alembic" / "versions").glob("*notes*.py")
    assert "op.enable_tenant_isolation('notes')" in revision_file.read_text()
    migrated = await generated.run(project, "-m", "alembic", "upgrade", "heads")
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr

    async with generated.serve(project) as client:
        alice = await _member(client, "alice")
        bob = await _member(client, "bob")
        for headers, count in ((alice, 2), (bob, 1)):
            for _ in range(count):
                note = await client.post("/notes/", json={}, headers=headers)
                assert note.status_code == 201, note.text

        assert len((await client.get("/notes/", headers=alice)).json()) == 2
        assert len((await client.get("/notes/", headers=bob)).json()) == 1

        crossing = {"Authorization": bob["Authorization"], "X-Tenant-ID": alice["X-Tenant-ID"]}
        assert (await client.get("/notes/", headers=crossing)).status_code == 403
        no_tenant = {"Authorization": alice["Authorization"]}
        assert (await client.get("/notes/", headers=no_tenant)).status_code == 400

    suite = await generated.run(
        project,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=--import-mode=importlib",
        "tests",
    )
    assert suite.returncode == 0, suite.stdout + suite.stderr
```

- [ ] **Step 3: Run it and make it GREEN**

Run: `uv run pytest packages/calango-cli/tests/e2e/test_generated_multitenancy.py -q`
Expected after Tasks 1–4: PASS. Any failure is a product defect: add a focused
regression test in the owning package (core, plugin or CLI) before fixing it,
then rerun this test.

- [ ] **Step 4: Commit**

```bash
git add packages/calango-cli/tests/e2e
git commit -m "test(multitenancy): verify a generated multitenant project end to end"
```

### Task 6: Documentation and final gates

**Files:**
- Modify: `packages/calango-plugins/calango-multitenancy/README.md`, `.../calango_multitenancy/plugin.py` (`context_md`)
- Modify: `packages/calango-core/README.md`, `packages/calango-cli/README.md`, `README.md`, `ROADMAP.md`, `CLAUDE.md`

- [ ] **Step 1: Document verified behavior**

- Plugin README: installation after Identity; `X-Tenant-ID` (UUID or slug) and custom `TenantResolver`; `get_current_tenant`/`require_tenant`; `TenantScoped` with an example model; `op.enable_tenant_isolation`/autogenerate and the manual recipe for converting an existing table (add nullable `tenant_id`, backfill per tenant inside `tenant_scope`, set `NOT NULL`, enable isolation); the application-role requirement and the three startup checks; the endpoints table; `tenant_scope` for jobs; the uniform `403`; WebSockets carry no tenant.
- `context_md()`: patterns for `TenantScoped`, `require_tenant`, `X-Tenant-ID`, and "never connect as a superuser".
- Core README: `DbSession` unit of work, `BadRequestError`, ordered dependency guards.
- CLI README: `calango new --multitenancy`, `calango generate resource ... --tenant-scoped`.
- Root README, ROADMAP (Phase 7 ✅ with the verified test count), CLAUDE.md (implemented list; next = Phase 8 payments; the `@tenantable` sample becomes `class Order(TenantScoped, Base)`).

- [ ] **Step 2: Run every gate**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/
uv run pytest -q
uv run pytest -m integration -q
uv run calango check:security
```

Expected: all exit 0; the documented test count equals `uv run pytest --co -q | tail -1`.

- [ ] **Step 3: Commit**

```bash
git add README.md ROADMAP.md CLAUDE.md packages
git commit -m "docs: close verified Phase 7 multitenancy"
```
