"""Frozen task-cluster analysis of adding security feedback."""
import collections,hashlib,itertools,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
METRICS=['functional','security','joint_pass']
def summarize(rows,cfg):
 methods=cfg['methods'];tasks=sorted({(r['benchmark'],r['task']) for r in rows});bykey={(r['benchmark'],r['task'],r['model'],r['generation_seed'],r['method']):r for r in rows}
 assert len(rows)==len(bykey)==400 and len(tasks)==20
 assert set(bykey)=={(*t,m,s,a) for t,m,s,a in itertools.product(tasks,cfg['models'],cfg['seeds'],methods)}
 for t,m,s in itertools.product(tasks,cfg['models'],cfg['seeds']):
  a,b=[bykey[*t,m,s,c] for c in methods]
  assert a['rounds'][0]['messages']==b['rounds'][0]['messages'] and a['rounds'][0]['response']==b['rounds'][0]['response'] and a['initial_hidden']==b['initial_hidden']
  assert a['rounds'][0]['feedback_audit']['functional']==b['rounds'][0]['feedback_audit']['functional']
  for r in [a,b]:
   assert not r['hidden_feedback_used'] and len(r['rounds'])==3
   for q in r['rounds'][:2]:
    assert q['feedback_audit']['delivered_tokens']<=600
    if r['method']=='functional_only':assert q['feedback_audit']['security'] is None
 values=np.array([[[np.mean([bykey[*t,m,s,a]['final_hidden'][k] for m,s in itertools.product(cfg['models'],cfg['seeds'])]) for k in METRICS] for a in methods] for t in tasks])
 rng=np.random.default_rng(cfg['bootstrap_seed']);idx=rng.integers(0,20,(cfg['bootstrap_replicates'],20));contrasts={}
 for i,k in enumerate(METRICS):
  d=values[:,1,i]-values[:,0,i];nz=d[np.abs(d)>1e-12];pv=np.mean([abs(np.dot(sign,nz))>=abs(d.sum())-1e-12 for sign in itertools.product([-1,1],repeat=len(nz))]);diff=[int(bykey[*t,m,s,methods[1]]['final_hidden'][k])-int(bykey[*t,m,s,methods[0]]['final_hidden'][k]) for t,m,s in itertools.product(tasks,cfg['models'],cfg['seeds'])]
  contrasts[k]={'estimate_pp':float(d.mean()*100),'ci95_pp':(100*np.quantile(d[idx].mean(axis=1),[.025,.975])).tolist(),'p_task_sign_flip':float(pv),'wins':diff.count(1),'losses':diff.count(-1),'ties':diff.count(0),'task_differences_pp':{b+'/'+t:float(x*100) for (b,t),x in zip(tasks,d)}}
 running=0
 for i,k in enumerate(sorted(contrasts,key=lambda k:contrasts[k]['p_task_sign_flip'])):running=max(running,min(1,(3-i)*contrasts[k]['p_task_sign_flip']));contrasts[k]['holm_p']=running
 state=lambda r:('F+' if r['functional'] else 'F-')+('S+' if r['security'] else 'S-')
 transitions={};costs={}
 for a in methods:
  rs=[r for r in rows if r['method']==a];counts=collections.Counter(state(r['initial_hidden'])+' -> '+state(r['final_hidden']) for r in rs)
  transitions[a]={'states':dict(sorted(counts.items())),'joint_repairs':sum(not r['initial_hidden']['joint_pass'] and r['final_hidden']['joint_pass'] for r in rs),'joint_regressions':sum(r['initial_hidden']['joint_pass'] and not r['final_hidden']['joint_pass'] for r in rs),'functional_regressions':sum(r['initial_hidden']['functional'] and not r['final_hidden']['functional'] for r in rs),'function_preserving_security_repairs':counts['F+S- -> F+S+']}
  costs[a]={'new_calls':len(rs)*2,**{k:float(np.mean([sum(q['usage'].get(k,0) for q in r['rounds'][1:]) for r in rs])) for k in ['prompt_tokens','completion_tokens']},'feedback_tokens':float(np.mean([sum(q['feedback_audit']['delivered_tokens'] for q in r['rounds'][:2]) for r in rs])),'truncated_channels':{c:sum(q['feedback_audit'][c] is not None and q['feedback_audit'][c]['truncated'] for r in rs for q in r['rounds'][:2]) for c in ['functional','security']}}
 base=[r for r in rows if r['method']==methods[0]]
 return {'complete':True,'trajectories':400,'new_calls':800,'task_count':20,'initial_rates':{k:float(np.mean([r['initial_hidden'][k] for r in base])) for k in METRICS},'initial_visible_security_failures':sum(any(c['marker']=='security' and not c['passed'] for c in r['rounds'][0]['visible_result']['cases']) for r in base),'methods':{a:dict(zip(METRICS,values[:,j].mean(axis=0).tolist())) for j,a in enumerate(methods)},'contrasts':contrasts,'transitions':transitions,'costs':costs,'by_task':{b+'/'+t:{a:dict(zip(METRICS,values[i,j].tolist())) for j,a in enumerate(methods)} for i,(b,t) in enumerate(tasks)},'by_model':{m:{a:{k:float(np.mean([r['final_hidden'][k] for r in rows if r['model']==m and r['method']==a])) for k in METRICS} for a in methods} for m in cfg['models']}}
def main():
 cfg=json.loads((ROOT/'configs/experiments/security_feedback_v1.json').read_text());output=ROOT/cfg['output'];digest=hashlib.sha256((output/'input-freeze.json').read_bytes()).hexdigest();rows=[json.loads(p.read_text()) for p in (output/'trajectories').rglob('trajectory.json')]
 if len(rows)!=400:print(f'Incomplete {len(rows)}/400; no inference');return
 assert all(r['input_freeze_sha256']==digest for r in rows);result=summarize(rows,cfg);(ROOT/'artifacts/reports/security-feedback-v1.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['methods','contrasts','transitions']},indent=2))
if __name__=='__main__':main()
