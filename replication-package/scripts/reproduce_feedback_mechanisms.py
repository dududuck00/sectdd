"""Reproduce complete case selection and validate interpretation evidence against archived records."""
import argparse,collections,gzip,hashlib,json
from pathlib import Path

def load_gz(p):
 with gzip.open(p,'rt') as f:return [json.loads(s) for s in f]
def functional_pass(raw):
 f=[c['passed'] for c in raw['cases'] if c['marker'] in ['functional','functionality']];return bool(f) and all(f)
def main():
 p=argparse.ArgumentParser();p.add_argument('--artifact-directory',type=Path);p.add_argument('--output',type=Path);args=p.parse_args();root=args.artifact_directory or Path(__file__).resolve().parents[1]
 if args.artifact_directory:
  sf=load_gz(root/'data/security-feedback-trajectories.jsonl.gz');ex=load_gz(root/'data/seccodebench-external-trajectories.jsonl.gz');ledger=json.loads((root/'artifacts/reports/feedback-case-ledger.json').read_text())
 else:
  def read(base):
   rows=[]
   for p in (root/base).rglob('trajectory.json'):
    r=json.loads(p.read_text());r['_artifact']={'source_record_sha256':hashlib.sha256(p.read_bytes()).hexdigest()};rows.append(r)
   return rows
  sf=read('artifacts/security-feedback-v1/trajectories');ex=read('artifacts/seccodebench-external-v1/trajectories');ledger=json.loads((root/'artifacts/feedback-mechanism-analysis/case-ledger.json').read_text())
 sk=lambda r:tuple(r[k] for k in ['benchmark','task','model','generation_seed']);ek=lambda r:tuple(r[k] for k in ['task','model','generation_seed'])
 sd={(*sk(r),r['method']):r for r in sf};ed={(*ek(r),r['method']):r for r in ex};selected={}
 for k,a in sd.items():
  if k[-1]!='functional_only':continue
  b=sd[(*k[:-1],'functional_security')]
  if a['final_hidden']['joint_pass']!=b['final_hidden']['joint_pass'] or b['initial_hidden']['functional'] and not b['final_hidden']['functional']:selected[('security-feedback',*k[:-1])]=(a,b)
 for k,b in ed.items():
  if k[-1]!='M':continue
  a=ed[(*k[:-1],'B0')]
  if a['final_hidden']['functional'] and not b['final_hidden']['functional']:selected[('external',*k[:-1])]=(a,b)
 assert len(selected)==28 and len(ledger['cases'])==28
 checked={};categories=collections.defaultdict(collections.Counter);detections=collections.defaultdict(collections.Counter)
 for item in ledger['cases']:
  k=item['key'];key=(item['cohort'],*([k['benchmark']] if item['cohort']=='security-feedback' else []),k['task'],k['model'],k['generation_seed']);a,b=selected.pop(key)
  assert item['source_sha256']==[r['_artifact']['source_record_sha256'] for r in [a,b]]
  assert a['rounds'][0]['response']==b['rounds'][0]['response'];assert item['final_response_evidence'] in b['rounds'][-1]['response']
  combined=[a['final_hidden'],b['final_hidden'],*[q['visible_result'] for q in b['rounds']]];assert item['failure_evidence'] in str(combined) or item['failure_evidence'] in json.dumps(combined,ensure_ascii=False)
  if item['category']=='oracle_status_alignment':
   aa=a['rounds'][-1]['response'].splitlines();bb=b['rounds'][-1]['response'].splitlines();assert len(aa)==len(bb)
   changes=[(x,y) for x,y in zip(aa,bb) if x!=y];assert len(changes)==1 and changes[0][0].replace(', 400',', 500')==changes[0][1]
  if item['category']=='missing_import':assert 'from markupsafe import escape' not in b['rounds'][-1]['response'] and 'def escape' not in b['rounds'][-1]['response']
  categories[item['cohort']][item['category']]+=1
  visible_bad=not functional_pass(b['rounds'][-1]['visible_result'])
  if item['selection']['functional_regression']:detections[item['cohort']]['visible_functional_failure' if visible_bad else 'visible_functional_pass']+=1
  checked[item['id']]={'category':item['category'],'final_visible_functional_pass':not visible_bad,'initial_hidden':b.get('initial_hidden',a['final_hidden']) if item['cohort']=='security-feedback' else {k:a['final_hidden'][k] for k in ['functional','security','joint_pass']},'final_hidden':{k:b['final_hidden'][k] for k in ['functional','security','joint_pass']},'rounds':len(b['rounds'])-1}
 assert not selected
 report={'complete':True,'selected_cases':28,'security_feedback_discordant_pairs':10,'security_feedback_unique_cases':12,'external_functional_regressions':16,'categories':{k:dict(v) for k,v in categories.items()},'functional_regression_detection':{k:dict(v) for k,v in detections.items()},'cases':checked,'interpretation_status':'Source/log grounded machine-assisted annotations; automated checks validate evidence linkage, not independent semantic correctness.'}
 if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
 else:assert report==json.loads((root/'artifacts/reports/feedback-mechanism-audit.json').read_text());print('PASS: complete 28-case selection, source hashes, shared initials, category evidence, status-only diffs and visible detection counts verified.')
if __name__=='__main__':main()
