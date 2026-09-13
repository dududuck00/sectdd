"""Load oracle manifests with auditable single-inheritance support."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rebase_task_paths(task_data: dict, old_base: Path, new_base: Path) -> dict:
    task_data = copy.deepcopy(task_data)
    for partition in ("visible", "hidden"):
        absolute = (old_base / task_data["oracles"][partition]).resolve()
        task_data["oracles"][partition] = os.path.relpath(absolute, new_base)
    for subject in task_data["subjects"]:
        absolute = (old_base / subject["source"]).resolve()
        subject["source"] = os.path.relpath(absolute, new_base)
    return task_data


def load_oracle_manifest(path: Path) -> tuple[dict, dict[str, str]]:
    """Return a resolved manifest and every source manifest hash.

    A child manifest may declare ``"extends": "../base/manifest.json"``.
    Inherited task paths are rebased to the child directory, so all existing
    validators can continue resolving paths relative to the requested manifest.
    """

    path = path.expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = {str(path): sha256_file(path)}
    extends = raw.get("extends")
    if not extends:
        return raw, sources

    base_path = (path.parent / extends).resolve()
    base, base_sources = load_oracle_manifest(base_path)
    sources = {**base_sources, **sources}
    inherited_tasks = {
        task: _rebase_task_paths(data, base_path.parent, path.parent)
        for task, data in base["tasks"].items()
    }
    for task, overrides in raw.get("task_overrides", {}).items():
        if task not in inherited_tasks:
            raise ValueError(f"{path}: cannot override unknown task {task}")
        if set(overrides) - {"oracles"}:
            raise ValueError(
                f"{path}: task override for {task} may only replace oracles"
            )
        inherited_tasks[task]["oracles"].update(
            copy.deepcopy(overrides.get("oracles", {}))
        )
    child_tasks = copy.deepcopy(raw["tasks"])
    overlap = set(inherited_tasks) & set(child_tasks)
    if overlap:
        raise ValueError(
            f"{path}: inherited tasks may not be overridden: {sorted(overlap)}"
        )
    resolved = copy.deepcopy(base)
    for key, value in raw.items():
        if key not in {"extends", "task_overrides", "tasks"}:
            resolved[key] = copy.deepcopy(value)
    resolved["tasks"] = {**inherited_tasks, **child_tasks}
    return resolved, sources


def manifest_dependency_digest(sources: dict[str, str]) -> str:
    payload = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
