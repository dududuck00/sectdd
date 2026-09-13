#!/usr/bin/env python3
"""Create the deterministic lock for amended SALLM external main v1.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/experiments/sallm_partitioned_main_v1_1.json"
LOCK = ROOT / "configs/experiments/sallm_partitioned_main_v1_1.lock.json"
INPUTS = (
    CONFIG,
    ROOT / "protocol.md",
    ROOT / "configs/oracles/sallm_partitioned_oracle_v3_visible.json",
    ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json",
    ROOT / "benchmarks/manifests/sallm-partitioned-oracle-v3-freeze.json",
    ROOT / "sectdd/sallm_formal_orchestrator.py",
    ROOT / "tools/sallm_bwrap.py",
    ROOT / "tools/run_sallm_formal.py",
    ROOT / "tools/run_sallm_task_shards.py",
    ROOT / "tools/merge_sallm_formal_shards.py",
    ROOT / "tools/validate_sallm_formal.py",
    ROOT / "tools/analyze_sallm_main.py",
    ROOT / "scripts/serve_qwen25_coder.sh",
    ROOT / "scripts/serve_qwen36.sh",
    ROOT / "scripts/run_sallm_main_local.sh",
)
MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    config = json.loads(CONFIG.read_text())
    lock = {
        "schema_version": 1,
        "lock_id": "sallm-partitioned-main-v1.1",
        "amendment": {
            "supersedes": config["supersedes"],
            "reason": config["amendment_reason"],
        },
        "experiment_shape": {
            "tasks": len(config["tasks"]),
            "seeds": len(config["generation_seeds"]),
            "methods": len(config["methods"]),
            "models": len(config["models"]),
            "trajectories_per_model": (
                len(config["tasks"])
                * len(config["generation_seeds"])
                * len(config["methods"])
            ),
        },
        "input_sha256": {
            path.relative_to(ROOT).as_posix(): digest(path) for path in INPUTS
        },
        "models": {},
    }
    for model, metadata in config["models"].items():
        root = Path(metadata["checkpoint"]).resolve()
        files = {
            name: digest(root / name)
            for name in MODEL_FILES
            if (root / name).is_file()
        }
        if "config.json" not in files or "tokenizer_config.json" not in files:
            raise RuntimeError(f"Incomplete checkpoint: {root}")
        lock["models"][model] = {
            "checkpoint": str(root),
            "files_sha256": files,
        }
    LOCK.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {LOCK.relative_to(ROOT)} for "
        f"{lock['experiment_shape']['trajectories_per_model']} "
        "trajectories/model"
    )


if __name__ == "__main__":
    main()
