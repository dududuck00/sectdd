"""Frozen complete-grid analysis of matched-information representation."""
import hashlib,itertools,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def main():
 cfg=json.loads((ROOT/'configs/experiments/representation_v1.json').read_text());output=ROOT/cfg['output'];freeze=json.loads((output/'input-freeze.json').read_text());digest=hashlib.sha256((output/'input-freeze.json').read_bytes()).hexdigest()
 tasks=sorted({p['task'] for p in freeze['prompts']});methods=cfg['methods'];metrics=['functional','security','joint_pass'];rows={}
 for t,m,s,a in itertools.product(tasks,cfg['models'],cfg['seeds'],methods):
  path=output/'trajectories'/m/a/t.replace('/','__')/f'seed_{s}/trajectory.json'
  if path.exists():
   r=json.loads(path.read_text());assert r['input_freeze_sha256']==digest and not r['hidden_feedback_used'];assert (r['task'],r['model'],r['generation_seed'],r['method'])==(t,m,s,a);rows[(t,m,s,a)]=r
 if len(rows)!=480:print(f'Incomplete {len(rows)}/480; no inferential result');return
 values=np.array([[[np.mean([r['final_hidden'][metric] for k,r in rows.items() if k[0]==t and k[3]==a]) for metric in metrics] for a in methods] for t in tasks])
 rng=np.random.default_rng(cfg['bootstrap_seed']);idx=rng.integers(0,len(tasks),size=(cfg['bootstrap_replicates'],len(tasks)));contrasts={}
 for name,weights in [('code-prose_functional',[1,-1,0,0]),('code-prose_both',[0,0,1,-1]),('interaction',[-1,1,1,-1])]:
  d=values[:,:,2]@np.array(weights);nz=d[np.abs(d)>1e-12];p=np.mean([abs(np.dot(sign,nz))>=abs(d.sum())-1e-12 for sign in itertools.product([-1,1],repeat=len(nz))]);boot=d[idx].mean(axis=1)
  contrasts[name]={'estimate_pp':100*float(d.mean()),'ci95_pp':(100*np.quantile(boot,[.025,.975])).tolist(),'p_task_sign_flip':float(p),'task_differences_pp':dict(zip(tasks,(100*d).tolist()))}
 running=0
 for i,name in enumerate(sorted(contrasts,key=lambda n:contrasts[n]['p_task_sign_flip'])):
  running=max(running,min(1,(3-i)*contrasts[name]['p_task_sign_flip']));contrasts[name]['holm_p']=running
 result={'complete':True,'trajectories':len(rows),'task_count':len(tasks),'methods':{a:dict(zip(metrics,values[:,i,:].mean(axis=0).tolist())) for i,a in enumerate(methods)},'contrasts':contrasts,'by_task':{t:{a:dict(zip(metrics,values[i,j,:].tolist())) for j,a in enumerate(methods)} for i,t in enumerate(tasks)},'by_model':{m:{a:{metric:float(np.mean([r['final_hidden'][metric] for k,r in rows.items() if k[1]==m and k[3]==a])) for metric in metrics} for a in methods} for m in cfg['models']},'costs':{a:{k:float(np.mean([r['rounds'][0]['usage'].get(k,0) for key,r in rows.items() if key[3]==a])) for k in ['prompt_tokens','completion_tokens']} for a in methods}}
 path=ROOT/'artifacts/reports/representation-v1.json';path.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['contrasts'],indent=2))
if __name__=='__main__':main()
