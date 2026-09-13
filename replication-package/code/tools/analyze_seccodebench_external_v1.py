#!/usr/bin/env python3
import json,itertools,hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def main():
 config=json.loads((ROOT/'configs/experiments/seccodebench_external_v1.json').read_text());output=ROOT/'artifacts/seccodebench-external-v1';rows={};missing=[]
 freeze=hashlib.sha256((output/'input-freeze.json').read_bytes()).hexdigest()
 for task,model,seed,method in itertools.product([t['task'] for t in config['tasks']],config['models'],config['seeds'],config['methods']):
  p=output/'trajectories'/model/method/task/f'seed_{seed}/trajectory.json';key=(task,model,seed,method)
  if not p.exists():missing.append(key);continue
  r=json.loads(p.read_text());assert r['input_freeze_sha256']==freeze and not r['hidden_feedback_used'];rows[key]=r
 expected=len(config['tasks'])*len(config['models'])*len(config['seeds'])*len(config['methods'])
 if missing:
  (output/'progress-summary.json').write_text(json.dumps({'completed':len(rows),'expected':expected,'missing':missing},indent=2)+'\n');print(f'Incomplete: {len(rows)}/{expected}; no inferential report');return
 for key,r in rows.items():
  if key[-1] in ('M','B6'):
   base=rows[(*key[:-1],'B0' if key[-1]=='M' else 'B3')]
   assert r['rounds'][0]['response']==base['rounds'][0]['response'] and r['rounds'][0]['messages']==base['rounds'][0]['messages']
 tasks=[t['task'] for t in config['tasks']];methods=config['methods'];metrics=['functional','security','joint_pass']
 values=np.array([[[np.mean([r['final_hidden'][metric] for k,r in rows.items() if k[0]==task and k[-1]==method]) for metric in metrics] for method in methods] for task in tasks])
 rng=np.random.default_rng(20260910);idx=rng.integers(0,len(tasks),size=(10000,len(tasks)));contrasts={}
 for a,b in [('B3','B0'),('M','B0'),('B6','B3')]:
  d=values[:,methods.index(a),2]-values[:,methods.index(b),2];boot=d[idx].mean(axis=1);nz=d[np.abs(d)>1e-12]
  p=np.mean([abs(np.dot(s,nz))>=abs(d.sum())-1e-12 for s in itertools.product([-1,1],repeat=len(nz))])
  diff=[int(r['final_hidden']['joint_pass'])-int(rows[(*k[:-1],b)]['final_hidden']['joint_pass']) for k,r in rows.items() if k[-1]==a]
  contrasts[a+'-'+b]={'estimate_pp':100*float(d.mean()),'ci95_pp':(100*np.quantile(boot,[.025,.975])).tolist(),'p_task_sign_randomization':float(p),'wins':diff.count(1),'losses':diff.count(-1),'ties':diff.count(0)}
 ordered=sorted(contrasts,key=lambda x:contrasts[x]['p_task_sign_randomization']);running=0
 for i,k in enumerate(ordered):running=max(running,min(1,(len(ordered)-i)*contrasts[k]['p_task_sign_randomization']));contrasts[k]['holm_adjusted_p']=running
 result={'complete':True,'trajectory_count':len(rows),'task_count':len(tasks),'model_count':len(config['models']),'seeds':config['seeds'],'inference':'10000 task-cluster bootstrap; seed 20260910; exact task sign randomization; Holm across three joint contrasts','methods':{method:dict(zip(metrics,values[:,i,:].mean(axis=0).tolist())) for i,method in enumerate(methods)},'contrasts':contrasts,'excluded':config['excluded'],'new_generation_calls':sum(not q['generation_reused'] for r in rows.values() for q in r['rounds']),'by_task':{task:{m:dict(zip(metrics,values[i,j,:].tolist())) for j,m in enumerate(methods)} for i,task in enumerate(tasks)}}
 result['costs']={m:{'logical_calls':sum(len(r['rounds']) for k,r in rows.items() if k[-1]==m),'prompt_tokens':sum(q['usage'].get('prompt_tokens',0) for k,r in rows.items() if k[-1]==m for q in r['rounds']),'completion_tokens':sum(q['usage'].get('completion_tokens',0) for k,r in rows.items() if k[-1]==m for q in r['rounds'])} for m in methods}
 (ROOT/'artifacts/reports/seccodebench-external-v1.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['contrasts'],indent=2))
if __name__=='__main__':main()
