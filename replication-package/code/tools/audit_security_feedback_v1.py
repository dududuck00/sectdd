"""Check full grid, feedback provenance, response reuse, and candidate collection failures."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.run_security_feedback_v1 import freeze,assert_infrastructure
from sectdd.security_feedback import make_feedback
from sectdd.formal_orchestrator import TokenCounter

def main():
 cfg=json.loads((ROOT/'configs/experiments/security_feedback_v1.json').read_text());frozen=freeze(cfg);base=ROOT/cfg['output'];files=list((base/'trajectories').rglob('trajectory.json'));assert len(files)==400
 counters={m:TokenCounter(Path(p)) for m,p in cfg['models'].items()};collection=[];caps=[];calls=0;maxcontext=0
 for path in files:
  r=json.loads(path.read_text());counter=counters[r['model']]
  for before,after in zip(r['rounds'][:2],r['rounds'][1:]):
   feedback,audit=make_feedback(r['method'],before['visible_result'],cfg,counter);assert feedback==before['feedback'] and audit==before['feedback_audit']
   altered=copy.deepcopy(before['visible_result'])
   for c in altered['cases']:
    if c['marker']=='security':c.update(passed=not c['passed'],failure='SECURITY_SENTINEL')
   assert make_feedback('functional_only',altered,cfg,counter)[0]==make_feedback('functional_only',before['visible_result'],cfg,counter)[0]
   original=json.loads((path.parent/f"round_{after['round']}/generation.json").read_text());assert original['response']==after['response'] and original['messages']==after['messages']
   assert after['messages']==before['messages']+[{'role':'assistant','content':before['response']},{'role':'user','content':feedback}]
   assert counter.count_messages(after['messages'])==after['usage']['prompt_tokens'];assert after['usage']['completion_tokens']<=cfg['max_completion_tokens'];maxcontext=max(maxcontext,after['usage']['prompt_tokens']+cfg['max_completion_tokens']);assert maxcontext<=cfg['context_tokens'];calls+=1
   if after['usage']['completion_tokens']==cfg['max_completion_tokens']:caps.append(str(path.relative_to(ROOT))+f"/round_{after['round']}")
   assert_infrastructure(after['visible_result'],after['visible_execution'])
   if after['visible_result'].get('collection_errors'):collection.append({'record':str(path.relative_to(ROOT)),'partition':'visible','round':after['round']})
  assert_infrastructure(r['final_hidden']['raw'],r['final_hidden']['execution'])
  raw=r['final_hidden']['raw'];f=[c['passed'] for c in raw['cases'] if c['marker'] in ['functional','functionality']];s=[c['passed'] for c in raw['cases'] if c['marker']=='security'];assert (f and s) or raw.get('collection_errors');fv,sv=bool(f) and all(f),bool(s) and all(s);assert [r['final_hidden'][k] for k in ['functional','security','joint_pass']]==[fv,sv,fv and sv]
  if raw.get('collection_errors'):collection.append({'record':str(path.relative_to(ROOT)),'partition':'hidden','round':2})
 assert calls==800 and len(list((base/'trajectories').rglob('generation.json')))==800
 report={'complete':True,'trajectories':400,'new_generation_records':800,'feedback_provenance_verified':True,'functional_channel_invariance_verified':True,'archived_response_reuse_verified':True,'token_accounting_verified':True,'max_context_budget_used':maxcontext,'collection_failures_retained':collection,'completion_cap_events_retained':caps,'source_correction':'collection-correction.json; original sources preserved','analysis_source_unchanged':True}
 (ROOT/'artifacts/reports/security-feedback-execution-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)},indent=2));print('collection failures',len(collection),'completion caps',len(caps))
if __name__=='__main__':main()
