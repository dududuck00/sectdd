# SecTDD

面向 FSE 2027 的测试驱动安全代码生成实验项目。

## 复现材料与详细结果

- [详细结果与分析 PDF](replication-package/supporting-results/supplementary-tables.pdf)
- [结果与复现入口说明](replication-package/supporting-results/README.md)
- [完整复现包说明](replication-package/README.md)

该文档收录逐任务指标、对照实验、干预机会和案例分析，作为复现包的一部分。匿名仓库同步时，以 `replication-package/` 的内容作为仓库根目录，保留 README、代码、数据、许可证与 supporting-results 目录。

- 实验预注册草案与指标定义：[protocol.md](protocol.md)
- Oracle 构造与冻结规范：[oracle_protocol.md](oracle_protocol.md)
- 外部 benchmark manifest：[docs/external-benchmark-manifests.md](docs/external-benchmark-manifests.md)
- SALLM Bubblewrap 隔离执行器：[docs/sallm-bubblewrap.md](docs/sallm-bubblewrap.md)
- CodeGuard+ Python 无 Docker 验证器：
  [docs/codeguardplus-python-bwrap.md](docs/codeguardplus-python-bwrap.md)
- CodeGuard+ 六题基础设施 smoke 结果：
  [docs/codeguardplus-python-smoke-v1-results.md](docs/codeguardplus-python-smoke-v1-results.md)
- CodeGuard+ 24 题资格化候选池：
  [docs/codeguardplus-qualification-candidates-v2.md](docs/codeguardplus-qualification-candidates-v2.md)
- CodeGuard+ 稳定安全参考：
  [docs/codeguardplus-stable-safe-v1.md](docs/codeguardplus-stable-safe-v1.md)
- CodeGuard+ 漏洞变异体筛选：
  [docs/codeguardplus-mutant-selection-v1.md](docs/codeguardplus-mutant-selection-v1.md)
- CodeGuard+ 15 个机器资格化 oracle pairs：
  [docs/codeguardplus-oracle-pairs-v1.md](docs/codeguardplus-oracle-pairs-v1.md)
- CodeGuard+ v2 机器语义审查：
  [docs/codeguardplus-semantic-machine-v2.md](docs/codeguardplus-semantic-machine-v2.md)
- CodeGuard+ 全新 seeds 多模型 G8 preflight：
  [docs/codeguardplus-preflight-v1.md](docs/codeguardplus-preflight-v1.md)
- CodeGuard+ 32 题 reserve expansion wave：
  [docs/codeguardplus-reserve-expansion-v1.md](docs/codeguardplus-reserve-expansion-v1.md)
- SALLM Python 环境引导脚本：[scripts/bootstrap_sallm_env.sh](scripts/bootstrap_sallm_env.sh)
- SALLM overlay v1 参考审计结果：[docs/sallm-reference-audit-v1.md](docs/sallm-reference-audit-v1.md)
- SALLM 安全参考候选生成：[docs/sallm-secure-candidate-generation.md](docs/sallm-secure-candidate-generation.md)
- Qwen3.6-27B SALLM 安全参考 pilot 结果：[docs/qwen36-27b-sallm-secure-reference-pilot-v1.md](docs/qwen36-27b-sallm-secure-reference-pilot-v1.md)
- SALLM 多候选生成入口：[tools/generate_sallm_secure_candidates.py](tools/generate_sallm_secure_candidates.py)
- SALLM visible/hidden oracle v3 与 7B smoke：
  [docs/sallm-partitioned-oracle-v3-smoke.md](docs/sallm-partitioned-oracle-v3-smoke.md)
- SALLM 方法实验入口：[tools/run_sallm_formal.py](tools/run_sallm_formal.py) /
  [tools/validate_sallm_formal.py](tools/validate_sallm_formal.py)
- Qwen3.6 本地服务入口：[scripts/serve_qwen36.sh](scripts/serve_qwen36.sh)
- CWEval 环境、命令和已完成结果：[docs/cweval-pilot.md](docs/cweval-pilot.md)
- B0–B5/SecTDD 方法矩阵：[docs/method-matrix-pilot.md](docs/method-matrix-pilot.md)
- 三任务论文级 oracle candidate：[docs/oracle-paper-candidate-v1.md](docs/oracle-paper-candidate-v1.md)
- 九任务反馈触发型 oracle candidate v2：[docs/oracle-paper-candidate-v2.md](docs/oracle-paper-candidate-v2.md)
- 7B 九任务 protocol v2 开发实验：[docs/qwen25-coder-7b-feedback-v2-9tasks-seeds3.md](docs/qwen25-coder-7b-feedback-v2-9tasks-seeds3.md)
- 14B 九任务 protocol v2 开发实验：[docs/qwen25-coder-14b-feedback-v2-9tasks-seeds3.md](docs/qwen25-coder-14b-feedback-v2-9tasks-seeds3.md)
- Protocol v2 双模型比较：[docs/feedback-v2-9tasks-seeds3-two-models.md](docs/feedback-v2-9tasks-seeds3-two-models.md)
- 三任务 × 三 seeds 正式配对 pilot：[docs/formal-pilot-3tasks-seeds3-paired-v3.md](docs/formal-pilot-3tasks-seeds3-paired-v3.md)
- 模型服务脚本：[scripts/serve_qwen25_coder.sh](scripts/serve_qwen25_coder.sh)
- CWEval 生成入口：[tools/generate_cweval.py](tools/generate_cweval.py)
- 隔离评测入口：[tools/cweval_sandbox.py](tools/cweval_sandbox.py)
- 指标汇总入口：[tools/summarize_cweval.py](tools/summarize_cweval.py)
- 方法矩阵入口：[tools/run_method_matrix.py](tools/run_method_matrix.py)
- 方法矩阵审计：[tools/validate_method_matrix.py](tools/validate_method_matrix.py)
- Oracle mutation 审计：[tools/validate_oracle_set.py](tools/validate_oracle_set.py)
- 正式 pilot 运行/审计：[tools/run_formal_pilot.py](tools/run_formal_pilot.py) /
  [tools/validate_formal_pilot.py](tools/validate_formal_pilot.py)
- 两模型比较报告生成：[tools/compare_formal_pilot.py](tools/compare_formal_pilot.py)
- Protocol v2 反馈分析：[tools/analyze_feedback_v2.py](tools/analyze_feedback_v2.py)
- Protocol v2 双模型汇总：[tools/compare_feedback_v2.py](tools/compare_feedback_v2.py)

当前已使用 GPU 4 跑通 Qwen2.5-Coder-7B-Instruct 和
Qwen2.5-Coder-14B-Instruct 的全部 25 个 CWEval Python 任务，每题使用
3 个显式 generation seeds。CWE-20/78/79 已完成按行为族隔离的论文级
oracle candidate、三次 mutation 验证，以及 2 模型 × 7 方法 × 3 任务 ×
3 seeds 的 126 条正式配对 pilot。

Protocol v2 已扩展到 9 个行为族任务和 81 个 oracle cases；安全参考与
mutants 的 162 次三重复隔离验证全部通过。7B/14B 的 9 tasks × 7 methods ×
3 seeds 共 378 条反馈开发轨迹均已完成并通过审计；B4/B5/M 共享 B0 首轮，
合计 85.2% 的反馈轨迹触发第二轮，两个模型的 Go/No-Go 均为 GO。B4 在
7B/14B 上取得最高 Secure-Pass@1（48.1%/59.3%）。

CodeGuard+ 无 Docker 工程链路现已完成首轮 15 个 safe/mutant pair 的机器资格化、
visible/hidden 构建、语义修复和 64 条全新-seed G8 trajectory；严格 G8 只保留
CWE-327。为扩大可辨识题池，全部 32 道未观察 reserve 题已完成污染审计和哈希
冻结；96 个安全候选初筛后保留 24 题，其 72 次三重复均为 F+S+，覆盖 14 个
CWE。该外部 benchmark 尚不能进入确认性主实验；下一步是生成并资格化漏洞
变异体、构建分区行为族，并最终完成独立第二研究者 G7，而不是放宽门槛。
