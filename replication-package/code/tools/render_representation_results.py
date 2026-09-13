"""Generate paper tables directly from the complete, frozen-analysis report."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 r=json.loads((ROOT/'artifacts/reports/representation-v1.json').read_text());assert r['complete'] and r['trajectories']==480
 labels={'code_functional':('Functional','Code'),'prose_functional':('Functional','Prose'),'code_both':('Functional + security','Code'),'prose_both':('Functional + security','Prose')}
 lines=[r'\begin{table}[t]',r'\caption{Matched-information representation experiment: 120 candidates per condition. Pass rates use hidden tests and are reported in percent; input and output are mean tokens per candidate. Fixture/helper code is identical within each representation pair.}',r'\label{tab:representation}',r'\centering\small',r'\begin{tabular}{llrrrrr}',r'\toprule',r'Content & Expression & Pass@1 & Secure@1 & \textbf{Secure-Pass@1} & Input & Output \\',r'\midrule']
 for method,(content,rep) in labels.items():
  vals=r['methods'][method];cost=r['costs'][method];lines.append(f'{content} & {rep} & '+' & '.join(f'{vals[k]*100:.1f}' for k in ['functional','security','joint_pass'])+f" & {cost['prompt_tokens']:.0f} & {cost['completion_tokens']:.0f}"+r' \\')
 lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
 (ROOT/'FSE/submission/generated/representation-table.tex').write_text('\n'.join(lines)+'\n')
 lines=[r'\begin{table}[ht]',r'\caption{Representation results by model. Each row contains 60 task--seed observations.}',r'\centering\small',r'\begin{tabular}{lllrrr}',r'\toprule',r'Model & Content & Expression & Pass@1 (\%) & Secure@1 (\%) & \textbf{Secure-Pass@1} (\%) \\',r'\midrule']
 for model,methods in r['by_model'].items():
  for method,(content,rep) in labels.items():lines.append(f"{model.replace('qwen25-coder-','Qwen ').replace('b','B')} & {content} & {rep} & "+' & '.join(f'{methods[method][k]*100:.1f}' for k in ['functional','security','joint_pass'])+r' \\')
 lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
 lines += [r'\begin{table}[ht]',r'\caption{Per-task hidden joint pass rates (\%) for the representation experiment. Each condition has ten model--seed observations per task.}',r'\centering\small',r'\begin{tabular}{lrrrr}',r'\toprule',r'Task & F/code & F/prose & F+S/code & F+S/prose \\',r'\midrule']
 for task,v in r['by_task'].items():
  name=task.replace('Assertion_','').replace('Tainted_','').replace('.py','').replace('_',r'\_')
  lines.append(name+' & '+' & '.join(f"{v[m]['joint_pass']*100:.0f}" for m in labels)+r' \\')
 lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
 (ROOT/'FSE/submission/generated/representation-supplementary.tex').write_text('\n'.join(lines)+'\n')
 out=ROOT/'artifacts/reports/representation-by-task.csv'
 with out.open('w') as f:
  w=csv.writer(f);w.writerow(['task','method','functional_pct','security_pct','joint_pct'])
  for task,v in r['by_task'].items():
   for m in labels:w.writerow([task,m,*[100*v[m][k] for k in ['functional','security','joint_pass']]])
 print('Generated tables and 48-row per-task CSV from complete report')
if __name__=='__main__':main()
