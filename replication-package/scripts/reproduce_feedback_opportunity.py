"""Post-hoc descriptive strata from pre-revision visible outcomes; no new generation."""
import argparse,collections,gzip,hashlib,json
from pathlib import Path
METRICS=['functional','security','joint_pass']
ORDER=['F+S+','F+S-','F-S+','F-S-','not_run']
def state(raw):
 cs=raw['cases'];f=[c['passed'] for c in cs if c['marker'] in ['functional','functionality']];s=[c['passed'] for c in cs if c['marker']=='security']
 if not f or not s:return 'not_run'
 return ('F+' if all(f) else 'F-')+('S+' if all(s) else 'S-')
def summary(initial,final):
 return {'n':len(final),'rates_pct':{k:100*sum(r['final_hidden'][k] for r in final)/len(final) for k in METRICS},'joint_repairs':sum(not a['joint_pass'] and b['final_hidden']['joint_pass'] for a,b in zip(initial,final)),'joint_regressions':sum(a['joint_pass'] and not b['final_hidden']['joint_pass'] for a,b in zip(initial,final)),'functional_regressions':sum(a['functional'] and not b['final_hidden']['functional'] for a,b in zip(initial,final)),'function_preserving_security_repairs':sum(a['functional'] and not a['security'] and b['final_hidden']['joint_pass'] for a,b in zip(initial,final)),'new_calls':sum(len(r['rounds'])-1 for r in final),'mean_new_prompt_tokens':sum(sum(q.get('usage',{}).get('prompt_tokens',0) for q in r['rounds'][1:]) for r in final)/len(final),'mean_new_completion_tokens':sum(sum(q.get('usage',{}).get('completion_tokens',0) for q in r['rounds'][1:]) for r in final)/len(final),'final_visible_functional_failure':sum(state(r['rounds'][-1]['visible_result']) not in ['F+S+','F+S-'] for r in final)}
def calculate(sf,ex):
 methods=['functional_only','functional_security'];key=lambda r:tuple(r[k] for k in ['benchmark','task','model','generation_seed']);d={(*key(r),r['method']):r for r in sf};base=sorted([r for r in sf if r['method']==methods[0]],key=key);assert len(base)==200 and len(sf)==400
 strata={}
 for s in ORDER:
  bs=[r for r in base if state(r['rounds'][0]['visible_result'])==s]
  if not bs:continue
  init=[r['initial_hidden'] for r in bs];ars=[[d[(*key(r),m)] for r in bs] for m in methods]
  dif=[int(b['final_hidden']['joint_pass'])-int(a['final_hidden']['joint_pass']) for a,b in zip(*ars)]
  strata[s]={'initials':len(bs),'tasks':len({(r['benchmark'],r['task']) for r in bs}),'by_method':{m:summary(init,rs) for m,rs in zip(methods,ars)},'joint_wins_losses_ties':[dif.count(1),dif.count(-1),dif.count(0)],'joint_delta_pp':100*sum(dif)/len(dif),'by_model':{m:{a:summary([r['initial_hidden'] for r in rs if r['model']==m],[r for r in rs if r['model']==m]) for a,rs in zip(methods,ars)} for m in sorted({r['model'] for r in bs})}}
 groups={}
 for name,wanted in [('security_failed',{'F+S-','F-S-'}),('security_passed',{'F+S+','F-S+'})]:
  bs=[r for r in base if state(r['rounds'][0]['visible_result']) in wanted];ars=[[d[(*key(r),m)] for r in bs] for m in methods];diff=[int(b['final_hidden']['joint_pass'])-int(a['final_hidden']['joint_pass']) for a,b in zip(*ars)]
  groups[name]={'initials':len(bs),'tasks':len({(r['benchmark'],r['task']) for r in bs}),'by_method':{m:summary([r['initial_hidden'] for r in bs],rows) for m,rows in zip(methods,ars)},'joint_wins_losses_ties':[diff.count(1),diff.count(-1),diff.count(0)]}
 # Pre-treatment states only. Later visible results are detection diagnostics, never strata.
 ed={tuple(r[k] for k in ['task','model','generation_seed','method']):r for r in ex};eb=sorted([r for r in ex if r['method']=='B0'],key=lambda r:(r['task'],r['model'],r['generation_seed']));assert len(eb)==100
 estrata={}
 for s in ORDER:
  bs=[r for r in eb if state(r['rounds'][0]['visible_result'])==s]
  if not bs:continue
  finals=[ed[(r['task'],r['model'],r['generation_seed'],'M')] for r in bs]
  estrata[s]={'initials':len(bs),'tasks':len({r['task'] for r in bs}),'M':summary([r['final_hidden'] for r in bs],finals)}
 excluded='Tainted_StackOverflow_SO_cwe094_4.py';rs=[[r for r in sf if r['method']==m and r['task']!=excluded] for m in methods]
 sensitivity={'excluded_task':excluded,'reason':'Security test requires HTTP 500 despite public contract allowing rejection without a status code specification; descriptive whole-task exclusion, original scores retained.','pairs':len(rs[0]),'tasks':19,'rates_pct':{m:{k:100*sum(r['final_hidden'][k] for r in rows)/len(rows) for k in METRICS} for m,rows in zip(methods,rs)}}
 sensitivity['delta_pp']={k:sensitivity['rates_pct'][methods[1]][k]-sensitivity['rates_pct'][methods[0]][k] for k in METRICS}
 return {'analysis_type':'post-hoc descriptive; strata use initial visible outcomes; no confidence intervals or new hypothesis tests','security_feedback':strata,'security_failure_groups':groups,'external_B0_to_M':estrata,'status_code_oracle_sensitivity':sensitivity}
def read_gz(p):
 with gzip.open(p,'rt') as f:return [json.loads(s) for s in f]
def main():
 p=argparse.ArgumentParser();p.add_argument('--artifact-directory',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();root=Path(__file__).resolve().parents[1]
 if a.artifact_directory:
  root=a.artifact_directory;sf=read_gz(root/'data/security-feedback-trajectories.jsonl.gz');ex=read_gz(root/'data/seccodebench-external-trajectories.jsonl.gz')
 else:
  sf=[json.loads(p.read_text()) for p in (root/'artifacts/security-feedback-v1/trajectories').rglob('trajectory.json')];ex=[json.loads(p.read_text()) for p in (root/'artifacts/seccodebench-external-v1/trajectories').rglob('trajectory.json')]
 r=calculate(sf,ex)
 if a.output:a.output.write_text(json.dumps(r,indent=2)+'\n')
 else:
  expected=json.loads((root/'artifacts/reports/feedback-opportunity-v1.json').read_text());assert r==expected;print('PASS: all initial-visible strata, rates, repairs, regressions, costs, model breakdowns and whole-task sensitivity reproduced.')
if __name__=='__main__':main()
