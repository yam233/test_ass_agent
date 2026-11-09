# 五批改造验收记录

日期：2026-11-10。五批、8 个实施任务完成。范围为本地 mock 平台上的单机工作流运行时；已完成一次独立整分支审阅及问题修复。

## 交付内容

| 批次 | 已实现 | 批次提交 |
|---|---|---|
| 一 | 核心/兼容依赖拆分、仓库外 venv 测试、UTF-8 引用分页、不可升级的预演、状态版本 | `605ce1d`、`6dbddf4` |
| 二 | 持久权限交集、显式写身份、删除快照确认、事务审计、模型重试及预算、配置指纹 | `12be4e8`、`7031cde` |
| 三 | checkpoint CAS、迁移备份、过期审批、refs GC、安全 reset、完整消息对与上下文预算 | `972672e`、`554f016` |
| 四 | 统一 fixture/chaos/replay/remote 入口、7 条业务链、独立状态判分、基线校验、JSONL 导出 | `ace588c` |
| 五 | 持久队列、两个执行槽、inline/queued 共池、受监督工具子进程、取消、停机及重启恢复 | `aec0ca3` |

代码保存在 `codex/runtime-hardening`；后续验收提交包含审阅修复、格式整理和本记录。改动同步回原项目，保留原有本地配置、凭证、运行数据与无关改动。本轮未推送远程仓库。

## 实际验证

测试使用合成平台、临时 SQLite、脚本模型和假传输；没有调用付费模型。两套仓库外虚拟环境已分别安装对应 requirements 后运行。

| 命令/场景 | 实际结果 |
|---|---|
| 核心环境 `python -m pytest tests -q` | 143 passed |
| 完整依赖环境 `python -m pytest tests_legacy -q` | 34 passed |
| 同步回原项目后 `python -m pytest tests tests_legacy -q` | 177 passed；67 个新增、修改、删除路径逐项一致 |
| `python -m evals.runner --model fixture --repeat 4` | 37 用例 × 4 次，148/148；完整运行 |
| `python -m evals.runner --model chaos --repeat 4 --seed 17` | 28/28；拦截率 100%，错误放行与正常误拒均 0 |
| fixture `--record` 后用 `--model replay --replay …` | 7/7 多步链回放；观察或契约不匹配有拒绝测试 |
| `python -m evals.runner --suite backpack` | 9/9 |
| 真实 uvicorn 子进程 SIGTERM → 重启 → 审批续跑 | 单份提交回执、实际数量 10；无重复写入 |
| 阻塞工具、提交前/后崩溃、运行中取消、混合 8 请求、调度循环异常后停机 | 纳入上述核心测试 |
| `bash -n start_server.sh`、`git diff --check` | 通过 |

固定评测报告：[fixture](../evals/reports/runtime_hardening_fixture.json)、[chaos](../evals/reports/runtime_hardening_chaos.json)。fixture 衡量运行时可靠性；replay 衡量历史轨迹兼容性，均不是实时 LLM 准确率。

真实模型 12 条选择题和 6 条业务链的入口已提供，但本轮**未运行**；必须显式指定 remote 模式及总 token 上限。当前服务商可用性和模型业务准确率不在以上离线结果中。

## 审阅修复

独立审阅发现 3 项需要修复的问题，均新增行为测试，先复现失败再验证修复：

1. 崩溃后执行预算耗尽时，先结算已有回执再停止任务，保留真实提交结果。
2. 删除影响量在准备、审批、执行时均受旧任务与当前策略的较小阈值约束；服务端放宽不能扩张旧任务权限。
3. 读取已提交回执时同步结清动作状态，并追加幂等 reconcile 审计，不再遗留 running 动作。

另补充调度循环异常后的停机回收测试，确保异常不会跳过子进程终止；启动脚本给 uvicorn 请求排空与调度器停机留足等待时间。

## 执行裁定与边界

- 基线安装/路径故障属于已授权修复，直接实施；没有再次等待用户确认。
- 在干净发布副本的 worktree 实现，再逐文件比较原项目后同步；避免混入私有历史或覆盖无关修改。
- 成功写入测试增加显式 operator/env 和删除确认，反映有意收紧的契约；调用者也需要这些字段，拒绝测试保留。
- 父进程崩溃测试显式选择 `isolate_tools=False`；生产默认隔离。SDK 主动关闭隔离时不承诺同步工具强制终止。
- 单个调度循环负责回收活动执行进程，避免停机与运行循环同时修改执行池。
- 审阅未判断生产认证、多租户、分布式调度、真实平台事务，以及不遵守新协议的旧二进制；这些均在批准方案之外。真实平台仍需独立适配与验收。
- 保留一条既有 Pydantic V1 validator 弃用告警，测试未失败；未用“零告警”替代正确性验证。

可选 S5 框架对照、跨任务记忆、多 agent 与外部评测仓库集成均未纳入此次交付。详细操作见 [工作流指南](workflow-guide.md) 和 [架构边界](architecture-boundaries.md)。
