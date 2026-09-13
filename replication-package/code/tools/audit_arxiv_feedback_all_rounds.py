#!/usr/bin/env python3
"""Reproducible all-round, observed-state feedback audit for arXiv v2."""
import collections
import difflib
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_paper_evidence_v3 import RUNS
from sectdd.formal_orchestrator import choose_feedback as cwe_feedback
from sectdd.sallm_formal_orchestrator import choose_feedback as external_feedback
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/reports/arxiv-feedback-all-rounds-v1.json'

def state(row):
 h=row['final_hidden'];return ('F+' if h['functional']['all_passed'] else 'F-')+('S+' if h['security']['all_passed'] else 'S-')

def main():
 events=[]; disagreements=[]
 for benchmark,family,model,root,_ in RUNS:
  for path in sorted((root/'trajectories/M').glob('**/trajectory.json')):
   row=json.loads(path.read_text());seen={}
   raw_path=root/'trajectories/B4'/path.relative_to(root/'trajectories/M')
   raw=json.loads(raw_path.read_text())
   for r in row['rounds']:
    if not r.get('feedback'):continue
    failed=[c for c in r['visible_result']['cases'] if not c['passed']]
    fixed=sorted(failed,key=lambda c:c['case_id'])
    priority=sorted(failed,key=lambda c:(c['marker']!='security',seen.get(c['case_id'],0),c['case_id']))[:2]
    actual=r['feedback_case_ids']
    choose=cwe_feedback if benchmark=='CWEval' else external_feedback
    full,_=choose('sectdd_structured',r['visible_result'],row['generation_seed'],r['round'],dict(seen))
    assert actual==[c['case_id'] for c in priority],(path,r['round'])
    events.append(dict(benchmark=benchmark,model=model,task=row['task'],seed=row['generation_seed'],round=r['round'],trajectory=str(path.relative_to(ROOT)),failed_count=len(failed),fixed_ids=[c['case_id'] for c in fixed],priority_ids=actual,same_set=set(actual)=={c['case_id'] for c in fixed},same_order=actual==[c['case_id'] for c in fixed],feedback_chars=len(r['feedback']),full_feedback_chars=len(full),feedback_truncated=r['feedback']!=full,feedback_tokens=r.get('token_accounting',{}).get('feedback_tokens'),selected_id_present=[c in r['feedback'] for c in actual]))
    for c in priority:seen[c['case_id']]=seen.get(c['case_id'],0)+1
   if row['final_hidden']['joint_pass']!=raw['final_hidden']['joint_pass']:
    b0_path=root/'trajectories/B0'/path.relative_to(root/'trajectories/M');b0=json.loads(b0_path.read_text())
    disagreements.append(dict(benchmark=benchmark,model=model,task=row['task'],seed=row['generation_seed'],initial_state=state(b0),M_state=state(row),B4_state=state(raw),M_path=str(path.relative_to(ROOT)),B4_path=str(raw_path.relative_to(ROOT)),M_rounds=len(row['rounds']),B4_rounds=len(raw['rounds']),M_failed_hidden=[{k:c.get(k) for k in ('case_id','marker','description')} for c in row['final_hidden']['raw']['cases'] if not c['passed']],B4_failed_hidden=[{k:c.get(k) for k in ('case_id','marker','description')} for c in raw['final_hidden']['raw']['cases'] if not c['passed']],final_code_diff=''.join(difflib.unified_diff(raw['rounds'][-1]['response'].splitlines(True),row['rounds'][-1]['response'].splitlines(True),fromfile='B4',tofile='M')),causal_coding='pending: code differences are observations, not isolated causal effects'))
 def summary(xs):return dict(events=len(xs),same_set=sum(e['same_set'] for e in xs),same_order=sum(e['same_order'] for e in xs),failure_counts=dict(collections.Counter(e['failed_count'] for e in xs)),selected_ids_absent_from_delivered_text=sum(not all(e['selected_id_present']) for e in xs),truncated_events=sum(e['feedback_truncated'] for e in xs))
 result=dict(scope='arXiv selected-preprint-v2; counterfactual selection at each M-observed state, not matched later-round B4 states',summary=summary(events),by_round={str(r):summary([e for e in events if e['round']==r]) for r in sorted({e['round'] for e in events})},events=events,disagreements=disagreements,limitations=['Selected ID absence is only a truncation diagnostic, not proof the whole failure was omitted.','Later-round code states differ across methods; do not treat their observed failures as a controlled treatment contrast.','No human causal coding or blind adjudication has been performed.'])
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
 lines=['# arXiv v2 feedback disagreement ledger','', 'All joint-outcome disagreements are included. Labels are observed outcomes; causal attribution requires reading the code and execution records. This ledger is not a human annotation claim.','']
 for i,d in enumerate(disagreements,1):
  lines += [f"## {i}. {d['benchmark']} / {d['model']} / {d['task']} / {d['seed']}",'',f"Initial {d['initial_state']}; B4 {d['B4_state']} ({d['B4_rounds']} calls); M {d['M_state']} ({d['M_rounds']} calls).",'',f"B4: `{d['B4_path']}`",f"M: `{d['M_path']}`",'', '```diff',d['final_code_diff'],'```','']
 (ROOT/'docs/arxiv-feedback-disagreements-v1.md').write_text('\n'.join(lines))
 print(json.dumps({'summary':result['summary'],'by_round':result['by_round'],'disagreements':len(disagreements)},indent=2))
if __name__=='__main__':main()
