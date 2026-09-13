#!/usr/bin/env python3
"""Run resumable CWEval behavior-family trajectories on local or remote models."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sectdd.formal_orchestrator import (
    TokenCounter,
    aggregate_trajectories,
    run_trajectory,
    sha256_file,
)
from sectdd.orchestrator import configure_local_network


DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "experiments" / "paper_candidate_formal_pilot.json"
)
DEFAULT_VISIBLE = (
    PROJECT_ROOT
    / "configs"
    / "oracles"
    / "cweval_py_paper_candidate_v1_visible.json"
)
DEFAULT_HIDDEN = (
    PROJECT_ROOT
    / "configs"
    / "oracles"
    / "cweval_py_paper_candidate_v1_hidden.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-model", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--visible-projection", type=Path, default=DEFAULT_VISIBLE)
    parser.add_argument("--hidden-projection", type=Path, default=DEFAULT_HIDDEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--method", action="append", dest="methods")
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def check_server(
    api_base: str, served_model: str, provider: str, api_key: str
) -> None:
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if provider == "local"
        else urllib.request.build_opener()
    )
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with opener.open(request, timeout=10) as response:
        models = json.load(response)
    available = {item["id"] for item in models.get("data", [])}
    if served_model not in available:
        raise RuntimeError(
            f"Model {served_model!r} not available; server has {sorted(available)}"
        )


def tokenizer_identity(path: Path) -> dict:
    resolved = path.expanduser().resolve()
    files = {}
    for name in (
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "config.json",
    ):
        candidate = resolved / name
        if candidate.is_file():
            files[name] = sha256_file(candidate)
    return {"path": str(resolved), "files_sha256": files}


def model_identity(path: Path) -> dict:
    resolved = path.expanduser().resolve()
    files = {}
    for name in (
        "config.json",
        "generation_config.json",
        "model.safetensors.index.json",
    ):
        candidate = resolved / name
        if candidate.is_file():
            files[name] = sha256_file(candidate)
    return {"path": str(resolved), "files_sha256": files}


def main() -> None:
    args = parse_args()
    output = args.output.expanduser().resolve()
    output.relative_to(PROJECT_ROOT)
    if output.exists() and not args.resume:
        raise FileExistsError(
            f"{output} already exists; choose a new path to preserve provenance"
        )
    config_path = args.config.resolve()
    visible_path = args.visible_projection.resolve()
    hidden_path = args.hidden_projection.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    visible = json.loads(visible_path.read_text(encoding="utf-8"))
    hidden = json.loads(hidden_path.read_text(encoding="utf-8"))
    if visible["partition"] != "visible" or hidden["partition"] != "hidden":
        raise ValueError("Projection partition labels are invalid")
    if visible["oracle_set_id"] != hidden["oracle_set_id"]:
        raise ValueError("Visible/hidden oracle set mismatch")
    if visible["canonical_manifest_sha256"] != hidden[
        "canonical_manifest_sha256"
    ]:
        raise ValueError("Visible/hidden canonical manifest hash mismatch")
    if config["oracle_set_id"] != visible["oracle_set_id"]:
        raise ValueError("Experiment/oracle set mismatch")

    tasks = args.tasks or config.get("tasks") or list(visible["tasks"])
    if set(tasks) - set(visible["tasks"]) or set(tasks) - set(hidden["tasks"]):
        raise ValueError("Requested task absent from oracle projections")
    methods = args.methods or list(config["methods"])
    if set(methods) - set(config["methods"]):
        raise ValueError("Unknown method requested")
    legacy_policy = config.get("shared_initial_candidate_policy", {})
    legacy_reference = legacy_policy.get("reference_method")
    legacy_reused_by = set(legacy_policy.get("reused_by", []))
    shared_reference_by_method = {
        method_id: (
            config["methods"][method_id].get("shared_initial_from")
            if "shared_initial_from" in config["methods"][method_id]
            else (
                legacy_reference
                if method_id in legacy_reused_by
                else None
            )
        )
        for method_id in methods
    }
    positions = {method: index for index, method in enumerate(methods)}
    shared_policies = []
    for method_id in methods:
        method = config["methods"][method_id]
        reference = shared_reference_by_method[method_id]
        if reference is None:
            continue
        if reference not in positions or positions[reference] > positions[method_id]:
            raise ValueError(f"{method_id} requires earlier shared reference {reference}")
        reference_config = config["methods"][reference]
        for key in ("security_reminder", "upfront_tests"):
            if reference_config[key] != method[key]:
                raise ValueError(
                    f"{method_id}/{reference} initial prompt differs on {key}"
                )
        shared_policies.append(
            {"method": method_id, "reference_method": reference}
        )
    seeds = args.seeds or config.get("generation_seeds") or [11, 22, 33]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Generation seeds must be unique")
    model_registry = config.get("models", {})
    model_freeze = None
    api_key = "local-sectdd"
    if model_registry:
        if args.served_model not in model_registry:
            raise ValueError(
                f"{args.served_model!r} absent from frozen model registry"
            )
        model_record = model_registry[args.served_model]
        if model_record.get("provider", "local") != args.provider:
            raise ValueError("CLI provider does not match frozen model registry")
        tokenizer_path = args.tokenizer.expanduser().resolve()
        if args.provider == "local":
            registered_path = Path(model_record["checkpoint"]).expanduser().resolve()
            if registered_path != tokenizer_path:
                raise ValueError(
                    "Tokenizer path does not match frozen checkpoint: "
                    f"{tokenizer_path} != {registered_path}"
                )
            model_freeze = {**model_record, **model_identity(registered_path)}
        else:
            registered_path = Path(model_record["tokenizer_proxy"]).expanduser().resolve()
            if registered_path != tokenizer_path:
                raise ValueError("Tokenizer path does not match remote budget proxy")
            if not args.api_base.rstrip("/").startswith("https://api.deepseek.com"):
                raise ValueError("DeepSeek provider requires the official HTTPS API base")
            api_key = os.environ.get(args.api_key_env, "").strip()
            if not api_key:
                raise RuntimeError(f"{args.api_key_env} is required")
            os.environ["DEEPSEEK_API_KEY"] = api_key
            model_freeze = dict(model_record)
    tokenizer = TokenCounter(args.tokenizer)

    configure_local_network()
    check_server(args.api_base, args.served_model, args.provider, api_key)
    output.mkdir(parents=True, exist_ok=args.resume)
    trajectories = []
    shared_initial_generations = {}
    total = len(tasks) * len(methods) * len(seeds)
    completed = 0
    for task in tasks:
        for method_id in methods:
            method = config["methods"][method_id]
            for seed in seeds:
                trajectory_dir = (
                    output / "trajectories" / method_id / task / f"seed_{seed}"
                )
                trajectory_path = trajectory_dir / "trajectory.json"
                if args.resume and trajectory_path.is_file():
                    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
                    identity = (
                        trajectory.get("task"),
                        trajectory.get("model"),
                        trajectory.get("method"),
                        trajectory.get("generation_seed"),
                    )
                    if identity != (task, args.served_model, method_id, seed):
                        raise RuntimeError(f"Resume identity drift: {trajectory_path}")
                    if trajectory.get("oracle_set_id") != visible["oracle_set_id"]:
                        raise RuntimeError(f"Resume oracle drift: {trajectory_path}")
                    if trajectory.get("method_config") != method:
                        raise RuntimeError(f"Resume protocol drift: {trajectory_path}")
                    audit = trajectory.get("hidden_leak_audit", {})
                    if (
                        not audit.get("passed")
                        or audit.get("hidden_evaluation_count") != 1
                        or audit.get("hidden_feedback_used")
                    ):
                        raise RuntimeError(
                            f"Resume hidden isolation failure: {trajectory_path}"
                        )
                else:
                    reference = shared_reference_by_method[method_id]
                    trajectory = run_trajectory(
                        task=task,
                        generation_seed=seed,
                        method_id=method_id,
                        method=method,
                        config=config,
                        served_model=args.served_model,
                        api_base=args.api_base,
                        tokenizer=tokenizer,
                        visible_projection=visible,
                        visible_projection_path=visible_path,
                        hidden_projection_path=hidden_path,
                        trajectory_dir=trajectory_dir,
                        initial_generation=(
                            shared_initial_generations[(reference, task, seed)]
                            if reference is not None
                            else None
                        ),
                    )
                first = trajectory["rounds"][0]
                shared_initial_generations[(method_id, task, seed)] = {
                    "messages": first["messages"],
                    "request_seed": first["request_seed"],
                    "response": first["response"],
                    "usage": first["usage"],
                    "model_wall_seconds": first["model_wall_seconds"],
                }
                trajectories.append(trajectory)
                completed += 1
                print(
                    f"[{completed}/{total}] {method_id} {task} seed={seed} "
                    f"calls={len(trajectory['rounds'])} "
                    f"hidden_joint={trajectory['final_hidden']['joint_pass']}",
                    flush=True,
                )

    manifest = {
        "schema_version": 3,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pilot_only": config.get("pilot_only", True),
        "development_only": config.get("development_only", True),
        "study_phase": config.get("study_phase", "formal_pilot"),
        "formal_experiment": True,
        "formal_pilot": config.get("pilot_only", True),
        "shared_initial_candidate_policies": shared_policies,
        "model": args.served_model,
        "provider": args.provider,
        "provider_seed_supported": args.provider == "local",
        "remote_seed_policy": (
            "generation_seeds_are_request_slot_ids_not_sent_to_provider"
            if args.provider == "deepseek"
            else "seed_sent_to_local_endpoint"
        ),
        "model_freeze": model_freeze,
        "tasks": tasks,
        "methods": methods,
        "seeds": seeds,
        "config": str(config_path),
        "visible_projection": str(visible_path),
        "hidden_projection": str(hidden_path),
        "oracle_set_id": visible["oracle_set_id"],
        "canonical_oracle_manifest_sha256": visible[
            "canonical_manifest_sha256"
        ],
        "tokenizer": tokenizer_identity(args.tokenizer),
        "input_sha256": {
            "config": sha256_file(config_path),
            "visible_projection": sha256_file(visible_path),
            "hidden_projection": sha256_file(hidden_path),
        },
        "trajectory_count": len(trajectories),
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(aggregate_trajectories(trajectories), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Summary: {output / 'summary.json'}")


if __name__ == "__main__":
    main()
