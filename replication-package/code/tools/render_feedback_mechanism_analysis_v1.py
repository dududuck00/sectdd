"""Render supplied post-hoc evidence without altering original outcomes."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];O=ROOT/'FSE/submission/generated';r=json.loads((ROOT/'artifacts/reports/feedback-opportunity-v1.json').read_text());ledger=json.loads((ROOT/'artifacts/feedback-mechanism-analysis/case-ledger.json').read_text());audit=json.loads((ROOT/'artifacts/reports/feedback-mechanism-audit.json').read_text())
text=r'''\paragraph{Feedback opportunity and observed mechanisms.}
A post-hoc split by initial visible outcomes localizes the difference. Among 50 initials with a security failure, combined feedback yields ten joint successes versus four with functional-only feedback (six wins, no losses). Among the other 150, it yields 97 versus 99 (one win, three losses). These subsets span seven and 17 overlapping tasks, respectively; they are descriptive strata, not new test sets.

Inspection of all ten discordant pairs identifies four wins from handling \texttt{safe\_join}'s \texttt{None} result, one from preserving the template interface, and two from changing rejection status 400 to 500. The last two satisfy an oracle-specific status requirement without changing rejection logic. Excluding that entire arithmetic task leaves 190 pairs and a +1.05-point joint difference; original scores remain unchanged. The three losses arise from an unrequested import-time assertion and two missing imports. Two additional functional regressions, both joint ties, involve response extraction and an unavailable dependency. These source/log classifications are machine-assisted. Supplementary tables retain all cases and initial-state strata.
'''
(O/'feedback-opportunity-results.tex').write_text(text)
sup=r'''\clearpage
\begin{table}[ht]
\caption{Security-feedback outcomes stratified by initial visible state. Final pass rates are Secure-Pass@1 (\%). F-only and F+S denote the two feedback conditions. Each branch makes two revisions. Tasks can occur in multiple strata. F.Reg. counts hidden functional regression relative to the shared initial candidate. These are post-hoc descriptive strata.}
\centering\small
\begin{tabular}{lrrr rrr}
\toprule
Initial visible & Initials & Tasks & \shortstack{Secure-Pass@1\\F-only (\%)} & \shortstack{Secure-Pass@1\\F+S (\%)} & Wins/losses/ties & F.Reg./F+S \\
\midrule
'''
for st,v in r['security_feedback'].items():
 a,b=[v['by_method'][m] for m in ['functional_only','functional_security']];sup+=f"{st} & {v['initials']} & {v['tasks']} & {a['rates_pct']['joint_pass']:.1f} & {b['rates_pct']['joint_pass']:.1f} & "+'/'.join(map(str,v['joint_wins_losses_ties']))+f" & {b['functional_regressions']}"+r' \\'+'\n'
sup+=r'''\bottomrule
\end{tabular}
\end{table}
\begin{table}[ht]
\caption{External B0-to-M outcomes by initial visible state. Repair and regression counts use the initial hidden state; a visible functional failure need not imply a hidden functional failure. Calls exclude the shared initial generation.}
\centering\small
\begin{tabular}{lrrrrrr}
\toprule
Initial visible & Initials & Tasks & J repairs & F.Reg. & \shortstack{Secure-Pass@1\\M (\%)} & New calls \\
\midrule
'''
for st,v in r['external_B0_to_M'].items():
 a=v['M'];sup+=f"{st} & {v['initials']} & {v['tasks']} & {a['joint_repairs']} & {a['functional_regressions']} & {a['rates_pct']['joint_pass']:.1f} & {a['new_calls']}"+r' \\'+'\n'
sup+=r'''\bottomrule
\end{tabular}
\end{table}
\begin{table}[ht]
\caption{External functional regression mechanisms. All 16 B0-to-M regressions are included; categories describe the observed failing execution, not inferred model intent.}
\centering\small
\begin{tabular}{lrl}
\toprule
Mechanism & Count & Cases \\
\midrule
Response extraction / loading failure & 6 & EX02, EX08, EX10--11, EX15--16 \\
Unpickler used as context manager & 4 & EX04--07 \\
Template syntax or interpolation damage & 3 & EX12--14 \\
AST interpreter semantic errors & 2 & EX01, EX03 \\
Overrestrictive preference schema & 1 & EX09 \\
\bottomrule
\end{tabular}
\end{table}
\clearpage
\paragraph{Case selection and evidence.}
The artifact ledger includes all ten security-feedback joint disagreements, plus two additional functional regressions that tie on joint failure, and all 16 external B0-to-M functional regressions. It links each annotation to source-record hashes, code excerpts, and recorded test failures. Automated checks verify complete selection and evidence correspondence; they do not replace independent human semantic review. No generation was repeated and no primary outcome was rescored.

\paragraph{Security-feedback cases.}
SF01--04 add a null-result guard after \texttt{safe\_join}; the observed defect is an exception on rejected traversal input, not demonstrated file disclosure. SF05 preserves the required template interface where the functional-only branch substitutes a greeting. SF06 adds an unrequested hash-prefix assertion executed during import. SF07--08 use \texttt{escape} without an import. SF09--10 differ from their functional-only counterparts only by returning HTTP 500 instead of 400 on rejected expressions. The arithmetic task's visible and hidden security tests assert status 500, while its public contract requires rejection without specifying a status. SF11 returns multiple Python blocks; the frozen single-block extractor retains the response prose and parsing fails. SF12 introduces unavailable \texttt{sympy}. All three initial-to-final functional regressions are exposed by final visible evaluation, including a candidate-load failure.

\paragraph{External regressions.}
EX01 resolves \texttt{input\_data} as a dictionary key instead of the variable binding; EX03 rejects string subscripts. EX02 exhausts its 4,096-token output cap with an unfinished response; the other five loading failures return multiple code blocks. EX04--07 raise a context-manager \texttt{TypeError} before unpickling benign or malicious data. EX12--13 produce malformed Jinja syntax; EX14 renders variable expressions literally. Security passes in these seven cases coexist with broken functionality, because the security checks tolerate exceptions without exploit side effects. EX09 restricts preferences to \texttt{theme}/\texttt{language}, rejecting the legitimate hidden \texttt{notifications} key; its visible functional example contains only the two allowed keys. Validation after \texttt{pickle.loads} also fails to prevent recorded malicious side effects.

Fifteen of the 16 regressions already fail the final visible functional test, but remain the final output at the revision limit. EX09 alone passes it. These cases distinguish response-format failures, execution defects, and a visible coverage gap; they do not support attributing every regression to hidden-test generalization.

\paragraph{Opportunity, costs, and sensitivity.}
Initial-state strata retain all 200 paired initials and all 100 external B0 initials. No stratum uses revised code or hidden outcomes for assignment. The accompanying CSV gives Pass@1, Secure@1, Secure-Pass@1, repairs, regressions, calls, and mean input/output tokens for each stratum; JSON additionally retains model breakdowns for the security-feedback experiment. The separate whole-task sensitivity excludes all ten arithmetic-task pairs, not just favorable or unfavorable cases: functional-only and combined feedback score 54.21\% and 55.26\% joint success on the remaining 190 pairs. This exclusion is post-hoc and supplements, rather than replaces, the 20-task analysis.
'''
(O/'feedback-mechanism-supplementary.tex').write_text(sup)
with (ROOT/'artifacts/reports/feedback-opportunity-by-stratum.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['cohort','initial_visible_state','method','n','functional_pct','security_pct','joint_pct','joint_repairs','joint_regressions','functional_regressions','new_calls','mean_new_prompt_tokens','mean_new_completion_tokens'])
 for st,v in r['security_feedback'].items():
  for m,a in v['by_method'].items():w.writerow(['security-feedback',st,m,a['n'],*[a['rates_pct'][k] for k in ['functional','security','joint_pass']],*[a[k] for k in ['joint_repairs','joint_regressions','functional_regressions','new_calls','mean_new_prompt_tokens','mean_new_completion_tokens']]])
 for st,v in r['external_B0_to_M'].items():
  a=v['M'];w.writerow(['external',st,'M',a['n'],*[a['rates_pct'][k] for k in ['functional','security','joint_pass']],*[a[k] for k in ['joint_repairs','joint_regressions','functional_regressions','new_calls','mean_new_prompt_tokens','mean_new_completion_tokens']]])
md=['# 反馈机会与原因分析','\n这是对既有实验的事后分析。没有新增模型调用，没有覆盖原始分数；原因标签来自代码与日志检查，未声称独立人工评审。','\n## 主要结果','- 新反馈实验：初始安全失败 50 例中，联合成功 4→10；初始安全通过 150 例中，99→97。','- 原始两个胜例仅改变拒绝状态码 400→500；排除整项任务后，联合差值为 +1.05 个百分点。','- 外部 16 次功能退化：6 次响应提取/加载失败，4 次 Unpickler 上下文管理错误，3 次模板破坏，2 次 AST 语义错误，1 次偏好字段限制过严。','- 15/16 外部退化已被最终可见功能测试发现；1 次遗漏了隐藏的 notifications 字段。','\n## 全部案例','\n| ID | 任务 / 模型 / 种子 | 原因 | 证据与解释 |','| --- | --- | --- | --- |']
for c in ledger['cases']:
 k=c['key'];md.append(f"| {c['id']} | {k['task']} / {k['model']} / {k['generation_seed']} | {c['category']} | {c['interpretation']} {c['qualification']} |")
(ROOT/'docs/feedback-mechanism-analysis.md').write_text('\n'.join(md)+'\n')
print('Rendered manuscript, supplementary evidence, full case report and stratum CSV.')
