"""Render the observed per-task contrasts without aggregate smoothing."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
r=json.loads((ROOT/'artifacts/reports/external-task-analysis-v1.json').read_text())['rows']
order=['CommandInjectionSubprocessRun','SQLInjectionPsycopg2','SQLInjectionPyMySQL','SQLInjectionSQLite3','SSTIJinja2Template','CodeInjectionEval','SSTIFlaskRenderTemplateString','CommandInjectionSubprocessPopen','DeserializationPickle','DeserializationPyYAML']
names=['Command / subprocess.run','SQL / psycopg2','SQL / PyMySQL','SQL / SQLite3','Template / Jinja2','Code / eval','Template / Flask','Command / subprocess.Popen','Deserialize / pickle','Deserialize / PyYAML']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42,'svg.fonttype':'none'})
fig,axes=plt.subplots(1,3,figsize=(8.8,3.65),sharey=True,gridspec_kw={'wspace':.15})
for ax,contrast,title in zip(axes,['B3-B0','M-B0','B6-B3'],['(a) Upfront tests: B3 − B0','(b) Feedback: M − B0','(c) Feedback: B6 − B3']):
 data=np.array([[next(x for x in r if x['task']==t and x['contrast']==contrast)[metric+'_delta_pp'] for metric in ['functional','security','joint_pass']] for t in order])
 im=ax.imshow(data,cmap='RdBu',vmin=-80,vmax=80,aspect='auto')
 for i in range(10):
  for j in range(3):ax.text(j,i,f'{data[i,j]:+d}' if data[i,j] else '0',ha='center',va='center',color='white' if abs(data[i,j])>=50 else '#172736',fontsize=9)
 ax.set_xticks([0,1,2],['Δ Pass@1','Δ Secure@1','Δ Secure-\nPass@1'],fontsize=8);ax.xaxis.tick_top();ax.set_yticks(range(10),names);ax.set_title(title,pad=34,fontsize=9,fontweight='bold');ax.tick_params(length=0)
 ax.set_xticks(np.arange(-.5,3,1),minor=True);ax.set_yticks(np.arange(-.5,10,1),minor=True);ax.grid(which='minor',color='white',linewidth=2);ax.tick_params(which='minor',length=0)
 for s in ax.spines.values():s.set_visible(False)
fig.subplots_adjust(left=.25,right=.98,top=.76,bottom=.09)
fig.text(.615,.015,'Change in pass rate (percentage points); 10 paired observations per task',ha='center',fontsize=8)
for ext in ['pdf','svg','png']:fig.savefig(ROOT/f'FSE/submission/figures/external-task-effects.{ext}',dpi=220,bbox_inches='tight')
