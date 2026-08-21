from __future__ import annotations

import ast
import heapq
import re
import shutil
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.resources import as_file
from importlib.resources.abc import Traversable
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import TYPE_CHECKING

from calango_plugin_base import PluginMigration

if TYPE_CHECKING:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

__all__ = [
    "MigrationConfigurationError",
    "MigrationResources",
    "order_migrations",
    "own_version_locations",
    "refresh_alembic_script",
    "release_version_locations",
    "validate_migration_descriptors",
    "version_locations",
]

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_RESOURCE_OWNER_KEY = "calango.migration_resources"


class MigrationConfigurationError(ValueError):
    """Raised when plugin migration contributions cannot form a valid graph."""


class MigrationResources(AbstractContextManager["MigrationResources"]):
    """Own temporary plugin migration copies for one bounded operation."""

    def __init__(self) -> None:
        self._temporaries: list[tuple[str, TemporaryDirectory[str]]] = []
        self._closed = False

    def __enter__(self) -> MigrationResources:
        if self._closed:
            raise MigrationConfigurationError(
                "migration resource context is closed. Create a new context and retry."
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            self.close()
        except MigrationConfigurationError:
            if exc_type is None:
                raise
        return False

    def create_temporary_directory(self, name: str) -> Path:
        """Create and own one temporary directory for a validated plugin."""
        if self._closed:
            raise MigrationConfigurationError(
                "migration resource context is closed. Create a new context and retry."
            )
        try:
            temporary = TemporaryDirectory(prefix="calango-plugin-migrations-")
        except Exception:
            raise _plugin_error(name, "could not create temporary migration storage") from None
        self._temporaries.append((name, temporary))
        return Path(temporary.name)

    def release(self, directory: Path) -> None:
        """Release one owned directory early after a failed materialization."""
        for index, (name, temporary) in enumerate(self._temporaries):
            if Path(temporary.name) != directory:
                continue
            self._temporaries.pop(index)
            try:
                temporary.cleanup()
            except Exception:
                raise _plugin_error(name, "could not clean temporary migration storage") from None
            return

    def close(self) -> None:
        """Remove every owned resource; repeated close calls are safe."""
        if self._closed:
            return
        self._closed = True
        cleanup_name: str | None = None
        while self._temporaries:
            name, temporary = self._temporaries.pop()
            try:
                temporary.cleanup()
            except Exception:
                cleanup_name = cleanup_name or name
        if cleanup_name is not None:
            raise _plugin_error(
                cleanup_name,
                "could not clean temporary migration storage",
            ) from None


@dataclass(frozen=True)
class _RevisionInfo:
    path: Path
    revision: str
    down_revisions: tuple[str, ...]


def order_migrations(
    items: Iterable[PluginMigration],
) -> tuple[PluginMigration, ...]:
    """Return plugin migrations in deterministic dependency-first order."""
    descriptors = validate_migration_descriptors(items)
    by_name: dict[str, PluginMigration] = {}
    for item in descriptors:
        if item.name in by_name:
            raise MigrationConfigurationError(
                f"duplicate plugin migration name '{item.name}'. "
                "Remove the duplicate plugin contribution, then retry."
            )
        by_name[item.name] = item

    for name in sorted(by_name):
        for dependency in sorted(set(by_name[name].depends_on)):
            if dependency not in by_name:
                raise MigrationConfigurationError(
                    f"plugin migration '{name}' depends on missing plugin '{dependency}'. "
                    f"Install or enable plugin '{dependency}', then retry."
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
        raise MigrationConfigurationError(
            f"plugin migration dependency cycle detected: {cyclic}. "
            "Update or reinstall the named plugins, then retry."
        )

    for item in descriptors:
        _validate_versions(item)
    return tuple(ordered)


def validate_migration_descriptors(
    items: Iterable[PluginMigration],
) -> tuple[PluginMigration, ...]:
    """Validate descriptor fields without accessing contributed resources."""
    return _descriptor_tuple(items)


def version_locations(
    items: Iterable[PluginMigration],
    *,
    resources: MigrationResources,
) -> tuple[Path, ...]:
    """Materialize versions and encode plugin dependencies as Alembic edges."""
    ordered = order_migrations(items)
    locations: dict[str, Path] = {}
    for item in ordered:
        locations[item.name] = _materialize(item, resources)

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
            raise _plugin_error(item.name, "cannot encode dependencies without revisions")
        overlay = _copy_versions(item.name, locations[item.name], resources)
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


def own_version_locations(
    config: Config,
    items: Iterable[PluginMigration],
) -> tuple[Path, ...]:
    """Attach one migration resource owner to an Alembic Config for its full run."""
    release_version_locations(config)
    resources = MigrationResources()
    try:
        locations = version_locations(items, resources=resources)
    except Exception:
        resources.close()
        raise
    config.attributes[_RESOURCE_OWNER_KEY] = resources
    return locations


def release_version_locations(config: Config) -> None:
    """Release plugin migration resources owned by an Alembic Config."""
    owner = config.attributes.pop(_RESOURCE_OWNER_KEY, None)
    if isinstance(owner, MigrationResources):
        owner.close()


def refresh_alembic_script(config: Config, script: ScriptDirectory) -> None:
    """Reload the command's ScriptDirectory after dynamic locations are configured."""
    from alembic.script import ScriptDirectory

    refreshed = ScriptDirectory.from_config(config)
    script.version_locations = refreshed.version_locations
    script.revision_map = refreshed.revision_map


def _descriptor_tuple(items: Iterable[PluginMigration]) -> tuple[PluginMigration, ...]:
    try:
        descriptors = tuple(items)
    except Exception:
        raise MigrationConfigurationError(
            "could not enumerate plugin migration descriptors. "
            "Update or reinstall the configured plugins, then retry."
        ) from None
    for position, item in enumerate(descriptors):
        if type(item) is not PluginMigration:
            raise MigrationConfigurationError(
                f"invalid plugin migration descriptor at position {position}. "
                "Update or reinstall the contributing plugin, then retry."
            )
        if type(item.name) is not str or _IDENTIFIER.fullmatch(item.name) is None:
            raise MigrationConfigurationError(
                "invalid plugin migration name. Use a nonempty identifier containing only "
                "letters, numbers, underscores, or hyphens."
            )
        if not isinstance(item.depends_on, tuple):
            raise _plugin_error(item.name, "depends_on must be a tuple")
        seen: set[str] = set()
        for dependency in item.depends_on:
            if type(dependency) is not str or _IDENTIFIER.fullmatch(dependency) is None:
                raise _plugin_error(item.name, "has an invalid dependency identifier")
            if dependency in seen:
                raise _plugin_error(item.name, "has a duplicate dependency")
            if dependency == item.name:
                raise _plugin_error(item.name, "cannot depend on itself")
            seen.add(dependency)
        try:
            valid_versions = isinstance(item.versions, Traversable)
        except Exception:
            valid_versions = False
        if not valid_versions:
            raise _plugin_error(item.name, "has an invalid versions resource")
    return descriptors


def _validate_versions(item: PluginMigration) -> None:
    try:
        if not item.versions.is_dir():
            raise _plugin_error(item.name, "versions directory is unavailable or unreadable")
        children = tuple(item.versions.iterdir())
        for child in children:
            if child.is_file() and child.name.endswith(".py"):
                child.read_bytes()
    except MigrationConfigurationError:
        raise
    except Exception:
        raise _plugin_error(
            item.name,
            "versions directory is unavailable or unreadable",
        ) from None


def _materialize(item: PluginMigration, resources: MigrationResources) -> Path:
    temporary = resources.create_temporary_directory(item.name)
    location = temporary / "versions"
    try:
        with as_file(item.versions) as extracted:
            shutil.copytree(extracted, location)
    except Exception:
        try:
            resources.release(temporary)
        except MigrationConfigurationError:
            pass
        raise _plugin_error(item.name, "versions could not be materialized") from None
    return location


def _copy_versions(
    name: str,
    source: Path,
    resources: MigrationResources,
) -> Path:
    temporary = resources.create_temporary_directory(name)
    destination = temporary / "versions"
    try:
        shutil.copytree(source, destination)
    except Exception:
        try:
            resources.release(temporary)
        except MigrationConfigurationError:
            pass
        raise _plugin_error(name, "migration dependency overlay could not be built") from None
    return destination


def _plugin_error(name: str, problem: str) -> MigrationConfigurationError:
    return MigrationConfigurationError(
        f"plugin migration '{name}' {problem}. Update or reinstall plugin '{name}', then retry."
    )


def _read_revisions(name: str, location: Path) -> tuple[_RevisionInfo, ...]:
    revisions: list[_RevisionInfo] = []
    try:
        paths = sorted(location.glob("*.py"))
    except Exception:
        raise _plugin_error(name, "revisions could not be inspected") from None
    for path in paths:
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
            revision = _literal_assignment(tree, "revision")
            down_revision = _literal_assignment(tree, "down_revision")
        except (OSError, SyntaxError, TypeError, ValueError):
            raise _plugin_error(name, "revisions could not be inspected") from None
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
            raise _plugin_error(name, "has invalid revision metadata")
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
        raise _plugin_error(name, "has no revision root")
    return roots


def _revision_heads(name: str, revisions: tuple[_RevisionInfo, ...]) -> tuple[str, ...]:
    referenced = {down_revision for item in revisions for down_revision in item.down_revisions}
    heads = tuple(sorted(item.revision for item in revisions if item.revision not in referenced))
    if revisions and not heads:
        raise _plugin_error(name, "has no revision head")
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
    except (OSError, StopIteration, SyntaxError, TypeError, ValueError):
        raise _plugin_error(name, "Alembic dependency could not be encoded") from None
