#!/usr/bin/env python3
"""Run one model over the frozen CodeGuard+ G8 preflight grid."""

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

from sectdd.codeguardplus_formal_orchestrator import TokenCounter, aggregate_trajectories, run_trajectory, sha256_file
from sectdd.orchestrator import PROJECT_ROOT, configure_local_network
from tools.codeguardplus_bwrap import python_metadata, DEFAULT_PYTHON

def args():
    p=argparse.ArgumentParser(); p.add_argument("--served-model",required=True); p.add_argument("--api-base",required=True); p.add_argument("--provider",choices=("local","deepseek"),default="local"); p.add_argument("--api-key-env",default="DEEPSEEK_API_KEY"); p.add_argument("--tokenizer",type=Path,required=True); p.add_argument("--config",type=Path,default=PROJECT_ROOT/"configs/experiments/codeguardplus_preflight_v1.json"); p.add_argument("--visible",type=Path,default=PROJECT_ROOT/"configs/oracles/codeguardplus_preflight_visible_v1.json"); p.add_argument("--hidden",type=Path,default=PROJECT_ROOT/"configs/oracles/codeguardplus_preflight_hidden_v1.json"); p.add_argument("--output",type=Path,required=True); p.add_argument("--task",action="append",dest="tasks"); p.add_argument("--method",action="append",dest="methods"); p.add_argument("--seed",action="append",type=int,dest="seeds"); p.add_argument("--resume",action="store_true"); return p.parse_args()
def identity(path: Path):
    files={};
    for name in ("config.json","tokenizer.json","tokenizer_config.json","model.safetensors.index.json"):
        if (path/name).is_file(): files[name]=sha256_file(path/name)
    return {"path":str(path),"files_sha256":files}
def main():
    a=args(); output=a.output.resolve(); output.relative_to(PROJECT_ROOT)
    if output.exists() and not a.resume: raise FileExistsError(output)
    config_path=a.config.resolve(); visible_path=a.visible.resolve(); hidden_path=a.hidden.resolve(); config=json.loads(config_path.read_text()); visible=json.loads(visible_path.read_text()); hidden=json.loads(hidden_path.read_text())
    if visible["oracle_set_id"]!=hidden["oracle_set_id"] or config["oracle_set_id"]!=visible["oracle_set_id"]: raise RuntimeError("Oracle set mismatch")
    tasks=a.tasks or config['tasks']; methods=a.methods or list(config['methods']); seeds=a.seeds or config['generation_seeds']
    if set(tasks)-set(config['tasks']) or set(tasks)-set(visible['tasks']) or set(tasks)-set(hidden['tasks']): raise RuntimeError("Unknown task")
    if set(methods)-set(config['methods']): raise RuntimeError("Unknown method")
    if len(seeds)!=len(set(seeds)): raise RuntimeError("Generation seeds must be unique")
    positions={method:index for index,method in enumerate(methods)}
    for method in methods:
        reference=config['methods'][method].get('shared_initial_from')
        if reference is not None and (reference not in positions or positions[reference]>positions[method]): raise RuntimeError(f"{method} requires earlier shared reference {reference}")
    model_record=config["models"][a.served_model]; tokenizer_path=a.tokenizer.resolve()
    if model_record.get("provider","local")!=a.provider: raise RuntimeError("CLI provider/model registry mismatch")
    if a.provider=="local":
        checkpoint=Path(model_record["checkpoint"]).resolve()
        if checkpoint!=tokenizer_path: raise RuntimeError("Tokenizer/checkpoint mismatch")
        api_key="local-sectdd"; opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        if Path(model_record["tokenizer_proxy"]).resolve()!=tokenizer_path: raise RuntimeError("Tokenizer/budget proxy mismatch")
        if not a.api_base.rstrip('/').startswith('https://api.deepseek.com'): raise RuntimeError("DeepSeek provider requires official HTTPS API base")
        api_key=os.environ.get(a.api_key_env,'').strip()
        if not api_key: raise RuntimeError(f"{a.api_key_env} is required")
        os.environ['DEEPSEEK_API_KEY']=api_key; opener=urllib.request.build_opener()
    configure_local_network(); request=urllib.request.Request(f"{a.api_base.rstrip('/')}/models",headers={"Authorization":f"Bearer {api_key}"})
    with opener.open(request,timeout=10) as response: available={x['id'] for x in json.load(response).get('data',[])}
    if a.served_model not in available: raise RuntimeError("Served model unavailable")
    tokenizer=TokenCounter(tokenizer_path); py_info=python_metadata(DEFAULT_PYTHON.absolute()); output.mkdir(parents=True,exist_ok=a.resume)
    trajectories=[]; shared={}; total=len(tasks)*len(methods)*len(seeds); done=0
    for task in tasks:
        slug=task.replace('/','__')
        for method_id in methods:
            method=config['methods'][method_id]
            for seed in seeds:
                ref=method.get('shared_initial_from')
                trajectory_path=output/'trajectories'/method_id/slug/f'seed_{seed}'/'trajectory.json'
                if a.resume and trajectory_path.is_file():
                    trajectory=json.loads(trajectory_path.read_text(encoding='utf-8'))
                    if (trajectory.get('task'),trajectory.get('model'),trajectory.get('method'),trajectory.get('generation_seed'))!=(task,a.served_model,method_id,seed): raise RuntimeError(f"Resume trajectory identity drift: {trajectory_path}")
                    if trajectory.get('oracle_set_id')!=visible['oracle_set_id'] or trajectory.get('method_config')!=method: raise RuntimeError(f"Resume trajectory protocol drift: {trajectory_path}")
                    audit=trajectory.get('hidden_leak_audit',{})
                    if not audit.get('passed') or audit.get('hidden_evaluation_count')!=1 or audit.get('hidden_feedback_used'): raise RuntimeError(f"Resume hidden isolation failure: {trajectory_path}")
                    for round_value in trajectory.get('rounds',[]):
                        candidate=PROJECT_ROOT/round_value['candidate']['path']
                        if not candidate.is_file() or sha256_file(candidate)!=round_value['candidate']['sha256']: raise RuntimeError(f"Resume candidate drift: {candidate}")
                else:
                    trajectory=run_trajectory(task=task,generation_seed=seed,method_id=method_id,method=method,config=config,served_model=a.served_model,api_base=a.api_base,tokenizer=tokenizer,visible_projection=visible,visible_projection_path=visible_path,hidden_projection_path=hidden_path,trajectory_dir=output/'trajectories'/method_id/slug/f'seed_{seed}',python_info=py_info,initial_generation=shared[(ref,task,seed)] if ref else None)
                first=trajectory['rounds'][0]; shared[(method_id,task,seed)]={k:first[k] for k in ('messages','request_seed','response','usage','model_wall_seconds')}; trajectories.append(trajectory); done+=1; print(f"[{done}/{total}] {method_id} {task} seed={seed} calls={len(trajectory['rounds'])} hidden_joint={trajectory['final_hidden']['joint_pass']}",flush=True)
    trajectory_records={path.relative_to(output).as_posix():sha256_file(path) for path in sorted((output/'trajectories').glob('*/*/seed_*/trajectory.json'))}
    if len(trajectory_records)!=len(trajectories): raise RuntimeError("Trajectory file grid mismatch")
    manifest={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),"pilot_only":config.get("pilot_only",True),"development_only":config.get("development_only",True),"formal_results_use":config.get("formal_results_use",False),"technical_confirmatory":config.get("technical_confirmatory",False),"study_phase":config['study_phase'],"oracle_set_id":visible['oracle_set_id'],"canonical_oracle_manifest_sha256":visible['canonical_manifest_sha256'],"model":a.served_model,"provider":a.provider,"provider_seed_supported":a.provider=="local","remote_seed_policy":"generation_seeds_are_request_slot_ids_not_sent_to_provider" if a.provider=="deepseek" else "seed_sent_to_local_endpoint","model_freeze":({**model_record,**identity(checkpoint)} if a.provider=="local" else dict(model_record)),"tokenizer":identity(tokenizer_path),"tasks":tasks,"methods":methods,"seeds":seeds,"config":config_path.relative_to(PROJECT_ROOT).as_posix(),"visible_projection":visible_path.relative_to(PROJECT_ROOT).as_posix(),"hidden_projection":hidden_path.relative_to(PROJECT_ROOT).as_posix(),"input_sha256":{"config":sha256_file(config_path),"visible_projection":sha256_file(visible_path),"hidden_projection":sha256_file(hidden_path)},"trajectory_count":len(trajectories),"trajectory_sha256":trajectory_records}
    (output/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); (output/'summary.json').write_text(json.dumps(aggregate_trajectories(trajectories),indent=2)+'\n'); print(output/'summary.json')
if __name__=='__main__': main()
