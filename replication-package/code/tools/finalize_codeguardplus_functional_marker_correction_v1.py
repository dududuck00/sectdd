#!/usr/bin/env python3
"""Validate and close the CodeGuard+ functional-marker correction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/paper-expansion-full-v1/codeguardplus"
MANIFEST = (
    ROOT
    / "benchmarks/manifests"
    / "codeguardplus-paper-expansion-functional-marker-correction-v1.json"
)
VISIBLE = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json"
MODELS = (
    "qwen25-coder-7b",
    "qwen25-coder-14b",
    "qwen36-27b",
    "deepseek-v4-flash",
)


def summary(result: dict[str, Any], marker: str) -> dict[str, Any]:
    aliases = {"functional", "functionality"} if marker == "functional" else {marker}
    cases = [case for case in result["cases"] if case["marker"] in aliases]
    passed = sum(bool(case["passed"]) for case in cases)
    return {
        "count": len(cases),
        "passed": passed,
        "fraction": passed / len(cases) if cases else None,
        "all_passed": bool(cases) and passed == len(cases),
    }


def main() -> None:
    correction = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not correction.get("prepared"):
        raise RuntimeError("Correction was not prepared")
    visible = json.loads(VISIBLE.read_text(encoding="utf-8"))
    pending = [
        model
        for model in MODELS
        if not (RUN_ROOT / model / "run_manifest.json").is_file()
    ]
    if pending:
        raise RuntimeError(
            "Correction is prepared but model reruns are still pending: "
            + ", ".join(pending)
            + ". Rerun CodeGuard+ for these models before finalizing."
        )
    checked = b2_checked = 0
    for model in MODELS:
        run = RUN_ROOT / model
        run_manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        paths = sorted(run.glob("trajectories/*/*/seed_*/trajectory.json"))
        if len(paths) != 160 or run_manifest.get("trajectory_count") != 160:
            raise RuntimeError(f"Incomplete corrected run: {model}")
        for path in paths:
            item = json.loads(path.read_text(encoding="utf-8"))
            hidden = item["final_hidden"]["raw"]
            functional = summary(hidden, "functional")
            security = summary(hidden, "security")
            if item["final_hidden"]["functional"] != functional:
                raise RuntimeError(f"Functional summary mismatch: {path}")
            if item["final_hidden"]["security"] != security:
                raise RuntimeError(f"Security summary mismatch: {path}")
            if item["final_hidden"]["joint_pass"] != (
                functional["all_passed"] and security["all_passed"]
            ):
                raise RuntimeError(f"Joint summary mismatch: {path}")
            if item["method"] == "B2":
                prompt = json.dumps(item["rounds"][0]["messages"], ensure_ascii=False)
                functional_cases = [
                    case
                    for case in visible["tasks"][item["task"]]["cases"]
                    if case["marker"] in {"functional", "functionality"}
                ]
                if not functional_cases or any(
                    case["case_id"] not in prompt for case in functional_cases
                ):
                    raise RuntimeError(f"B2 functional test absent from prompt: {path}")
                b2_checked += 1
            checked += 1
    if checked != 640 or b2_checked != 80:
        raise RuntimeError(f"Unexpected audit counts: {checked}, {b2_checked}")
    correction["complete"] = True
    correction["formal_results_use"] = True
    correction["validated_trajectory_count"] = checked
    correction["validated_b2_prompt_count"] = b2_checked
    correction["required_post_steps"] = [
        "rerun paper-expansion-full-v1 analysis",
        "rerun paper-evidence-v4 synthesis",
    ]
    MANIFEST.write_text(json.dumps(correction, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "validated_trajectories": checked,
                "validated_b2_prompts": b2_checked,
                "complete": True,
                "formal_results_use": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
