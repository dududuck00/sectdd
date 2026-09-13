"""Two fresh fixed-call branches per archived initial; security information ablation."""
import argparse,concurrent.futures,copy,json,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.run_feedback_mechanism_v1 import candidate,evaluate,projection,load,write,sha
from sectdd.security_feedback import make_feedback
from sectdd.orchestrator import call_model,configure_local_network
from sectdd.formal_orchestrator import TokenCounter
from sectdd import codeguardplus_formal_orchestrator as cg
CONFIG=ROOT/'configs/experiments/security_feedback_v1.json'
def freeze(cfg):
 files=[CONFIG,Path(__file__),ROOT/'sectdd/security_feedback.py',ROOT/'tools/analyze_security_feedback_v1.py',ROOT/'docs/security-feedback-v1-protocol.md',ROOT/'tools/run_feedback_mechanism_v1.py']
 files += [ROOT/'sectdd'/f for f in ['orchestrator.py','formal_orchestrator.py','sallm_formal_orchestrator.py','codeguardplus_formal_orchestrator.py']]
 files += [ROOT/'tools'/f for f in ['cweval_sandbox.py','paper_oracle_sandbox.py','run_paper_oracle_tests.py','sallm_bwrap.py','codeguardplus_bwrap.py']]
 initials=[]
 for b in cfg['benchmarks']:
  for part in ['visible','hidden']:
   p=projection(b,part);files.append(p)
   for item in load(p)['tasks'].values():files.append(ROOT/item['oracle_file'])
  for task in sorted(load(projection(b,'visible'))['tasks']):
   for model in cfg['models']:
    for seed in cfg['seeds']:
     p=ROOT/cfg['initial_root']/b/model/'trajectories/B0'/task.replace('/','__')/f'seed_{seed}/trajectory.json';r=load(p)
     assert (r['task'],r['model'],r['generation_seed'])==(task,model,seed) and len(r['rounds'])==1
     initials.append({'benchmark':b,'task':task,'model':model,'seed':seed,'path':str(p.relative_to(ROOT)),'sha256':sha(p)})
 assert len(initials)==200
 result={'config':cfg,'files':{str(p.relative_to(ROOT)):sha(p) for p in files},'initials':initials}
 target=ROOT/cfg['output']/'input-freeze.json'
 if target.exists():assert load(target)==result,'Frozen inputs changed'
 else:write(target,result)
 return result

def assert_infrastructure(result,execution):
 # Candidate syntax/import/test failures are legitimate outcomes; host startup is not.
 text=json.dumps([result,execution])
 for error in ['bwrap:','setting up uid map: Permission denied','SALLM sandbox doctor failed','prlimit: failed']:
  if error in text:raise RuntimeError('Infrastructure failure: '+error)
 for c in result['cases']:
  if c.get('status') in ['infrastructure_error','not_runnable']:raise RuntimeError('Infrastructure case: '+str(c))

def execute(initial,method,cfg,api,counter,python_info,digest):
 b,task,model,seed=(initial[k] for k in ['benchmark','task','model','seed']);dest=ROOT/cfg['output']/'trajectories'/b/model/method/task.replace('/','__')/f'seed_{seed}';target=dest/'trajectory.json'
 if target.exists():assert load(target)['input_freeze_sha256']==digest;return
 archived=load(ROOT/initial['path']);assert sha(ROOT/initial['path'])==initial['sha256']
 first=archived['rounds'][0];messages=copy.deepcopy(first['messages']);response=first['response'];visible=first['visible_result']
 rounds=[{'round':0,'messages':messages,'response':response,'visible_result':visible,'generation_reused':True}]
 for index in [1,2]:
  feedback,audit=make_feedback(method,visible,cfg,counter)
  rounds[-1].update(feedback=feedback,feedback_audit=audit)
  messages=[*messages,{'role':'assistant','content':response},{'role':'user','content':feedback}]
  assert counter.count_messages(messages)+cfg['max_completion_tokens']<=cfg['context_tokens']
  gp=dest/f'round_{index}/generation.json'
  if gp.exists():
   gen=load(gp);assert gen['messages']==messages and gen['input_freeze_sha256']==digest
  else:
   response,usage,elapsed=call_model(model,api,messages,seed+index,cfg['temperature'],cfg['max_completion_tokens'])
   gen={'round':index,'messages':messages,'response':response,'usage':usage,'model_wall_seconds':elapsed,'request_seed':seed+index,'generation_reused':False,'input_freeze_sha256':digest};write(gp,gen)
  response=gen['response'];code=candidate(b,task,dest,index,response)
  vp=dest/f'round_{index}/visible.json'
  if vp.exists():v=load(vp);visible,execution=v['result'],v['execution']
  else:
   visible,execution=evaluate(b,task,code,projection(b,'visible'),dest/f'round_{index}/visible_execution',python_info);assert_infrastructure(visible,execution);write(vp,{'result':visible,'execution':execution})
  rounds.append({**gen,'visible_result':visible,'visible_execution':execution})
 hidden,execution=evaluate(b,task,code,projection(b,'hidden'),dest/'hidden_execution',python_info);assert_infrastructure(hidden,execution)
 fc=[c for c in hidden['cases'] if c['marker'] in ['functional','functionality']];sc=[c for c in hidden['cases'] if c['marker']=='security'];assert fc and sc
 f,s=all(c['passed'] for c in fc),all(c['passed'] for c in sc)
 initial_hidden={'functional':archived['final_hidden']['functional']['all_passed'],'security':archived['final_hidden']['security']['all_passed'],'joint_pass':archived['final_hidden']['joint_pass']}
 write(target,{'benchmark':b,'task':task,'model':model,'generation_seed':seed,'method':method,'input_freeze_sha256':digest,'initial':initial,'initial_hidden':initial_hidden,'rounds':rounds,'final_hidden':{'functional':f,'security':s,'joint_pass':f and s,'raw':hidden,'execution':execution},'hidden_feedback_used':False,'stop_reason':'fixed_two_revisions'})
 print(f'DONE {b}/{model}/{method}/{task}/{seed}',flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze-only',action='store_true');p.add_argument('--model');p.add_argument('--workers',type=int,default=12);p.add_argument('--api-base',default='http://127.0.0.1:19884/v1');args=p.parse_args()
 cfg=load(CONFIG);frozen=freeze(cfg)
 if args.freeze_only:print('Frozen 200 shared initials, 400 trajectories, 800 new calls');return
 assert args.model in cfg['models'];configure_local_network();counter=TokenCounter(Path(cfg['models'][args.model]));counter.count_text('Initialize');python_info=cg.python_metadata(cg.DEFAULT_PYTHON.absolute());digest=sha(ROOT/cfg['output']/'input-freeze.json')
 work=[(i,m) for i in frozen['initials'] if i['model']==args.model for m in cfg['methods']];random.Random(cfg['bootstrap_seed']).shuffle(work)
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures=[pool.submit(execute,i,m,cfg,args.api_base,counter,python_info,digest) for i,m in work]
  for f in concurrent.futures.as_completed(futures):f.result()
if __name__=='__main__':main()
