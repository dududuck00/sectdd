#!/usr/bin/env python3
"""Run frozen, shared-initial, two-revision interventions on all 20 primary tasks."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sectdd.feedback_mechanism import METHODS, make_feedback, select_cases
from sectdd.orchestrator import call_model, configure_local_network, write_candidate_eval
from sectdd.formal_orchestrator import TokenCounter, run_paper_partition
from sectdd import sallm_formal_orchestrator as sallm
from sectdd import codeguardplus_formal_orchestrator as cg

CONFIG = ROOT / "configs/experiments/feedback_mechanism_v1.json"


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def projection(benchmark, partition):
    prefix = "cweval_py" if benchmark == "cweval" else benchmark
    return ROOT / f"configs/oracles/{prefix}_paper_expansion_v1_semantic_machine_{partition}.json"


def candidate(benchmark, task, dest, index, response):
    if benchmark == "cweval":
        return write_candidate_eval(dest, task, index, response)
    if benchmark == "sallm":
        return sallm.write_candidate(dest, task, index, response)[0]
    return cg.write_candidate(dest, index, response)


def evaluate(benchmark, task, code, partition, output, python_info):
    if benchmark == "cweval":
        return run_paper_partition(code, partition, task, 20, 180)
    if benchmark == "sallm":
        return sallm.run_partition(task=task, candidate_root=code, projection_path=partition, output=output, timeout_seconds=20)
    return cg.run_partition(task, code, partition, output, 20, python_info)


def freeze(config, output):
    # Hashes bind the known archived evidence; hidden contents are never supplied
    # to generation. This is a post-primary experiment, not a fresh holdout study.
    paths = [CONFIG, Path(__file__), ROOT / "sectdd/feedback_mechanism.py", ROOT / "docs/feedback-mechanism-v1-protocol.md"]
    paths += [ROOT / "sectdd" / name for name in ("orchestrator.py", "formal_orchestrator.py", "sallm_formal_orchestrator.py", "codeguardplus_formal_orchestrator.py")]
    for b in config["benchmarks"]:
        paths += [projection(b, p) for p in ("visible", "hidden")]
    initials = []
    for b in config["benchmarks"]:
        tasks = sorted(load(projection(b, "visible"))["tasks"])
        for model in config["models"]:
            for task in tasks:
                for seed in config["seeds"]:
                    p = ROOT / config["initial_root"] / b / model / "trajectories/B0" / task.replace("/", "__") / f"seed_{seed}/trajectory.json"
                    row = load(p)
                    assert row["model"] == model and row["task"] == task and row["generation_seed"] == seed
                    assert len(row["rounds"]) == 1
                    initials.append({"benchmark": b, "model": model, "task": task, "seed": seed, "path": str(p.relative_to(ROOT)), "sha256": sha(p)})
    result = {"config": config, "files": {str(p.relative_to(ROOT)): sha(p) for p in paths}, "initials": initials}
    target = output / "input-freeze.json"
    if target.exists():
        if load(target) != result:
            raise RuntimeError("Inputs changed after freeze; use a new experiment version")
    else:
        write(target, result)
    return result


def run_one(initial, method, config, output, api, tokenizer, python_info, freeze_sha):
    b, model, task, seed = (initial[k] for k in ("benchmark", "model", "task", "seed"))
    dest = output / b / model / method / task / f"seed_{seed}"
    target = dest / "trajectory.json"
    if target.exists():
        row = load(target)
        assert row["input_freeze_sha256"] == freeze_sha and len(row["rounds"]) == 3
        return
    # Only the initial prompt, response and visible observations leave this block.
    first = load(ROOT / initial["path"])["rounds"][0]
    messages, response = first["messages"], first["response"]
    visible = first["visible_result"]
    rounds = [{"round": 0, "response": response, "messages": messages, "visible_result": visible, "generation_reused": True}]
    seen = {}
    for index in (1, 2):
        before_seen = dict(seen)
        full, ids = make_feedback(method, visible, seen)
        feedback = tokenizer.truncate_text(full, config["feedback_tokens"])
        fixed = select_cases(visible["cases"], "fixed", before_seen)
        priority = select_cases(visible["cases"], "priority", before_seen)
        rounds[-1]["feedback"] = feedback
        rounds[-1]["feedback_full"] = full
        rounds[-1]["feedback_case_ids"] = ids
        rounds[-1]["feedback_audit"] = {
            "full_tokens": tokenizer.count_text(full), "delivered_tokens": tokenizer.count_text(feedback),
            "truncated": full != feedback,
            "fixed_case_ids": [c["case_id"] for c in fixed], "priority_case_ids": [c["case_id"] for c in priority],
        }
        messages = [*messages, {"role": "assistant", "content": response}, {"role": "user", "content": feedback}]
        if tokenizer.count_messages(messages) + config["max_completion_tokens"] > config["context_tokens"]:
            raise RuntimeError(f"Context cannot accommodate fixed budget: {b}/{model}/{method}/{task}/{seed}")
        response, usage, elapsed = call_model(model, api, messages, seed + index, config["temperature"], config["max_completion_tokens"])
        code = candidate(b, task, dest, index, response)
        visible, execution = evaluate(b, task, code, projection(b, "visible"), dest / f"round_{index}/visible_execution", python_info)
        rounds.append({"round": index, "messages": messages, "response": response, "request_seed": seed + index, "usage": usage, "model_wall_seconds": elapsed, "visible_result": visible, "visible_execution": execution})
        write(dest / "progress.json", {"rounds": rounds, "input_freeze_sha256": freeze_sha})
    # Both revision decisions and the final candidate are now frozen.
    hidden, execution = evaluate(b, task, code, projection(b, "hidden"), dest / "hidden_execution", python_info)
    functional = [c for c in hidden["cases"] if c["marker"] in {"functional", "functionality"}]
    security = [c for c in hidden["cases"] if c["marker"] == "security"]
    f, s = bool(functional) and all(c["passed"] for c in functional), bool(security) and all(c["passed"] for c in security)
    write(target, {"schema_version": 1, "benchmark": b, "model": model, "task": task, "generation_seed": seed, "method": method, "input_freeze_sha256": freeze_sha, "initial": initial, "rounds": rounds, "stop_reason": "fixed_two_revisions", "final_hidden": {"functional": f, "security": s, "joint_pass": f and s, "raw": hidden, "execution": execution}, "hidden_feedback_used": False})
    print(f"DONE {b}/{model}/{method}/{task}/{seed}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["qwen25-coder-7b", "qwen25-coder-14b"])
    parser.add_argument("--api-base", default="http://127.0.0.1:19882/v1")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    configure_local_network()
    config = load(CONFIG)
    output = ROOT / config["output"]
    frozen = freeze(config, output)
    if args.freeze_only:
        print(f"Frozen {len(frozen['initials'])} shared initials, {len(frozen['initials']) * len(METHODS)} trajectories")
        return
    if not args.model:
        parser.error("--model required for generation")
    tokenizer = TokenCounter(Path(config["models"][args.model]))
    python_info = cg.python_metadata(cg.DEFAULT_PYTHON.absolute())
    freeze_sha = sha(output / "input-freeze.json")
    work = [(i, m) for i in frozen["initials"] if i["model"] == args.model for m in METHODS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(run_one, i, m, config, output, args.api_base, tokenizer, python_info, freeze_sha) for i, m in work]
        for job in concurrent.futures.as_completed(jobs):
            job.result()


if __name__ == "__main__":
    main()
