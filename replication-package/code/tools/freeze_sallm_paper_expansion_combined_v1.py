#!/usr/bin/env python3
"""Adjudicate and combine SALLM expansion waves under a frozen 2/3 policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WAVES = {
    "wave1": {
        "panel": ROOT / "artifacts/paper-expansion-v1/sallm/semantic-review/report.json",
        "dispute_freeze": ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-semantic-dispute-freeze.json",
        "dispute_report": ROOT / "artifacts/paper-expansion-v1/sallm/semantic-dispute-review/report.json",
        "visible": ROOT / "configs/oracles/sallm_paper_expansion_v1_visible.json",
        "hidden": ROOT / "configs/oracles/sallm_paper_expansion_v1_hidden.json",
    },
    "supplement": {
        "panel": ROOT / "artifacts/paper-expansion-v1/sallm-supplement/semantic-review/report.json",
        "dispute_freeze": ROOT / "benchmarks/manifests/sallm-paper-expansion-supplement-v1-semantic-dispute-freeze.json",
        "dispute_report": ROOT / "artifacts/paper-expansion-v1/sallm-supplement/semantic-dispute-review/report.json",
        "visible": ROOT / "configs/oracles/sallm_paper_expansion_supplement_v1_visible.json",
        "hidden": ROOT / "configs/oracles/sallm_paper_expansion_supplement_v1_hidden.json",
    },
}
VISIBLE = ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json"
HIDDEN = ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json"
VISIBLE_OVERLAY = ROOT / "configs/benchmarks/sallm_paper_expansion_v1_semantic_machine_visible.json"
HIDDEN_OVERLAY = ROOT / "configs/benchmarks/sallm_paper_expansion_v1_semantic_machine_hidden.json"
CANONICAL = ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-oracle.json"
FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json"
MINIMUM = 8


def load(path: Path) -> Any: return json.loads(path.read_text(encoding="utf-8"))
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def rec(path: Path) -> dict[str, Any]: return {"path":path.relative_to(ROOT).as_posix(),"sha256":sha(path),"size_bytes":path.stat().st_size}
def write(path: Path,value: Any) -> None:
    rendered=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered: raise RuntimeError(f"Combined SALLM semantic freeze drift: {path}")
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(rendered,encoding="utf-8")


def adjudicate(name: str, paths: dict[str, Path]) -> tuple[list[str], dict[str, Any]]:
    for key in ("panel","dispute_freeze","visible","hidden"):
        if not paths[key].is_file(): raise FileNotFoundError(paths[key])
    panel,dispute,visible,hidden=map(load,(paths["panel"],paths["dispute_freeze"],paths["visible"],paths["hidden"]))
    if set(visible["tasks"]) != set(hidden["tasks"]): raise RuntimeError(f"{name} projection mismatch")
    unanimous=list(panel["unanimous_machine_accept_tasks"])
    split=sorted(task for task,audit in panel["task_audit"].items() if set(audit["reviewer_verdicts"].values())=={"accept","reject"})
    if dispute["disputed_tasks"] != split or dispute["third_reviewer_packet_contains_prior_verdicts"] is not False: raise RuntimeError(f"{name} dispute freeze mismatch")
    tie_accept=[]
    if split:
        if not paths["dispute_report"].is_file(): raise FileNotFoundError(paths["dispute_report"])
        tie=load(paths["dispute_report"])
        if set(tie["task_audit"]) != set(split): raise RuntimeError(f"{name} tie-break task mismatch")
        for task in split:
            verdicts=tie["task_audit"][task]["reviewer_verdicts"]
            if len(verdicts)!=1 or next(iter(verdicts))!="qwen3-32b": raise RuntimeError(f"{name} unexpected tie-break reviewer")
            if next(iter(verdicts.values()))=="accept": tie_accept.append(task)
    accepted=[task for task in visible["tasks"] if task in set(unanimous)|set(tie_accept)]
    audit={"initial_unanimous_accept":unanimous,"split_tasks":split,"tie_break_accept":tie_accept,"accepted":accepted,"rejected":sorted(set(visible["tasks"])-set(accepted))}
    return accepted,{"audit":audit,"panel":rec(paths["panel"]),"dispute_freeze":rec(paths["dispute_freeze"]),"dispute_report":rec(paths["dispute_report"]) if split else None,"visible":rec(paths["visible"]),"hidden":rec(paths["hidden"])}


def main() -> None:
    accepted_by_wave={}; evidence={}; visible_tasks={}; hidden_tasks={}
    for name,paths in WAVES.items():
        accepted,e=adjudicate(name,paths); accepted_by_wave[name]=accepted; evidence[name]=e
        source_visible,source_hidden=load(paths["visible"]),load(paths["hidden"])
        for task in accepted:
            if task in visible_tasks: raise RuntimeError(f"Duplicate SALLM task across waves: {task}")
            visible_tasks[task]=source_visible["tasks"][task]; hidden_tasks[task]=source_hidden["tasks"][task]
    tasks=list(visible_tasks)
    if len(tasks)<MINIMUM: raise RuntimeError(f"Only {len(tasks)} SALLM tasks passed semantic adjudication; requires {MINIMUM}")
    canonical={"schema_version":1,"oracle_set_id":"sallm-paper-expansion-v1-semantic-machine","benchmark":"sallm","created_at_utc":datetime.now(timezone.utc).isoformat(),"tasks":tasks,"semantic_policy":"initial unanimous accept or blinded third-model 2/3 majority accept","method_or_g8_outcome_filter_applied":False,"independent_human_review_complete":False,"formal_results_use":False,"accepted_by_wave":accepted_by_wave,"evidence":evidence}
    if CANONICAL.exists(): canonical["created_at_utc"]=load(CANONICAL)["created_at_utc"]
    write(CANONICAL,canonical); canonical_hash=sha(CANONICAL)
    common={"schema_version":1,"oracle_set_id":canonical["oracle_set_id"],"canonical_manifest_sha256":canonical_hash,"machine_semantic_review_complete":True,"independent_human_review_complete":False}
    overlays = {}
    for partition, destination in (("visible", VISIBLE_OVERLAY), ("hidden", HIDDEN_OVERLAY)):
        source_paths = [WAVES[name][partition] for name in WAVES]
        source_overlays = [load(ROOT / load(path)["execution_overlay"]["path"]) for path in source_paths]
        combined = dict(source_overlays[0])
        combined["overlay_id"] = f"sallm-paper-expansion-v1-semantic-machine-{partition}"
        combined["oracle_set_id"] = "sallm-paper-expansion-v1-semantic-machine"
        combined["oracle_partition"] = partition
        combined["scope"] = {"qualified_task_ids": accepted, "task_count": len(accepted)}
        combined["test_overrides"] = {}
        for task in accepted:
            for source in source_overlays:
                if task in source.get("test_overrides", {}):
                    combined["test_overrides"][task] = source["test_overrides"][task]
                    break
            else:
                raise RuntimeError(f"Accepted task absent from {partition} overlays: {task}")
        write(destination, combined)
        overlays[partition] = rec(destination)
    write(VISIBLE,{**common,"partition":"visible","execution_overlay":overlays["visible"],"tasks":visible_tasks}); write(HIDDEN,{**common,"partition":"hidden","execution_overlay":overlays["hidden"],"tasks":hidden_tasks})
    freeze={"schema_version":1,"freeze_id":canonical["oracle_set_id"],"complete":True,"qualified_task_count":len(tasks),"qualified_tasks":tasks,"accepted_by_wave":accepted_by_wave,"method_or_g8_outcome_filter_applied":False,"independent_human_review_complete":False,"formal_results_use":False,"inputs":evidence,"outputs":{"canonical":rec(CANONICAL),"visible":rec(VISIBLE),"hidden":rec(HIDDEN)}}
    write(FREEZE,freeze)
    print(json.dumps({"qualified_task_count":len(tasks),"accepted_by_wave":accepted_by_wave,"complete":True},indent=2))


if __name__=="__main__": main()
