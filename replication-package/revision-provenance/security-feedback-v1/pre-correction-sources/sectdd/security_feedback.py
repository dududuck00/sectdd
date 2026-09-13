"""Fixed functional channel plus an optional, separately budgeted security channel."""
REVISION='Review and revise the implementation to satisfy the original requirements. Return one complete fenced Python module.'
FUNCTIONAL={'functional','functionality'}
def channel(visible,kind,config,tokenizer):
 cases=[c for c in visible['cases'] if (c['marker'] in FUNCTIONAL if kind=='functional' else c['marker']=='security')]
 if not cases:raise ValueError('Missing '+kind+' cases')
 failed=sorted([c for c in cases if not c['passed']],key=lambda c:c['case_id'])
 chosen=failed[:config['max_cases_per_channel']]
 chunks=[f"Visible {kind} tests: {'FAIL' if failed else 'PASS'}."]
 for c in chosen:
  tail='\n'.join((c.get('failure') or 'Test did not complete successfully.').splitlines()[-config['failure_tail_lines']:])
  chunks.append(f"Case: {c['case_id']}\nType: {c['marker']}\nProperty: {c['description']}\nObserved failure:\n{tail}")
 full='\n\n'.join(chunks);text=tokenizer.truncate_text(full,config['channel_tokens'])
 return {'text':text,'full':full,'case_ids':[c['case_id'] for c in chosen],'passed':not failed,'truncated':full!=text,'tokens':tokenizer.count_text(text)}
def make_feedback(method,visible,config,tokenizer):
 assert method in ['functional_only','functional_security']
 f=channel(visible,'functional',config,tokenizer);s=channel(visible,'security',config,tokenizer) if method=='functional_security' else None
 text=REVISION+'\n\n'+f['text']+('\n\n'+s['text'] if s else '')
 assert tokenizer.count_text(text)<=config['feedback_tokens']
 return text,{'functional':f,'security':s,'delivered_tokens':tokenizer.count_text(text)}
