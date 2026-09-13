#!/usr/bin/env python3
"""Exploratory direct contrasts, added after inspecting the complete planned analysis."""
import itertools,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def main():
 rows=[json.loads(p.read_text()) for p in (ROOT/'artifacts/feedback-mechanism-v1').rglob('trajectory.json')];assert len(rows)==1200
 tasks=sorted({(r['benchmark'],r['task']) for r in rows});rng=np.random.default_rng(20260910);idx=rng.integers(0,len(tasks),size=(10000,len(tasks)))
 out={'timing':'post-hoc after complete planned outcome inspection; separate exploratory family','contrasts':{}}
 for m in ('fixed_raw','fixed_structured'):
  d=np.array([np.mean([r['final_hidden']['joint_pass'] for r in rows if (r['benchmark'],r['task'])==t and r['method']==m])-np.mean([r['final_hidden']['joint_pass'] for r in rows if (r['benchmark'],r['task'])==t and r['method']=='blind']) for t in tasks]);nz=d[abs(d)>1e-12]
  p=np.mean([abs(np.dot(s,nz))>=abs(d.sum())-1e-12 for s in itertools.product([-1,1],repeat=len(nz))])
  out['contrasts'][m+'-blind']={'estimate_pp':100*float(d.mean()),'ci95_pp':(100*np.quantile(d[idx].mean(axis=1),[.025,.975])).tolist(),'p_task_sign_flip':float(p)}
 running=0
 for i,k in enumerate(sorted(out['contrasts'],key=lambda k:out['contrasts'][k]['p_task_sign_flip'])):
  running=max(running,min(1,(2-i)*out['contrasts'][k]['p_task_sign_flip']));out['contrasts'][k]['holm_adjusted_p']=running
 (ROOT/'artifacts/reports/feedback-vs-blind-posthoc-v1.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':main()
