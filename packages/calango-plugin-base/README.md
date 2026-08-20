# calango-plugin-base

`calango-plugin-base` defines the runtime-checkable `PluginBase` protocol used by
Calango plugins.

## Installation

```bash
uv add calango-plugin-base
```

Your application also needs `calango-core`, which provides `Calango` and its
`include_plugin()` integration point.

## Plugin contract

A conforming plugin supplies these attributes and methods:

| Member | Purpose |
|---|---|
| `name: str` | Stable plugin name. |
| `version: str` | Plugin version. |
| `requires: list[str]` | Required package dependencies. |
| `register(app: FastAPI) -> None` | Register routers, middleware, handlers, or lifecycle hooks. |
| `migrations() -> list[str]` | Return Alembic migration module paths contributed by the plugin. |
| `settings() -> type[BaseSettings]` | Return the plugin's Pydantic settings class. |
| `test_fixtures() -> list` | Return pytest fixtures made available to consuming projects. |
| `context_md() -> str` | Return the plugin's `CLAUDE.md` guidance block. |

`Calango.include_plugin()` checks this protocol at runtime and raises `TypeError`
when a required member is missing.

## Minimal plugin

```python
from fastapi import APIRouter, FastAPI
from pydantic_settings import BaseSettings

router = APIRouter()


@router.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello"}


class GreetingSettings(BaseSettings):
    GREETING: str = "hello"


class GreetingPlugin:
    name = "greeting"
    version = "0.1.0"
    requires: list[str] = []

    def register(self, app: FastAPI) -> None:
        app.include_router(router)

    def migrations(self) -> list[str]:
        return []

    def settings(self) -> type[BaseSettings]:
        return GreetingSettings

    def test_fixtures(self) -> list:
        return []

    def context_md(self) -> str:
        return "## Plugin: Greeting\nProvides `GET /hello`."
```

Register it when creating the application:

```python
from calango import Calango

app = Calango()
app.include_plugin(GreetingPlugin())
```
