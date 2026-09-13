#!/usr/bin/env python3
"""Independently reproduce revision contrasts from portable trajectory exports."""
import gzip,json,itertools,hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def read(name):
 with gzip.open(ROOT/'data'/name,'rt') as f:return [json.loads(line) for line in f]

def check(actual,expected,path='result'):
 if isinstance(expected,dict):
  for k,v in expected.items():check(actual[k],v,path+'.'+k)
 elif isinstance(expected,list):
  assert len(actual)==len(expected),path
  for i,v in enumerate(expected):check(actual[i],v,path+f'[{i}]')
 elif isinstance(expected,(int,float)):
  assert abs(actual-expected)<1e-8,(path,actual,expected)
 else:assert actual==expected,(path,actual,expected)

def contrasts(values,tasks,methods,spec,rows):
 rng=np.random.default_rng(20260910);idx=rng.integers(0,len(tasks),size=(10000,len(tasks)));out={}
 for name,weights in spec:
  d=sum(w*values[:,methods.index(m),2] for m,w in weights.items());ci=100*np.quantile(d[idx].mean(axis=1),[.025,.975]);nz=d[abs(d)>1e-12];success=0
  for start in range(0,2**len(nz),32768):
   ids=np.arange(start,min(start+32768,2**len(nz)),dtype=np.uint64);signs=2*((ids[:,None]>>np.arange(len(nz),dtype=np.uint64))&1).astype(float)-1
   success+=int(np.sum(abs(signs@nz)>=abs(d.sum())-1e-12))
  row={'estimate_pp':100*float(d.mean()),'ci95_pp':ci.tolist(),'p_task_sign_randomization':success/2**len(nz)}
  if len(weights)==2:
   a=next(m for m,w in weights.items() if w==1);b=next(m for m,w in weights.items() if w==-1)
   diff=[int(r['final_hidden']['joint_pass'])-int(rows[(*k[:-1],b)]['final_hidden']['joint_pass']) for k,r in rows.items() if k[-1]==a]
   row.update(wins=diff.count(1),losses=diff.count(-1),ties=diff.count(0))
  out[name]=row
 ordered=sorted(out,key=lambda n:out[n]['p_task_sign_randomization']);running=0
 for i,n in enumerate(ordered):running=max(running,min(1,(len(ordered)-i)*out[n]['p_task_sign_randomization']));out[n]['holm_adjusted_p']=running
 return out

def main():
 index=json.loads((ROOT/'data/revision-index.json').read_text())
 for group in ('feedback-mechanism','seccodebench-external'):
  assert hashlib.sha256((ROOT/'data'/index[group]['file']).read_bytes()).hexdigest()==index[group]['sha256']
  exported=read(index[group]['file']);expected=json.loads((ROOT/'artifacts/reports'/index[group]['report']).read_text())
  assert len(exported)==index[group]['records']
  if group=='feedback-mechanism':
   rows={(r['benchmark'],r['task'],r['model'],r['generation_seed'],r['method']):r for r in exported};tasks=sorted({k[:2] for k in rows});methods=['blind','binary','fixed_raw','priority_raw','fixed_structured','priority_structured']
   assert all(len(r['rounds'])==3 and not r['hidden_feedback_used'] for r in exported)
   for k,r in rows.items():
    assert r['rounds'][0]['response']==rows[(*k[:-1],'blind')]['rounds'][0]['response']
    assert r['rounds'][0]['messages']==rows[(*k[:-1],'blind')]['rounds'][0]['messages']
   specs=[('binary_minus_blind',{'binary':1,'blind':-1}),('details_minus_binary',{'fixed_raw':1,'binary':-1}),('priority_minus_fixed_raw',{'priority_raw':1,'fixed_raw':-1}),('structured_minus_raw_fixed',{'fixed_structured':1,'fixed_raw':-1}),('selection_rendering_interaction',{'priority_structured':1,'priority_raw':-1,'fixed_structured':-1,'fixed_raw':1})]
   selector=lambda k:k[:2]
  else:
   rows={(r['task'],r['model'],r['generation_seed'],r['method']):r for r in exported};methods=['B0','B3','M','B6'];tasks=index[group]['tasks']
   specs=[(a+'-'+b,{a:1,b:-1}) for a,b in [('B3','B0'),('M','B0'),('B6','B3')]];selector=lambda k:k[0]
   for k,r in rows.items():
    assert not r['hidden_feedback_used']
    if k[-1] in ('M','B6'):
     base=rows[(*k[:-1],'B0' if k[-1]=='M' else 'B3')]
     assert r['rounds'][0]['response']==base['rounds'][0]['response']
  assert len(rows)==len(exported)
  values=np.array([[[np.mean([r['final_hidden'][metric] for k,r in rows.items() if selector(k)==task and k[-1]==m]) for metric in ('functional','security','joint_pass')] for m in methods] for task in tasks])
  actual=contrasts(values,tasks,methods,specs,rows);check(actual,expected['contrasts'])
  labels=('functional','security','joint') if group=='feedback-mechanism' else ('functional','security','joint_pass')
  averages={m:dict(zip(labels,values[:,i,:].mean(axis=0).tolist())) for i,m in enumerate(methods)}
  check(averages,expected['methods'])
  if group=='feedback-mechanism':
   extra=contrasts(values,tasks,methods,[('fixed_raw-blind',{'fixed_raw':1,'blind':-1}),('fixed_structured-blind',{'fixed_structured':1,'blind':-1})],rows)
   frozen_extra=json.loads((ROOT/'artifacts/reports/feedback-vs-blind-posthoc-v1.json').read_text())['contrasts']
   for k,v in frozen_extra.items():
    v['p_task_sign_randomization']=v.pop('p_task_sign_flip')
    check(extra[k],v)
   base={(r['_artifact']['benchmark'],r['task'],r['model'],r['generation_seed']):r for r in read('primary-trajectories.jsonl.gz') if r['method']=='B0'}
   for method in methods:
    selected=[r for k,r in rows.items() if k[-1]==method];events=[q for r in selected for q in r['rounds'][:-1]]
    regressions={metric:0 for metric in ('functional','security','joint')}
    for r in selected:
     before=base[(r['benchmark'],r['task'],r['model'],r['generation_seed'])]['final_hidden']
     for metric in ('functional','security'):regressions[metric]+=int(before[metric]['all_passed'] and not r['final_hidden'][metric])
     regressions['joint']+=int(before['joint_pass'] and not r['final_hidden']['joint_pass'])
    actual_diag={'regressions':regressions,'feedback_events':len(events),'truncated_events':sum(q['feedback_audit']['truncated'] for q in events),'selection_set_opportunities':sum(set(q['feedback_audit']['fixed_case_ids'])!=set(q['feedback_audit']['priority_case_ids']) for q in events),'selection_order_opportunities':sum(q['feedback_audit']['fixed_case_ids']!=q['feedback_audit']['priority_case_ids'] for q in events),'revision_prompt_tokens':sum(q['usage'].get('prompt_tokens',0) for r in selected for q in r['rounds'][1:]),'revision_completion_tokens':sum(q['usage'].get('completion_tokens',0) for r in selected for q in r['rounds'][1:]),'revision_model_seconds':sum(q['model_wall_seconds'] for r in selected for q in r['rounds'][1:])}
    check(actual_diag,expected['diagnostics'][method])
  else:
   costs={m:{'logical_calls':sum(len(r['rounds']) for k,r in rows.items() if k[-1]==m),'prompt_tokens':sum(q['usage'].get('prompt_tokens',0) for k,r in rows.items() if k[-1]==m for q in r['rounds']),'completion_tokens':sum(q['usage'].get('completion_tokens',0) for k,r in rows.items() if k[-1]==m for q in r['rounds'])} for m in methods}
   check(costs,expected['costs'])
   assert sum(not q['generation_reused'] for r in rows.values() for q in r['rounds'])==expected['new_generation_calls']
   check({task:{m:dict(zip(('functional','security','joint_pass'),values[i,j,:].tolist())) for j,m in enumerate(methods)} for i,task in enumerate(tasks)},expected['by_task'])
  print(f"OK: {group}: {len(rows)} records, {len(tasks)} task clusters, estimates, bootstrap intervals and Holm tests reproduced")
if __name__=='__main__':main()
