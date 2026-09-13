"""Independently reproduce the security-feedback ablation from portable records."""
import argparse,collections,gzip,hashlib,itertools,json
from pathlib import Path
import numpy as np

def compare(a,b,path='report'):
 if isinstance(a,dict):
  assert set(a)==set(b),(path,set(a)^set(b))
  for k in a:compare(a[k],b[k],path+'.'+k)
 elif isinstance(a,list):
  assert len(a)==len(b),path
  for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+str(i))
 elif isinstance(a,(int,float)) and not isinstance(a,bool):assert np.isclose(a,b,rtol=1e-9,atol=1e-9),(path,a,b)
 else:assert a==b,(path,a,b)
def read(path):
 with gzip.open(path,'rt') as f:return [json.loads(line) for line in f]
def main():
 p=argparse.ArgumentParser();p.add_argument('--artifact-directory',type=Path,default=Path(__file__).resolve().parents[1]);args=p.parse_args();root=args.artifact_directory
 cfg=json.loads((root/'configs/experiments/security_feedback_v1.json').read_text());index=json.loads((root/'data/revision-index.json').read_text())['security-feedback'];path=root/'data'/index['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==index['sha256'];rows=read(path)
 metrics=['functional','security','joint_pass'];methods=cfg['methods'];models=list(cfg['models']);seeds=cfg['seeds'];tasks=sorted({(r['benchmark'],r['task']) for r in rows});bykey={(r['benchmark'],r['task'],r['model'],r['generation_seed'],r['method']):r for r in rows};assert len(rows)==len(bykey)==400 and len(tasks)==20
 expectedkeys={(*t,m,s,a) for t,m,s,a in itertools.product(tasks,models,seeds,methods)};assert set(bykey)==expectedkeys
 bases={(r['_artifact']['benchmark'],r['task'],r['model'],r['generation_seed']):r for r in read(root/'data/primary-trajectories.jsonl.gz') if r['method']=='B0'}
 for r in rows:
  assert r['input_freeze_sha256']==index['source_input_freeze_sha256'] and not r['hidden_feedback_used'];assert len(r['rounds'])==3
  base=bases[r['benchmark'],r['task'],r['model'],r['generation_seed']]
  assert r['initial']['sha256']==base['_artifact']['source_record_sha256']
  assert r['rounds'][0]['response']==base['rounds'][0]['response'] and r['rounds'][0]['messages']==base['rounds'][0]['messages']
  assert r['initial_hidden']=={'functional':base['final_hidden']['functional']['all_passed'],'security':base['final_hidden']['security']['all_passed'],'joint_pass':base['final_hidden']['joint_pass']}
  cs=r['final_hidden']['raw']['cases'];f=[c['passed'] for c in cs if c['marker'] in ['functional','functionality']];s=[c['passed'] for c in cs if c['marker']=='security'];assert (f and s) or r['final_hidden']['raw'].get('collection_errors')
  fv,sv=bool(f) and all(f),bool(s) and all(s)
  assert [r['final_hidden'][k] for k in metrics]==[fv,sv,fv and sv]
  for q in r['rounds'][:2]:
   audit=q['feedback_audit'];assert audit['delivered_tokens']<=600
   if r['method']=='functional_only':assert audit['security'] is None and 'Visible security tests:' not in q['feedback']
  for before,after in zip(r['rounds'][:2],r['rounds'][1:]):assert after['messages']==before['messages']+[{'role':'assistant','content':before['response']},{'role':'user','content':before['feedback']}]
 for t,m,s in itertools.product(tasks,models,seeds):
  a,b=[bykey[*t,m,s,x] for x in methods];assert a['rounds'][0]['feedback_audit']['functional']==b['rounds'][0]['feedback_audit']['functional']
 cube=np.array([[[[[int(bykey[*t,m,s,a]['final_hidden'][k]) for k in metrics] for s in seeds] for m in models] for a in methods] for t in tasks]);values=cube.mean(axis=(2,3));rng=np.random.default_rng(cfg['bootstrap_seed']);samples=rng.integers(0,20,(cfg['bootstrap_replicates'],20));contrasts={}
 for j,k in enumerate(metrics):
  d=values[:,1,j]-values[:,0,j];nz=d[np.abs(d)>1e-12];signs=np.array(list(itertools.product([-1,1],repeat=len(nz))));pv=float(np.mean(abs(signs@nz)>=abs(d.sum())-1e-12));diff=(cube[:,1,:,:,j]-cube[:,0,:,:,j]).flatten().tolist()
  contrasts[k]={'estimate_pp':float(d.mean()*100),'ci95_pp':(np.quantile(d[samples].mean(axis=1),[.025,.975])*100).tolist(),'p_task_sign_flip':pv,'wins':diff.count(1),'losses':diff.count(-1),'ties':diff.count(0),'task_differences_pp':{b+'/'+t:float(v*100) for (b,t),v in zip(tasks,d)}}
 running=0
 for i,k in enumerate(sorted(contrasts,key=lambda k:contrasts[k]['p_task_sign_flip'])):running=max(running,min(1,(3-i)*contrasts[k]['p_task_sign_flip']));contrasts[k]['holm_p']=running
 transitions={};costs={};state=lambda r:('F+' if r['functional'] else 'F-')+('S+' if r['security'] else 'S-')
 for a in methods:
  selected=[r for r in rows if r['method']==a];counts=collections.Counter(state(r['initial_hidden'])+' -> '+state(r['final_hidden']) for r in selected)
  transitions[a]={'states':dict(sorted(counts.items())),'joint_repairs':sum(not r['initial_hidden']['joint_pass'] and r['final_hidden']['joint_pass'] for r in selected),'joint_regressions':sum(r['initial_hidden']['joint_pass'] and not r['final_hidden']['joint_pass'] for r in selected),'functional_regressions':sum(r['initial_hidden']['functional'] and not r['final_hidden']['functional'] for r in selected),'function_preserving_security_repairs':counts['F+S- -> F+S+']}
  costs[a]={'new_calls':400,**{k:float(np.mean([sum(q['usage'].get(k,0) for q in r['rounds'][1:]) for r in selected])) for k in ['prompt_tokens','completion_tokens']},'feedback_tokens':float(np.mean([sum(q['feedback_audit']['delivered_tokens'] for q in r['rounds'][:2]) for r in selected])),'truncated_channels':{c:sum(q['feedback_audit'][c] is not None and q['feedback_audit'][c]['truncated'] for r in selected for q in r['rounds'][:2]) for c in ['functional','security']}}
 base=[r for r in rows if r['method']==methods[0]]
 result={'complete':True,'trajectories':400,'new_calls':800,'task_count':20,'initial_rates':{k:float(np.mean([r['initial_hidden'][k] for r in base])) for k in metrics},'initial_visible_security_failures':sum(any(c['marker']=='security' and not c['passed'] for c in r['rounds'][0]['visible_result']['cases']) for r in base),'methods':{a:dict(zip(metrics,values[:,i].mean(axis=0).tolist())) for i,a in enumerate(methods)},'contrasts':contrasts,'transitions':transitions,'costs':costs,'by_task':{b+'/'+t:{a:dict(zip(metrics,values[i,j].tolist())) for j,a in enumerate(methods)} for i,(b,t) in enumerate(tasks)},'by_model':{m:{a:dict(zip(metrics,cube[:,j,i].mean(axis=(0,1)).tolist())) for j,a in enumerate(methods)} for i,m in enumerate(models)}}
 compare(result,json.loads((root/'artifacts/reports/security-feedback-v1.json').read_text()))
 print('PASS: 400 branches, 200 original shared initials, raw-case scores, message history, functional channel identity, all endpoint statistics, task/model results, transition counts and token costs.')
if __name__=='__main__':main()
