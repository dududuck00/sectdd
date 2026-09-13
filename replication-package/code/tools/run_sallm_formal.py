#!/usr/bin/env python3
"""Run partitioned SALLM B0/B3/B4/M/B6 trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sectdd.orchestrator import configure_local_network
from sectdd.sallm_formal_orchestrator import (
    TokenCounter,
    aggregate_trajectories,
    run_trajectory,
    sha256_file,
)


DEFAULT_CONFIG = ROOT / "configs/experiments/sallm_partitioned_smoke_v1.json"
DEFAULT_VISIBLE = (
    ROOT / "configs/oracles/sallm_partitioned_oracle_v3_visible.json"
)
DEFAULT_HIDDEN = (
    ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"
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
        payload = json.load(response)
    available = {item["id"] for item in payload.get("data", [])}
    if served_model not in available:
        raise RuntimeError(
            f"{served_model!r} is unavailable; server exposes {sorted(available)}"
        )


def file_identity(root: Path) -> dict:
    files = {}
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "model.safetensors.index.json",
    ):
        path = root / name
        if path.is_file():
            files[name] = sha256_file(path)
    return {"path": str(root), "files_sha256": files}


def validate_method_order(methods: list[str], config: dict) -> None:
    positions = {method: index for index, method in enumerate(methods)}
    for method in methods:
        reference = config["methods"][method].get("shared_initial_from")
        if reference is None:
            continue
        if reference not in positions:
            raise ValueError(f"{method} requires shared reference {reference}")
        if positions[reference] > positions[method]:
            raise ValueError(f"{reference} must run before {method}")
        reference_config = config["methods"][reference]
        current = config["methods"][method]
        for key in ("security_reminder", "upfront_tests"):
            if reference_config[key] != current[key]:
                raise ValueError(
                    f"{method}/{reference} initial prompt differs on {key}"
                )


def main() -> None:
    args = parse_args()
    output = args.output.expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists() and not args.resume:
        raise FileExistsError(
            f"{output} already exists; select a new output to preserve provenance"
        )
    config_path = args.config.resolve()
    visible_path = args.visible_projection.resolve()
    hidden_path = args.hidden_projection.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    visible = json.loads(visible_path.read_text(encoding="utf-8"))
    hidden_header = json.loads(hidden_path.read_text(encoding="utf-8"))
    if visible["partition"] != "visible":
        raise ValueError("Visible projection label is invalid")
    if hidden_header["partition"] != "hidden":
        raise ValueError("Hidden projection label is invalid")
    if visible["oracle_set_id"] != hidden_header["oracle_set_id"]:
        raise ValueError("Visible/hidden oracle set mismatch")
    if visible["canonical_manifest_sha256"] != hidden_header[
        "canonical_manifest_sha256"
    ]:
        raise ValueError("Visible/hidden canonical manifest mismatch")
    if config["oracle_set_id"] != visible["oracle_set_id"]:
        raise ValueError("Config/oracle set mismatch")

    tasks = args.tasks or config["tasks"]
    if set(tasks) - set(visible["tasks"]) or set(tasks) - set(
        hidden_header["tasks"]
    ):
        raise ValueError("Requested task is absent from a projection")
    methods = args.methods or list(config["methods"])
    if set(methods) - set(config["methods"]):
        raise ValueError("Unknown method")
    validate_method_order(methods, config)
    seeds = args.seeds or config["generation_seeds"]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Generation seeds must be unique")

    registry = config.get("models", {})
    if args.served_model not in registry:
        raise ValueError("Served model is absent from the frozen registry")
    model_record = registry[args.served_model]
    registered_provider = model_record.get("provider", "local")
    if registered_provider != args.provider:
        raise ValueError("CLI provider does not match the frozen model registry")
    tokenizer_path = args.tokenizer.expanduser().resolve()
    if args.provider == "local":
        checkpoint = Path(model_record["checkpoint"]).expanduser().resolve()
        if checkpoint != tokenizer_path:
            raise ValueError("Tokenizer must match the registered checkpoint")
        api_key = "local-sectdd"
    else:
        expected_tokenizer = Path(
            model_record["tokenizer_proxy"]
        ).expanduser().resolve()
        if expected_tokenizer != tokenizer_path:
            raise ValueError("Tokenizer must match the registered budget proxy")
        api_key = os.environ.get(args.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"{args.api_key_env} is required")
        if not args.api_base.rstrip("/").startswith("https://api.deepseek.com"):
            raise ValueError("DeepSeek provider requires the official HTTPS API base")
        os.environ["DEEPSEEK_API_KEY"] = api_key
    tokenizer = TokenCounter(tokenizer_path)
    configure_local_network()
    check_server(args.api_base, args.served_model, args.provider, api_key)

    output.mkdir(parents=True, exist_ok=args.resume)
    trajectories = []
    shared = {}
    total = len(tasks) * len(methods) * len(seeds)
    completed = 0
    for task in tasks:
        for method_id in methods:
            method = config["methods"][method_id]
            for seed in seeds:
                reference = method.get("shared_initial_from")
                trajectory_dir = (
                    output / "trajectories" / method_id / task / f"seed_{seed}"
                )
                trajectory_path = trajectory_dir / "trajectory.json"
                if args.resume and trajectory_path.is_file():
                    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
                    identity = (
                        trajectory.get("task"), trajectory.get("model"),
                        trajectory.get("method"), trajectory.get("generation_seed"),
                    )
                    if identity != (task, args.served_model, method_id, seed):
                        raise RuntimeError(f"Resume identity drift: {trajectory_path}")
                    if trajectory.get("oracle_set_id") != visible["oracle_set_id"]:
                        raise RuntimeError(f"Resume oracle drift: {trajectory_path}")
                    if trajectory.get("method_config") != method:
                        raise RuntimeError(f"Resume protocol drift: {trajectory_path}")
                    audit = trajectory.get("hidden_leak_audit", {})
                    if (not audit.get("passed") or
                            audit.get("hidden_evaluation_count") != 1 or
                            audit.get("hidden_feedback_used")):
                        raise RuntimeError(f"Resume hidden isolation failure: {trajectory_path}")
                    for round_value in trajectory.get("rounds", []):
                        candidate = ROOT / round_value["candidate"]["path"]
                        if (not candidate.is_file() or
                                sha256_file(candidate) != round_value["candidate"]["sha256"]):
                            raise RuntimeError(f"Resume candidate drift: {candidate}")
                else:
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
                            shared[(reference, task, seed)]
                            if reference is not None else None
                        ),
                    )
                first = trajectory["rounds"][0]
                shared[(method_id, task, seed)] = {
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

    policies = [
        {
            "method": method,
            "reference_method": config["methods"][method].get(
                "shared_initial_from"
            ),
        }
        for method in methods
        if config["methods"][method].get("shared_initial_from")
    ]
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pilot_only": config.get("pilot_only", True),
        "development_only": config.get("development_only", True),
        "study_phase": config["study_phase"],
        "oracle_set_id": visible["oracle_set_id"],
        "canonical_oracle_manifest_sha256": visible[
            "canonical_manifest_sha256"
        ],
        "model": args.served_model,
        "provider": args.provider,
        "provider_seed_supported": args.provider == "local",
        "remote_seed_policy": (
            "generation_seeds_are_request_slot_ids_not_sent_to_provider"
            if args.provider == "deepseek" else "seed_sent_to_local_endpoint"
        ),
        "model_freeze": (
            {**model_record, **file_identity(checkpoint)}
            if args.provider == "local" else dict(model_record)
        ),
        "tokenizer": file_identity(tokenizer_path),
        "tasks": tasks,
        "methods": methods,
        "seeds": seeds,
        "shared_initial_candidate_policies": policies,
        "config": config_path.relative_to(ROOT).as_posix(),
        "visible_projection": visible_path.relative_to(ROOT).as_posix(),
        "hidden_projection": hidden_path.relative_to(ROOT).as_posix(),
        "input_sha256": {
            "config": sha256_file(config_path),
            "visible_projection": sha256_file(visible_path),
            "hidden_projection": sha256_file(hidden_path),
        },
        "trajectory_count": len(trajectories),
        "formal_results_use": config.get("formal_results_use", False),
        "technical_confirmatory": config.get("technical_confirmatory", False),
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
