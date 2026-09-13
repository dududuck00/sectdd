#!/usr/bin/env python3
"""Analyze complete fixed-call grids using task-cluster inference."""
import collections
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sectdd.feedback_mechanism import METHODS


def load(p):
    return json.loads(p.read_text())


def main():
    config = load(ROOT / "configs/experiments/feedback_mechanism_v1.json")
    output = ROOT / config["output"]
    frozen = load(output / "input-freeze.json")
    digest = hashlib.sha256((output / "input-freeze.json").read_bytes()).hexdigest()
    rows, missing = {}, []
    for initial in frozen["initials"]:
        b, model, task, seed = (initial[k] for k in ("benchmark", "model", "task", "seed"))
        for method in METHODS:
            path = output / b / model / method / task / f"seed_{seed}/trajectory.json"
            key = (b, task, model, seed, method)
            if not path.exists():
                missing.append(key)
                continue
            row = load(path)
            assert row["input_freeze_sha256"] == digest
            assert len(row["rounds"]) == 3 and row["stop_reason"] == "fixed_two_revisions"
            assert not row["hidden_feedback_used"]
            assert [r["request_seed"] for r in row["rounds"][1:]] == [seed + 1, seed + 2]
            rows[key] = row
    report = {"complete": not missing, "expected": len(frozen["initials"]) * len(METHODS), "completed": len(rows), "missing": missing}
    if missing:
        (output / "progress-summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Incomplete: {len(rows)}/{report['expected']}; no inferential result emitted")
        return
    tasks = sorted({(k[0], k[1]) for k in rows})
    methods = list(METHODS)
    values = np.array([[[np.mean([r["final_hidden"][metric] for k, r in rows.items() if k[:2] == t and k[-1] == m]) for metric in ("functional", "security", "joint_pass")] for m in methods] for t in tasks])
    rng = np.random.default_rng(20260910)
    indices = rng.integers(0, len(tasks), size=(10000, len(tasks)))
    report["task_count"] = len(tasks)
    report["inference"] = "Task-cluster bootstrap 10000, seed 20260910; exact task sign randomization; Holm across five planned joint contrasts"
    report["methods"] = {m: dict(zip(("functional", "security", "joint"), values[:, j, :].mean(axis=0).tolist())) for j, m in enumerate(methods)}
    weights = [
        ("binary_minus_blind", {"binary": 1, "blind": -1}),
        ("details_minus_binary", {"fixed_raw": 1, "binary": -1}),
        ("priority_minus_fixed_raw", {"priority_raw": 1, "fixed_raw": -1}),
        ("structured_minus_raw_fixed", {"fixed_structured": 1, "fixed_raw": -1}),
        ("selection_rendering_interaction", {"priority_structured": 1, "priority_raw": -1, "fixed_structured": -1, "fixed_raw": 1}),
    ]
    contrasts = {}
    for name, w in weights:
        d = sum(weight * values[:, methods.index(m), 2] for m, weight in w.items())
        boot = d[indices].mean(axis=1)
        # Only nonzero clusters affect the exact randomization distribution.
        nz = d[np.abs(d) > 1e-12]
        count = 0
        for start in range(0, 2 ** len(nz), 32768):
            ids = np.arange(start, min(start + 32768, 2 ** len(nz)), dtype=np.uint64)
            signs = 2 * ((ids[:, None] >> np.arange(len(nz), dtype=np.uint64)) & 1).astype(float) - 1
            count += int(np.sum(np.abs(signs @ nz) >= abs(d.sum()) - 1e-12))
        contrasts[name] = {"estimate_pp": 100 * float(d.mean()), "ci95_pp": (100 * np.quantile(boot, [.025, .975])).tolist(), "p_task_sign_randomization": count / 2 ** len(nz)}
        if len(w) == 2:
            a = next(m for m, x in w.items() if x == 1)
            b = next(m for m, x in w.items() if x == -1)
            diffs = [int(r["final_hidden"]["joint_pass"]) - int(rows[(*k[:-1], b)]["final_hidden"]["joint_pass"]) for k, r in rows.items() if k[-1] == a]
            contrasts[name].update(wins=diffs.count(1), losses=diffs.count(-1), ties=diffs.count(0))
    ordered = sorted(contrasts, key=lambda n: contrasts[n]["p_task_sign_randomization"])
    running = 0
    for i, name in enumerate(ordered):
        running = max(running, min(1, (len(ordered) - i) * contrasts[name]["p_task_sign_randomization"]))
        contrasts[name]["holm_adjusted_p"] = running
    report["contrasts"] = contrasts
    diagnostics = {}
    for method in methods:
        rr = [r for k, r in rows.items() if k[-1] == method]
        events = [q for r in rr for q in r["rounds"][:-1]]
        regressions = collections.Counter()
        for r in rr:
            before = load(ROOT / r["initial"]["path"])["final_hidden"]
            for metric in ("functional", "security"):
                regressions[metric] += bool(before[metric]["all_passed"]) and not r["final_hidden"][metric]
            regressions["joint"] += bool(before["joint_pass"]) and not r["final_hidden"]["joint_pass"]
        diagnostics[method] = {"regressions": dict(regressions), "feedback_events": len(events), "truncated_events": sum(q["feedback_audit"]["truncated"] for q in events), "selection_set_opportunities": sum(set(q["feedback_audit"]["fixed_case_ids"]) != set(q["feedback_audit"]["priority_case_ids"]) for q in events), "selection_order_opportunities": sum(q["feedback_audit"]["fixed_case_ids"] != q["feedback_audit"]["priority_case_ids"] for q in events), "revision_prompt_tokens": sum(q["usage"].get("prompt_tokens", 0) for r in rr for q in r["rounds"][1:]), "revision_completion_tokens": sum(q["usage"].get("completion_tokens", 0) for r in rr for q in r["rounds"][1:]), "revision_model_seconds": sum(q["model_wall_seconds"] for r in rr for q in r["rounds"][1:])}
    report["diagnostics"] = diagnostics
    target = ROOT / "artifacts/reports/feedback-mechanism-v1.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"complete": True, "contrasts": contrasts}, indent=2))


if __name__ == "__main__":
    main()
