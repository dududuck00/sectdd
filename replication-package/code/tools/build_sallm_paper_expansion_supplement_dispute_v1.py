#!/usr/bin/env python3
"""Freeze verdict-blind third-review packets for supplement split decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "artifacts/paper-expansion-v1/sallm-supplement/semantic-review/report.json"
SOURCE_ORACLE = ROOT / "oracles/sallm_paper_expansion_supplement_v1/manifest.json"
SOURCE_FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-supplement-v1-partition-freeze.json"
TASKS = ROOT / "configs/benchmarks/sallm_paper_expansion_supplement_v1_disputed.json"
ORACLE = ROOT / "oracles/sallm_paper_expansion_supplement_v1_dispute/manifest.json"
FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-supplement-v1-semantic-dispute-freeze.json"


def load(path: Path) -> Any: return json.loads(path.read_text(encoding="utf-8"))
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def rec(path: Path) -> dict[str, Any]: return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}
def write(path: Path, value: Any) -> None:
    rendered=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered: raise RuntimeError(f"Supplement dispute drift: {path}")
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(rendered,encoding="utf-8")


def main() -> None:
    for path in (PANEL,SOURCE_ORACLE,SOURCE_FREEZE):
        if not path.is_file(): raise FileNotFoundError(path)
    panel,source=load(PANEL),load(SOURCE_ORACLE)
    disputed=sorted(task for task,audit in panel["task_audit"].items() if set(audit["reviewer_verdicts"].values())=={"accept","reject"})
    unanimous_reject=sorted(task for task,audit in panel["task_audit"].items() if set(audit["reviewer_verdicts"].values())=={"reject"})
    write(TASKS,{"schema_version":1,"prior_verdicts_in_reviewer_packet":False,"tasks":disputed})
    write(ORACLE,{**{k:v for k,v in source.items() if k!="tasks"},"oracle_set_id":"sallm-paper-expansion-supplement-v1-dispute","status":"blinded_third_model_review_pending","tasks":{task:source["tasks"][task] for task in disputed}})
    freeze={"schema_version":1,"freeze_id":"sallm-paper-expansion-supplement-v1-semantic-dispute","created_at_utc":datetime.now(timezone.utc).isoformat(),"third_reviewer_packet_contains_prior_verdicts":False,"resolution_policy":"blinded Qwen3-32B tie-break; two-of-three majority","disputed_tasks":disputed,"unanimous_reject_tasks_not_disputed":unanimous_reject,"formal_results_use":False,"inputs":{"partition_freeze":rec(SOURCE_FREEZE),"oracle":rec(SOURCE_ORACLE),"panel":rec(PANEL)},"outputs":{"tasks":rec(TASKS),"oracle":rec(ORACLE)}}
    if FREEZE.exists(): freeze["created_at_utc"]=load(FREEZE)["created_at_utc"]
    write(FREEZE,freeze)
    print(json.dumps({"disputed_tasks":disputed,"unanimous_reject_tasks":unanimous_reject,"freeze_valid":True},indent=2))


if __name__=="__main__": main()
