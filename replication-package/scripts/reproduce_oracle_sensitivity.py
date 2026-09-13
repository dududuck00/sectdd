#!/usr/bin/env python3
"""Recompute the post-hoc oracle exclusion from portable original records."""
import gzip,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 with gzip.open(ROOT/'data/legacy-trajectories.jsonl.gz','rt') as f:records=[json.loads(x) for x in f]
 rows={(r['_artifact']['benchmark'],r['model'],r['task'],r['generation_seed'],r['method']):r for r in records}
 expected=json.loads((ROOT/'artifacts/reports/arxiv-oracle-exclusion-sensitivity-v1.json').read_text())
 for mode in ('with_task','without_task'):
  counts=dict.fromkeys(['pairs','m_wins','raw_wins','m_repairs','raw_repairs','m_joint_regressions','raw_joint_regressions'],0)
  for k,r in rows.items():
   if k[-1]!='M' or (mode=='without_task' and k[2]==expected['excluded_task']):continue
   b=rows[(*k[:-1],'B0')];raw=rows[(*k[:-1],'B4')]
   j0,jm,jr=[bool(q['final_hidden']['joint_pass']) for q in (b,r,raw)]
   for name,value in zip(counts,[1,jm and not jr,jr and not jm,not j0 and jm,not j0 and jr,j0 and not jm,j0 and not jr]):counts[name]+=int(value)
  assert counts==expected['summary'][mode],(mode,counts)
  print('OK:',mode,counts)
if __name__=='__main__':main()
