from __future__ import annotations

import ast
import heapq
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import as_file
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from calango_plugin_base import PluginMigration

if TYPE_CHECKING:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

__all__ = [
    "MigrationConfigurationError",
    "order_migrations",
    "refresh_alembic_script",
    "version_locations",
]

_materialized_resources: list[TemporaryDirectory[str]] = []


class MigrationConfigurationError(ValueError):
    """Raised when plugin migration contributions cannot form a valid graph."""


@dataclass(frozen=True)
class _RevisionInfo:
    path: Path
    revision: str
    down_revisions: tuple[str, ...]


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
    """Materialize versions and encode plugin dependencies as Alembic edges."""
    ordered = order_migrations(items)
    locations: dict[str, Path] = {}
    for item in ordered:
        if isinstance(item.versions, Path):
            location = item.versions
        else:
            location = _materialize(item)
        if not location.is_dir():
            raise MigrationConfigurationError(
                f"plugin migration '{item.name}' versions directory is missing: {location}"
            )
        locations[item.name] = location

    revisions = {item.name: _read_revisions(item.name, locations[item.name]) for item in ordered}
    heads = {
        name: _revision_heads(name, plugin_revisions)
        for name, plugin_revisions in revisions.items()
    }

    for item in ordered:
        if not item.depends_on:
            continue
        roots = _revision_roots(item.name, revisions[item.name])
        required_heads = tuple(
            revision for dependency in item.depends_on for revision in heads[dependency]
        )
        if not roots or not required_heads:
            raise MigrationConfigurationError(
                f"plugin migration '{item.name}' cannot encode dependencies without revisions"
            )
        overlay = _copy_versions(item.name, locations[item.name])
        for root in roots:
            path = overlay / root.path.relative_to(locations[item.name])
            down_revisions = _maximal_revisions(
                tuple(dict.fromkeys((*root.down_revisions, *required_heads))),
                revisions,
            )
            _replace_down_revision(item.name, path, down_revisions)
        locations[item.name] = overlay
        revisions[item.name] = _read_revisions(item.name, overlay)

    return tuple(locations[item.name] for item in ordered)


def refresh_alembic_script(config: Config, script: ScriptDirectory) -> None:
    """Reload the command's ScriptDirectory after dynamic locations are configured."""
    from alembic.script import ScriptDirectory

    refreshed = ScriptDirectory.from_config(config)
    script.version_locations = refreshed.version_locations
    script.revision_map = refreshed.revision_map


def _materialize(item: PluginMigration) -> Path:
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
    return location


def _copy_versions(name: str, source: Path) -> Path:
    temporary = TemporaryDirectory(prefix=f"calango-{name}-graph-")
    destination = Path(temporary.name, source.name)
    try:
        shutil.copytree(source, destination)
    except OSError as exc:
        temporary.cleanup()
        raise MigrationConfigurationError(
            f"could not build migration graph for plugin '{name}'"
        ) from exc
    _materialized_resources.append(temporary)
    return destination


def _read_revisions(name: str, location: Path) -> tuple[_RevisionInfo, ...]:
    revisions: list[_RevisionInfo] = []
    for path in sorted(location.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
            revision = _literal_assignment(tree, "revision")
            down_revision = _literal_assignment(tree, "down_revision")
        except (OSError, SyntaxError, TypeError, ValueError) as exc:
            raise MigrationConfigurationError(
                f"could not inspect revisions for plugin migration '{name}'"
            ) from exc
        if revision is None:
            continue
        if not isinstance(revision, str) or not (
            down_revision is None
            or isinstance(down_revision, str)
            or (
                isinstance(down_revision, tuple)
                and all(isinstance(item, str) for item in down_revision)
            )
        ):
            raise MigrationConfigurationError(
                f"plugin migration '{name}' has invalid revision metadata in '{path.name}'"
            )
        if down_revision is None:
            down_revisions: tuple[str, ...] = ()
        elif isinstance(down_revision, str):
            down_revisions = (down_revision,)
        else:
            down_revisions = tuple(item for item in down_revision if isinstance(item, str))
        revisions.append(_RevisionInfo(path, revision, down_revisions))
    return tuple(revisions)


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return ast.literal_eval(node.value)
    return None


def _revision_roots(name: str, revisions: tuple[_RevisionInfo, ...]) -> tuple[_RevisionInfo, ...]:
    revision_ids = {item.revision for item in revisions}
    roots = tuple(item for item in revisions if not revision_ids.intersection(item.down_revisions))
    if revisions and not roots:
        raise MigrationConfigurationError(f"plugin migration '{name}' has no revision root")
    return roots


def _revision_heads(name: str, revisions: tuple[_RevisionInfo, ...]) -> tuple[str, ...]:
    referenced = {down_revision for item in revisions for down_revision in item.down_revisions}
    heads = tuple(sorted(item.revision for item in revisions if item.revision not in referenced))
    if revisions and not heads:
        raise MigrationConfigurationError(f"plugin migration '{name}' has no revision head")
    return heads


def _maximal_revisions(
    candidates: tuple[str, ...],
    revisions: dict[str, tuple[_RevisionInfo, ...]],
) -> tuple[str, ...]:
    parents = {
        revision.revision: revision.down_revisions
        for plugin_revisions in revisions.values()
        for revision in plugin_revisions
    }

    def ancestors(revision: str) -> set[str]:
        found: set[str] = set()
        pending = list(parents.get(revision, ()))
        while pending:
            parent = pending.pop()
            if parent in found:
                continue
            found.add(parent)
            pending.extend(parents.get(parent, ()))
        return found

    ancestors_by_candidate = {candidate: ancestors(candidate) for candidate in candidates}
    return tuple(
        candidate
        for candidate in candidates
        if not any(
            candidate in ancestors_by_candidate[other] for other in candidates if other != candidate
        )
    )


def _replace_down_revision(name: str, path: Path, revisions: tuple[str, ...]) -> None:
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        node = next(
            node
            for node in tree.body
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "down_revision"
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "down_revision"
            )
        )
        value: str | tuple[str, ...] = revisions[0] if len(revisions) == 1 else revisions
        lines = source.splitlines(keepends=True)
        lines[node.lineno - 1 : node.end_lineno] = [f"down_revision = {value!r}\n"]
        path.write_text("".join(lines))
    except (OSError, StopIteration, SyntaxError) as exc:
        raise MigrationConfigurationError(
            f"could not encode Alembic dependency for plugin migration '{name}'"
        ) from exc
