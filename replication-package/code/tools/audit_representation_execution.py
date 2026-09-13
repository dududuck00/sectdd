"""Audit infrastructure recovery and complete-grid execution, without changing scores."""
import ast,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 base=ROOT/'artifacts/representation-v1';paths=list((base/'trajectories').rglob('trajectory.json'));assert len(paths)==480
 cfg=json.loads((base/'input-freeze.json').read_text());sha=hashlib.sha256((base/'input-freeze.json').read_bytes()).hexdigest();prompts={(p['task'],p['method']):p['messages'] for p in cfg['prompts']}
 syntax=[];at_cap=[];token_drift=[];max_prompt=0
 for path in paths:
  r=json.loads(path.read_text());g=json.loads((path.parent/'generation.json').read_text());q=r['rounds'][0]
  assert r['input_freeze_sha256']==g['input_freeze_sha256']==sha
  assert q['response']==g['response'] and q['messages']==g['messages']==prompts[r['task'],r['method']]
  assert not r['hidden_feedback_used'];assert q['usage']['completion_tokens']<=3072
  max_prompt=max(max_prompt,q['usage']['prompt_tokens'])
  if q['usage']['prompt_tokens']!=q['prompt_tokens_local']:token_drift.append(str(path.relative_to(ROOT)))
  if q['usage']['completion_tokens']==3072:at_cap.append(str(path.relative_to(ROOT)))
  for log in path.parent.glob('*_execution/*.log'):
   txt=log.read_text(errors='replace');assert not txt.startswith(('bwrap:','prlimit:')) and 'setting up uid map: Permission denied' not in txt,str(log)
  if r['benchmark']=='sallm':
   for e in [q['visible_execution'],r['final_hidden']['execution']]:
    assert '"infrastructure_error_task_count": 0' in e['stdout'];assert '"completed_task_count": 1' in e['stdout']
  files=list((path.parent/'round_0/candidate').glob('*.py'));assert len(files)==1
  try:ast.parse(files[0].read_text())
  except SyntaxError:syntax.append(str(path.relative_to(ROOT)))
 result={'complete':True,'trajectories':480,'raw_generation_records':len(list((base/'trajectories').rglob('generation.json'))),'identical_archived_response_reuse_verified':True,'quarantined_infrastructure_records':len(list((base/'infrastructure-interruption').rglob('trajectory.json'))),'remaining_detected_infrastructure_errors':0,'syntax_error_candidates_retained':syntax,'completion_cap_candidates_retained':at_cap,'prompt_token_counter_mismatches':token_drift,'max_prompt_tokens':max_prompt,'hidden_feedback_used':False}
 assert not token_drift;assert result['raw_generation_records']==480
 (ROOT/'artifacts/reports/representation-execution-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
