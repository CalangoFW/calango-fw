from __future__ import annotations

import heapq
import shutil
from collections.abc import Iterable
from importlib.resources import as_file
from pathlib import Path
from tempfile import TemporaryDirectory

from calango_plugin_base import PluginMigration

__all__ = [
    "MigrationConfigurationError",
    "order_migrations",
    "version_locations",
]

_materialized_resources: list[TemporaryDirectory[str]] = []


class MigrationConfigurationError(ValueError):
    """Raised when plugin migration contributions cannot form a valid graph."""


def order_migrations(
    items: Iterable[PluginMigration],
) -> tuple[PluginMigration, ...]:
    """Return plugin migrations in deterministic dependency-first order."""
    by_name: dict[str, PluginMigration] = {}
    for position, item in enumerate(items):
        if not isinstance(item, PluginMigration):
            raise MigrationConfigurationError(
                f"invalid plugin migration descriptor at position {position}"
            )
        if item.name in by_name:
            raise MigrationConfigurationError(f"duplicate plugin migration name '{item.name}'")
        by_name[item.name] = item

    for name in sorted(by_name):
        for dependency in sorted(set(by_name[name].depends_on)):
            if dependency not in by_name:
                raise MigrationConfigurationError(
                    f"plugin migration '{name}' depends on missing plugin '{dependency}'"
                )

    dependencies = {name: set(item.depends_on) for name, item in by_name.items()}
    dependents: dict[str, set[str]] = {name: set() for name in by_name}
    for name, required in dependencies.items():
        for dependency in required:
            dependents[dependency].add(name)

    ready = [name for name, required in dependencies.items() if not required]
    heapq.heapify(ready)
    ordered: list[PluginMigration] = []

    while ready:
        name = heapq.heappop(ready)
        ordered.append(by_name[name])
        for dependent in sorted(dependents[name]):
            dependencies[dependent].remove(name)
            if not dependencies[dependent]:
                heapq.heappush(ready, dependent)

    if len(ordered) != len(by_name):
        cyclic = ", ".join(sorted(name for name, required in dependencies.items() if required))
        raise MigrationConfigurationError(f"plugin migration dependency cycle detected: {cyclic}")

    return tuple(ordered)


def version_locations(items: Iterable[PluginMigration]) -> tuple[Path, ...]:
    """Return validated filesystem paths in plugin dependency order."""
    locations: list[Path] = []
    for item in order_migrations(items):
        if isinstance(item.versions, Path):
            location = item.versions
        else:
            temporary = TemporaryDirectory(prefix=f"calango-{item.name}-migrations-")
            try:
                with as_file(item.versions) as extracted:
                    location = Path(temporary.name, item.versions.name)
                    shutil.copytree(extracted, location)
            except (OSError, TypeError) as exc:
                temporary.cleanup()
                raise MigrationConfigurationError(
                    f"could not materialize versions for plugin migration '{item.name}'"
                ) from exc
            _materialized_resources.append(temporary)
        if not location.is_dir():
            raise MigrationConfigurationError(
                f"plugin migration '{item.name}' versions directory is missing: {location}"
            )
        locations.append(location)
    return tuple(locations)
