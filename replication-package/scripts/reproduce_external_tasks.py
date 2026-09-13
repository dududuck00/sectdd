"""Descriptive task-level decomposition; never pools seeds as independent tasks."""
import argparse,collections,csv,gzip,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--artifact-directory',type=Path);args=parser.parse_args()
 root=args.artifact_directory or ROOT
 cfg=json.loads((root/'configs/experiments/seccodebench_external_v1.json').read_text())
 rows={}
 if args.artifact_directory:
  with gzip.open(root/'data/seccodebench-external-trajectories.jsonl.gz','rt') as f: records=[json.loads(line) for line in f]
 else: records=[json.loads(p.read_text()) for p in (ROOT/'artifacts/seccodebench-external-v1/trajectories').rglob('trajectory.json')]
 for r in records:rows[(r['task'],r['model'],r['generation_seed'],r['method'])]=r
 assert len(rows)==400
 out=[]; detail=[]
 state=lambda r: ('F+' if r['final_hidden']['functional'] else 'F-')+('S+' if r['final_hidden']['security'] else 'S-')
 for task in [t['task'] for t in cfg['tasks']]:
  for a,b in [('B3','B0'),('M','B0'),('B6','B3')]:
   pairs=[(rows[(task,m,s,a)],rows[(task,m,s,b)]) for m in cfg['models'] for s in cfg['seeds']]
   transitions=collections.Counter((state(y),state(x)) for x,y in pairs)
   row={'task':task,'contrast':a+'-'+b,'n':len(pairs)}
   for metric in ['functional','security','joint_pass']:
    row[metric+'_delta_pp']=10*sum(int(x['final_hidden'][metric])-int(y['final_hidden'][metric]) for x,y in pairs)
   row.update({'joint_repairs':sum(x['final_hidden']['joint_pass'] and not y['final_hidden']['joint_pass'] for x,y in pairs),'joint_regressions':sum(y['final_hidden']['joint_pass'] and not x['final_hidden']['joint_pass'] for x,y in pairs),'function_regressions':sum(y['final_hidden']['functional'] and not x['final_hidden']['functional'] for x,y in pairs)})
   for origin,name in [('F+S-','security_only_repairs'),('F-S+','function_only_repairs'),('F-S-','both_repairs')]:row[name]=transitions[(origin,'F+S+')]
   row['transitions']={k+' -> '+v:n for (k,v),n in sorted(transitions.items())}
   out.append(row)
   for x,y in pairs:
    detail.append({'task':task,'model':x['model'],'seed':x['generation_seed'],'contrast':a+'-'+b,'before':state(y),'after':state(x)})
 result={'analysis':'post-hoc descriptive decomposition; 10 model-seed pairs per task; no new significance tests','rows':out,'pairs':detail}
 if args.artifact_directory:
  expected=json.loads((root/'artifacts/reports/external-task-analysis-v1.json').read_text());assert result==expected;print('PASS: all 300 paired transitions and 30 task contrasts reproduce');return
 target=ROOT/'artifacts/reports/external-task-analysis-v1.json';target.write_text(json.dumps(result,indent=2)+'\n')
 with target.with_suffix('.csv').open('w') as f:
  fields=[k for k in out[0] if k!='transitions'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in out)
 print(json.dumps([r for r in out if r['contrast']=='M-B0'],indent=2))
if __name__=='__main__':main()
