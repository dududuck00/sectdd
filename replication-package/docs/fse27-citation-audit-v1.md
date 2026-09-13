# FSE27 投稿稿参考文献核验

对象：`FSE/submission/references.bib`。原稿 29 条，新增 SecCodeBench-V2 后 30 条。原始检索返回保存在 `artifacts/citation-audit-v1/`。本轮检查条目存在性、标题、作者及出处，另按论文段落核对主要引用用途；不把能打开网页视为全文论断已验证。

## 修正

- 原 `SecCodePLT` 条目对应 arXiv v1，但无版本 URL 指向已改题名和作者顺序的 v2。改为 NeurIPS 2025 官方会议条目 `SECODEPLT: A Unified Benchmark for Evaluating the Security Risks and Capabilities of Code GenAI`；完整 BibTeX 直接取自会议站点，保留原 citation key 以避免误断引用。
- PromSec 标题补全官方题名结尾 `(LLMs)`。
- SALLM 第二作者规范为 DOI 元数据中的 Joanna Cecilia da Silva Santos；并非新增或替换作者。
- SecCodeBench-V2 条目直接获取 DOI 内容协商返回的 BibTeX，未猜测作者或出处。

## 访问失败及替代核验

| 条目 | 首次访问问题 | 支持存在性和元数据的一手来源 |
|---|---|---|
| SecurityEval | Crossref 限流、ACM 403 | 作者实验室仓库及 CITATION.cff：https://github.com/s2e-lab/SecurityEval |
| EvalPlus | Crossref 限流 | NeurIPS 2023 官方论文页：https://proceedings.neurips.cc/paper_files/paper/2023/hash/43e9d647ccd3e4b7b5baab53f0368686-Abstract-Conference.html |
| CodeT | OpenReview 浏览器校验页 | 作者 arXiv：https://arxiv.org/abs/2207.10397；OpenReview 原链接保留 |
| Rethinking the Evaluation | Crossref 404 | 作者最终 PDF 明列同一 DOI：https://tao.aisec.world/assets/pdf/ICSE26.pdf；作者出版列表确认 ICSE 2026：https://tao.aisec.world/publications/ |
| Holm 1979 | JSTOR 校验页 | 原论文扫描件含作者、期刊卷页和稳定链接：https://www.ime.usp.br/~abe/lista/pdf4R8xPVzCnX.pdf |
| Beck 2002 | 原条目无在线 URL | 出版社页明确 2002 版与 ISBN：https://www.pearson.com/en-us/subject-catalog/p/Beck-Test-Driven-Development-By-Example/P200000009421/9780321146533 |
| Qwen3.6 | 原始 HTML 只有应用标题 | 官方可索引发布页：https://qwen.ai/blog?id=qwen3.6-27b&lang=zh-CN |

其余条目通过 DOI 注册元数据、PMLR、ACL Anthology、arXiv 或项目官方页面核对。不能根据某个 DOI API 的 404 就认定引用不存在；ICSE 2026 条目有作者最终 PDF 的直接支持。

## 引用上下文边界

- VRpilot 支持“对已知漏洞进行带推理及执行验证的迭代修复”；不能把它描述为没有反馈对照，或声称本研究完整复现并击败该系统。
- AutoSafeCoder 支持“代码生成中结合静态分析和 fuzzing 的迭代安全增强”；本文不把摘要中的功能保持结论当作本任务上的可比结果。
- Self-Debugging 支持“模型可以借助执行与解释修订代码”；这也说明仅与一次调用比较不足以区分反馈信息和更多推理。
- Rethinking 支持同一候选上联合衡量安全与功能的动机，不构成本研究动态 oracle 正确性的外部认证。
- SecCodeBench-V2 提供工业来源的项目脚手架和功能级修改任务；本轮十个 Python 项目不等于多文件自主 agent 或多语言完整 benchmark。
- 原博士生审查表述属于作者报告的历史审查事实，不由参考文献证实；新的十任务复核未完成，不得沿用该表述。
