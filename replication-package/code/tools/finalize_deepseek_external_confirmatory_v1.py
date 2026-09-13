#!/usr/bin/env python3
"""Validate, summarize, and freeze the DeepSeek external confirmation."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from analyze_codeguardplus_technical_confirmatory_v1 import paired
from analyze_sallm_main import load_run


ARTIFACT = ROOT / "artifacts/deepseek-external-confirmatory-v1"
LOCK = ROOT / "configs/experiments/deepseek_external_confirmatory_v1.lock.json"
REPORT = ARTIFACT / "report.json"
MARKDOWN = ROOT / "docs/deepseek-external-confirmatory-v1.md"
FREEZE = ROOT / "benchmarks/manifests/deepseek-external-confirmatory-v1-results-freeze.json"
METHODS = ("B0", "B3", "B4", "M", "B6")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def load_and_validate_run(path: Path, expected: int) -> tuple[dict, list[dict]]:
    manifest, trajectories = load_run(path)
    if len(trajectories) != expected:
        raise RuntimeError(f"Expected {expected} trajectories in {path}, got {len(trajectories)}")
    if manifest.get("model") != "deepseek-v4-flash":
        raise RuntimeError(f"Unexpected model in {path}")
    if manifest.get("provider") != "deepseek":
        raise RuntimeError(f"Unexpected provider in {path}")
    if manifest.get("provider_seed_supported") is not False:
        raise RuntimeError(f"Remote seed policy is not explicit in {path}")
    if manifest.get("formal_results_use") is not False:
        raise RuntimeError(f"Formal boundary missing in {path}")
    for trajectory in trajectories:
        audit = trajectory.get("hidden_leak_audit", {})
        if not audit.get("passed") or audit.get("hidden_feedback_used"):
            raise RuntimeError("Hidden-test isolation failure")
        for round_value in trajectory.get("rounds", []):
            candidate = ROOT / round_value["candidate"]["path"]
            if (not candidate.is_file() or
                    sha256(candidate) != round_value["candidate"]["sha256"]):
                raise RuntimeError(f"Candidate hash drift: {candidate}")
    trajectory_hashes = manifest.get("trajectory_sha256")
    if trajectory_hashes:
        for relative, digest in trajectory_hashes.items():
            trajectory_path = path / relative
            if not trajectory_path.is_file() or sha256(trajectory_path) != digest:
                raise RuntimeError(f"Trajectory hash drift: {trajectory_path}")
    return manifest, trajectories


def method_rows(subreport: dict) -> dict:
    model = subreport["models"][0]
    if model["model"] != "deepseek-v4-flash":
        raise RuntimeError("Subreport model mismatch")
    return model["methods"]


def markdown(report: dict) -> str:
    lines = [
        "# DeepSeek 非 Qwen 外部确认实验", "",
        (
            f"设计：1 个远端非 Qwen 模型 × 2 个外部基准，共 "
            f"{report['design']['trajectories']} 条轨迹。"
        ), "",
        "| Benchmark | Method | Func | Secure | Joint | SAFE | Calls |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for benchmark, value in report["benchmarks"].items():
        for method in METHODS:
            item = value["methods"][method]
            lines.append(
                f"| {benchmark} | {method} | {item['functional']:.3f} | "
                f"{item['secure']:.3f} | {item['joint']:.3f} | "
                f"{item['safe']:.3f} | {item['mean_calls']:.2f} |"
            )
    lines += ["", "## 配对反馈事件", "",
              "| Benchmark | Pair | Trigger | Joint repair | Joint regression | Function regression |",
              "|---|---|---:|---:|---:|---:|"]
    for benchmark, value in report["benchmarks"].items():
        for name, item in value["paired_feedback"].items():
            lines.append(
                f"| {benchmark} | {name} | {item['feedback_trigger_count']} | "
                f"{item['joint_improvement_count']} | {item['joint_regression_count']} | "
                f"{item['function_regression_count']} |"
            )
    lines += [
        "", "## 解释边界", "",
        "- 这是模型家族外部效度检查，用于判断观察到的测试反馈效应是否仅属于 Qwen。",
        "- DeepSeek API 不承诺本实验所需的确定性 seed；冻结数字是独立请求槽和配对键，未作为 seed 发送给服务端。",
        "- 远端版本可能漂移，模型标识、调用时间、原始响应与 API usage 均保留在轨迹中；本结果不能表述成位级可复现实验。",
        "- CodeGuard+ 仍缺独立人工 G7，因此整个 wave 保持 `formal_results_use=false`。",
        "- 论文主结论应聚焦“测试反馈可修复部分安全失败并揭示安全—功能权衡”，而不是声称某一种方法在所有场景恒优。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for item in lock["frozen_files"].values():
        path = ROOT / item["path"]
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"Frozen input drift: {path}")
    expected = lock["expected"]
    sallm_manifest, sallm_records = load_and_validate_run(
        ARTIFACT / "sallm", expected["sallm_trajectories"]
    )
    codeguard_manifest, codeguard_records = load_and_validate_run(
        ARTIFACT / "codeguardplus", expected["codeguardplus_trajectories"]
    )
    sallm_report_path = ARTIFACT / "sallm-report.json"
    codeguard_report_path = ARTIFACT / "codeguardplus-report.json"
    sallm_report = json.loads(sallm_report_path.read_text(encoding="utf-8"))
    codeguard_report = json.loads(codeguard_report_path.read_text(encoding="utf-8"))
    total = len(sallm_records) + len(codeguard_records)
    if total != expected["total_trajectories"]:
        raise RuntimeError("Combined trajectory count mismatch")
    report = {
        "schema_version": 1,
        "report_id": "deepseek-external-confirmatory-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_results_use": False,
        "technical_confirmatory": True,
        "model": "deepseek-v4-flash",
        "provider_seed_supported": False,
        "design": {
            "benchmarks": 2,
            "tasks": len(sallm_manifest["tasks"]) + len(codeguard_manifest["tasks"]),
            "methods": 5,
            "request_slots": len(lock["generation_request_slots"]),
            "trajectories": total,
        },
        "benchmarks": {
            "SALLM": {
                "oracle_set_id": sallm_manifest["oracle_set_id"],
                "trajectory_count": len(sallm_records),
                "methods": method_rows(sallm_report),
                "paired_feedback": paired(sallm_records),
            },
            "CodeGuard+": {
                "oracle_set_id": codeguard_manifest["oracle_set_id"],
                "trajectory_count": len(codeguard_records),
                "methods": method_rows(codeguard_report),
                "paired_feedback": paired(codeguard_records),
            },
        },
        "interpretation_boundary": lock["interpretation_boundary"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    MARKDOWN.write_text(markdown(report), encoding="utf-8")
    freeze = {
        "schema_version": 1,
        "freeze_id": "deepseek-external-confirmatory-v1-results",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": False,
        "technical_confirmatory": True,
        "summary": report["design"],
        "inputs": {"lock": record(LOCK), **lock["frozen_files"]},
        "outputs": {
            "combined_report": record(REPORT),
            "combined_markdown": record(MARKDOWN),
            "sallm_report": record(sallm_report_path),
            "codeguardplus_report": record(codeguard_report_path),
            "sallm_manifest": record(ARTIFACT / "sallm/run_manifest.json"),
            "codeguardplus_manifest": record(ARTIFACT / "codeguardplus/run_manifest.json"),
        },
        "interpretation_boundary": lock["interpretation_boundary"],
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report["design"], "complete": True, "formal_results_use": False}, indent=2))
    print(f"Results freeze: {FREEZE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
