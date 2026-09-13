"""Recompute the completed representation study from the portable response records."""
import argparse,gzip,hashlib,itertools,json
from pathlib import Path
import numpy as np

def compare(a,b,path='report'):
 if isinstance(a,dict):
  assert set(a)==set(b),(path,set(a)^set(b))
  for k in a:compare(a[k],b[k],path+'.'+k)
 elif isinstance(a,list):
  assert len(a)==len(b),path
  for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+f'[{i}]')
 elif isinstance(a,(int,float)) and not isinstance(a,bool):assert np.isclose(a,b,atol=1e-9,rtol=1e-9),(path,a,b)
 else:assert a==b,(path,a,b)

def main():
 p=argparse.ArgumentParser();p.add_argument('--artifact-directory',type=Path,default=Path(__file__).resolve().parents[1]);args=p.parse_args();root=args.artifact_directory
 cfg=json.loads((root/'configs/experiments/representation_v1.json').read_text());index=json.loads((root/'data/revision-index.json').read_text())['representation'];fp=root/'data'/index['file'];assert hashlib.sha256(fp.read_bytes()).hexdigest()==index['sha256']
 with gzip.open(fp,'rt') as f:rows=[json.loads(line) for line in f]
 assert len(rows)==480;tasks=sorted({r['task'] for r in rows});methods=cfg['methods'];models=list(cfg['models']);seeds=cfg['seeds'];metrics=['functional','security','joint_pass'];assert len(tasks)==12
 keys={(r['task'],r['model'],r['generation_seed'],r['method']) for r in rows};assert keys==set(itertools.product(tasks,models,seeds,methods))
 frozen=json.loads((root/'revision-provenance/representation-v1/input-freeze.json').read_text());prompts={(p['task'],p['method']):p['messages'] for p in frozen['prompts']}
 for r in rows:
  assert not r['hidden_feedback_used'] and len(r['rounds'])==1
  assert r['input_freeze_sha256']==index['source_input_freeze_sha256']
  assert r['rounds'][0]['messages']==prompts[r['task'],r['method']]
  cases=r['final_hidden']['raw']['cases'];f=[c['passed'] for c in cases if c['marker'] in ['functional','functionality']];s=[c['passed'] for c in cases if c['marker']=='security'];assert f and s
  assert [r['final_hidden'][k] for k in metrics]==[all(f),all(s),all(f) and all(s)]
 # Construct task means independently from the complete key-addressed grid.
 by_key={(r['task'],r['model'],r['generation_seed'],r['method']):r for r in rows}
 cube=np.array([[[[[int(by_key[t,m,s,a]['final_hidden'][k]) for k in metrics] for s in seeds] for m in models] for a in methods] for t in tasks])
 values=cube.mean(axis=(2,3));rng=np.random.default_rng(cfg['bootstrap_seed']);samples=rng.integers(0,12,(cfg['bootstrap_replicates'],12));contrasts={}
 for name,d in [('code-prose_functional',values[:,0,2]-values[:,1,2]),('code-prose_both',values[:,2,2]-values[:,3,2]),('interaction',(values[:,2,2]-values[:,3,2])-(values[:,0,2]-values[:,1,2]))]:
  nz=d[np.abs(d)>1e-12];signs=np.array(list(itertools.product([-1,1],repeat=len(nz))));pv=float(np.mean(np.abs(signs@nz)>=abs(d.sum())-1e-12));ci=np.quantile(d[samples].mean(axis=1),[.025,.975])*100
  contrasts[name]={'estimate_pp':float(d.mean()*100),'ci95_pp':ci.tolist(),'p_task_sign_flip':pv,'task_differences_pp':dict(zip(tasks,(d*100).tolist()))}
 running=0
 for i,n in enumerate(sorted(contrasts,key=lambda n:contrasts[n]['p_task_sign_flip'])):
  running=max(running,min(1,(3-i)*contrasts[n]['p_task_sign_flip']));contrasts[n]['holm_p']=running
 result={'complete':True,'trajectories':480,'task_count':12,'methods':{a:dict(zip(metrics,values[:,i].mean(axis=0).tolist())) for i,a in enumerate(methods)},'contrasts':contrasts,'by_task':{t:{a:dict(zip(metrics,values[i,j].tolist())) for j,a in enumerate(methods)} for i,t in enumerate(tasks)},'by_model':{m:{a:dict(zip(metrics,cube[:,j,i].mean(axis=(0,1)).tolist())) for j,a in enumerate(methods)} for i,m in enumerate(models)},'costs':{a:{k:float(np.mean([r['rounds'][0]['usage'].get(k,0) for r in rows if r['method']==a])) for k in ['prompt_tokens','completion_tokens']} for a in methods}}
 expected=json.loads((root/'artifacts/reports/representation-v1.json').read_text());compare(result,expected)
 print('PASS: 480 complete cells, prompt identity, raw-case scores, rates, task/model results, tokens, all three confidence intervals and Holm tests.')
if __name__=='__main__':main()
