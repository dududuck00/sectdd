"""Run the frozen 2x2 matched-information specification experiment."""
import argparse,ast,concurrent.futures,copy,hashlib,itertools,json,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.run_feedback_mechanism_v1 import candidate,evaluate,projection,write,sha,load
from sectdd.orchestrator import call_model,configure_local_network
from sectdd.formal_orchestrator import TokenCounter
from sectdd import sallm_formal_orchestrator as sallm,codeguardplus_formal_orchestrator as cg
CONFIG=ROOT/'configs/experiments/representation_v1.json'
def prompts(config):
 translations=load(ROOT/config['specifications']);result=[]
 for b in config['benchmarks']:
  proj=load(projection(b,'visible'))
  for task,item in sorted(proj['tasks'].items()):
   tree=ast.parse((ROOT/item['oracle_file']).read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
   bodies={n.name:ast.unparse(n) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
   fixture=copy.deepcopy(tree)
   for n in fixture.body:
    if isinstance(n,ast.ClassDef):
     n.body=[x for x in n.body if not (isinstance(x,ast.FunctionDef) and x.name.startswith('test_'))] or [ast.Pass()]
   fixture.body=[n for n in fixture.body if not isinstance(n,ast.If)]
   common=ast.unparse(fixture)
   for content,representation in itertools.product(['functional','both'],['code','prose']):
    cases=[c for c in item['cases'] if content=='both' or c['marker'] in ('functional','functionality')]
    assert len(cases)==(1 if content=='functional' else 2)
    messages=(sallm if b=='sallm' else cg).initial_messages(task,{'upfront_tests':'none'},proj)
    sections=['Additional behavioral specification. Each case uses the following common unittest environment, with setup and cleanup applied separately for each case. Complete the target implementation, not the tests.',f'```python\n{common}\n```']
    for c in cases:
     trans=translations[task]['cases'][c['test_method']];assert trans['source']==bodies[c['test_method']]
     sections.append(f"Case {c['case_id']} ({c['test_method']}, {c['marker']}): {c['description']}")
     sections.append(f"```python\n{trans['source']}\n```" if representation=='code' else trans['prose'])
    messages[-1]['content']+='\n\n'+'\n\n'.join(sections)
    result.append({'benchmark':b,'task':task,'method':representation+'_'+content,'messages':messages,'case_ids':[c['case_id'] for c in cases],'common_fixture':common})
 return result

def freeze(config):
 output=ROOT/config['output'];ps=prompts(config)
 files=[CONFIG,Path(__file__),ROOT/config['specifications'],ROOT/'docs/representation-v1-protocol.md',ROOT/'tools/analyze_representation_v1.py',ROOT/'tools/run_feedback_mechanism_v1.py']
 files += [ROOT/'sectdd'/f for f in ['orchestrator.py','formal_orchestrator.py','sallm_formal_orchestrator.py','codeguardplus_formal_orchestrator.py']]
 for b in config['benchmarks']:
  for partition in ['visible','hidden']:
   p=projection(b,partition);files.append(p)
   for item in load(p)['tasks'].values():files.append(ROOT/item['oracle_file'])
 for p in ps:
  pair=next(x for x in ps if x['task']==p['task'] and x['method']==p['method'].replace('code','prose'))
  assert p['case_ids']==pair['case_ids'] and p['common_fixture']==pair['common_fixture']
 result={'config':config,'files':{str(f.relative_to(ROOT)):sha(f) for f in files},'prompts':ps}
 target=output/'input-freeze.json'
 if target.exists():assert load(target)==result,'Frozen inputs changed'
 else:write(target,result)
 return result

def run_one(prompt,model,seed,config,api,tokenizer,python_info,freeze_sha):
 b,task,method=(prompt[k] for k in ['benchmark','task','method']);dest=ROOT/config['output']/'trajectories'/model/method/task.replace('/','__')/f'seed_{seed}'
 target=dest/'trajectory.json'
 if target.exists():assert load(target)['input_freeze_sha256']==freeze_sha;return
 messages=prompt['messages'];tokens=tokenizer.count_messages(messages)
 assert tokens+config['max_completion_tokens']<=config['context_tokens']
 raw=dest/'generation.json'
 if raw.exists():
  generation=load(raw);assert generation['messages']==messages and generation['input_freeze_sha256']==freeze_sha
 else:
  response,usage,elapsed=call_model(model,api,messages,seed,config['temperature'],config['max_completion_tokens'])
  generation={'messages':messages,'response':response,'usage':usage,'model_wall_seconds':elapsed,'input_freeze_sha256':freeze_sha,'prompt_tokens_local':tokens};write(raw,generation)
 code=candidate(b,task,dest,0,generation['response'])
 visible,vexec=evaluate(b,task,code,projection(b,'visible'),dest/'visible_execution',python_info)
 hidden,hexec=evaluate(b,task,code,projection(b,'hidden'),dest/'hidden_execution',python_info)
 fs=[c for c in hidden['cases'] if c['marker'] in ('functional','functionality')];ss=[c for c in hidden['cases'] if c['marker']=='security'];assert fs and ss
 f,s=all(c['passed'] for c in fs),all(c['passed'] for c in ss)
 write(target,{'benchmark':b,'task':task,'model':model,'generation_seed':seed,'method':method,'input_freeze_sha256':freeze_sha,'rounds':[{**generation,'visible_result':visible,'visible_execution':vexec}], 'final_hidden':{'functional':f,'security':s,'joint_pass':f and s,'raw':hidden,'execution':hexec},'hidden_feedback_used':False})
 print(f'DONE {model}/{method}/{task}/{seed}',flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze-only',action='store_true');p.add_argument('--model');p.add_argument('--api-base',default='http://127.0.0.1:19883/v1');p.add_argument('--workers',type=int,default=3);args=p.parse_args()
 config=load(CONFIG);frozen=freeze(config)
 if args.freeze_only:print(f"Frozen {len(frozen['prompts'])} prompts; 480 trajectories");return
 assert args.model in config['models'];configure_local_network();tokenizer=TokenCounter(Path(config['models'][args.model]));tokenizer.count_messages(frozen['prompts'][0]['messages'])
 python_info=cg.python_metadata(cg.DEFAULT_PYTHON.absolute());digest=sha(ROOT/config['output']/'input-freeze.json')
 work=list(itertools.product(frozen['prompts'],config['seeds']));random.Random(20260911).shuffle(work)
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  jobs=[pool.submit(run_one,p,args.model,s,config,args.api_base,tokenizer,python_info,digest) for p,s in work]
  for job in concurrent.futures.as_completed(jobs):job.result()
if __name__=='__main__':main()
