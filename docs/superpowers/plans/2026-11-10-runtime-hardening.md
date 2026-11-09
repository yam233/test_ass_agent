# TestOps Agent Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 分五批完成两轮评审中有效的可靠性、治理、评测和单机调度改造。

**Architecture:** 保留 WorkflowRuntime、ActionStore 和事务回执。先修契约，再抽出策略、上下文及评测职责，最后以持久 job 表和受监督进程增加调度；旧入口保留兼容。

**Tech Stack:** Python 3.10+ 兼容语法、FastAPI、Pydantic 2、SQLite、httpx、pytest；不引入外部分布式队列。

**Spec:** ../specs/2026-11-10-runtime-hardening-design.md（已实施；验收记录见 ../../runtime-hardening-acceptance.md）。

## Global Constraints

- 全程保持平台 mock；模型接口可替换。当前不是生产多租户平台。
- 生产禁写保留为不可被普通配置放开的全局约束。
- 预演转正式执行必须新建任务并重新审批。
- 默认仅清理终态任务保留 7 天后的 refs；活动和待批任务引用保留。
- 默认模型输入硬限 32 KiB；每页最多 100 行且 16 KiB UTF-8 响应。
- 默认 1 个调度器、2 个执行进程、最多 100 个排队 job。
- 默认单次工具 5 秒上限、终止与回收宽限 1 秒；优雅停机最多 10 秒。
- 不提交凭证、运行数据、私有历史，不改写已发布历史。

## Review Focus

1. 恶意或遗漏的 resume context 不能扩大授权、把预演变成执行（任务 2、3）。
2. 提交后超时/取消/崩溃不能换动作重发；已有写入必须如实报告（任务 4、8）。
3. 旧 checkpoint 与升级后服务混用时必须迁移或拒绝，不能默认错字段继续写（任务 2、5）。
4. 大中文单行、工具配对和必要任务约束不能被上下文裁剪静默破坏（任务 2、6）。
5. 清扫、审批、取消、恢复并发时，旧 JSON 保存不能覆盖新控制状态（任务 5、8）。

## 任务执行约定

每个任务先写下列行为测试并运行确认暴露当前缺口，再实现；通过定向测试后检查 diff，批次末跑核心及兼容回归。新增测试针对可观察结果，不复述实现。每个任务单独提交相关路径；不自动 push。

## 第一批

### Task 1：干净安装与测试入口

**Files:** 修改 requirements-offline.txt、pytest.ini、tests/conftest.py、tests/test_write_reliability.py、agent_core/workflow.py、agent_core/langgraph_agent/__init__.py、api/offline_server.py；新增 requirements-core.txt、requirements-legacy-test.txt、.github/workflows/tests.yml；旧架构测试迁入 tests_legacy/；必要时抽 agent_core/llm_client.py 并保留旧 import 兼容。

**Interfaces:** 核心环境提供 WorkflowRuntime 与工作流 API；完整依赖另支持兼容/旧架构入口。新环境不要求虚拟环境名为 .venv。

- [x] 在仓库外 venv 安装核心依赖，运行 `python -m pytest tests -q`，定位导入耦合并修复；旧测试以 `python -m pytest tests_legacy -q` 独立验证。
- [x] 把两处子进程解释器改为 sys.executable；验证提交前/后崩溃测试实际启动子进程且保持原语义。
- [x] CI 分核心和完整配置；无远程凭证执行，README 给出两套精确命令及覆盖边界，兼容入口不支持时返回明确说明。
- [x] 两套环境全部通过后提交，不靠 collect_ignore 隐藏失败。

### Task 2：引用分页、不可升级的预演、最小状态版本

**Files:** 修改 agent_core/workflow.py、workflow_store.py、workflow_contracts.py、workflow_platform.py、api/offline_server.py；新增 agent_core/workflow_state.py、tests/test_workflow_contract_regressions.py。

**Interfaces:** `migrate_state(payload: dict) -> dict`；状态新增 schema_version=1、mode；`read_ref` data 增加 returned_count/next_offset/truncated；超大单行失败码 ROW_TOO_LARGE；预演 status=planned/stop_reason=dry_run。

- [x] 测试 runtime 读取 100 条小行保留全部行且 refs 不增加；中文大页分片无重漏，超大单行明确失败。
- [x] 测试 dry_run 创建/续跑均无 actions、receipts 和业务副作用，省略/修改 flag 不能升级；只预览第一个写步骤。
- [x] 测试无版本 v0→v1 幂等迁移、未知新版本拒绝；实现分页限额和持久 mode。
- [x] 运行上述测试及 tests/test_workflow_recovery.py、tests/test_write_reliability.py，更新契约/文档并提交。

## 第二批

### Task 3：服务端策略与风险驱动审批

**Files:** 新增 agent_core/workflow_policy.py、config/workflow_policy.json、tests/test_workflow_policy.py；修改 workflow.py、workflow_platform.py、action_store.py、api/offline_server.py 及旧入口上下文校验。

**Interfaces:** `resolve_policy(context: dict, saved: dict | None) -> dict` 返回有效工具集、policy_version、破坏性操作阈值；客户端限制只收窄；准备、审批、执行共用校验。破坏性确认通过 resume 的 `confirm_effect='delete_batch'` 和 `snapshot_hash` 绑定动作。

- [x] 测试缺 env/operator 的写入拒绝、prod 拒绝、未知工具拒绝；读默认身份不能自动获写权限。
- [x] 测试 resume 移除 allowed_tools 无法扩权，服务端撤销后旧动作不能执行，客户端伪造 grant 无效。
- [x] 测试更换 operator/session_id/env 的审批、续跑、取消和读取均拒绝；同 scope 操作继续兼容，不提供代批能力。
- [x] 测试 cleanup 缺删除确认、快照变化、影响量>1000 均拒绝；有效单批删除按绑定动作执行。
- [x] 更新调用示例和权限边界说明，通过审批/幂等回归后提交。

### Task 4：审计与模型可靠性

**Files:** 新增 agent_core/workflow_audit.py、tests/test_workflow_audit.py、tests/test_workflow_model_retries.py；修改 action_store.py、workflow_platform.py、workflow.py、workflow_model.py。

**Interfaces:** `append_event(db, event: dict) -> None` 在调用者事务内追加，事件有唯一 event_id；模型结果/异常含 attempt、usage、finish_reason 和版本指纹。

- [x] 注入审批提交/写回执后的崩溃，验证审批与回执事件不丢、不重复，且可还原 actor/action/args。
- [x] 假传输覆盖 429→成功、5xx 耗尽、鉴权立即失败、length→重试，以及重试预算不足；不得调用真实模型。
- [x] 输出 cap 默认1024，length 重试最多1次且不超2048；暂态重试最多2次、退避1/3秒；所有尝试计入预算和 trace。
- [x] 哈希覆盖 SYSTEM、工具契约与有效模型配置，并保存脱敏版本 artifact；验证变更指纹和历史可追溯。
- [x] 定向与审批恢复回归通过后提交。

## 第三批

### Task 5：生命周期、维护与状态并发

**Files:** 修改 workflow_state.py、workflow_store.py、action_store.py、scripts/mock_state.py；新增 scripts/workflow_maintenance.py、tests/test_workflow_lifecycle.py。

**Interfaces:** `save(state: dict, expected_revision: int) -> int` 冲突返回 STATE_CONFLICT；`expire_approvals(now: float) -> int`；`gc_refs(now: float, retention_days: int=7, dry_run: bool=True) -> dict`。取消控制独立持久化，不随 checkpoint 覆盖。

- [x] 测试旧任务迁移、审批与过期并发、取消标记与旧 revision 保存冲突、未知 schema 拒绝。
- [x] 测试 GC 只清终态过期 refs，活动引用/未对账动作/回执保留；reset dry-run 零变化且运行中实际 reset 被拒绝。
- [x] 实现维护命令、索引及迁移事务，核心与恢复套件通过后提交。

### Task 6：有分区预算的消息构造

**Files:** 新增 agent_core/workflow_context.py、tests/test_workflow_context.py；修改 workflow.py、workflow_model.py。

**Interfaces:** `build_context(state: dict, tool_catalog: list, input_limit_bytes: int=32768) -> dict` 返回 messages、context_bytes、compaction_events；必要内容超限返回明确预算错误。

- [x] 以200条历史构造上下文，验证UTF-8总量、分区统计、完整工具消息对、任务及澄清保留。
- [x] 测试旧观察含指令文本仍按数据处理、巨大必要输入明确停止，读引用页仍可用于末步核验。
- [x] 用10–20步脚本轨迹验证实际运行；修正system摘要布局，跑核心工作流套件后提交。

## 第四批

### Task 7：统一评测入口与证据导出

**Files:** 新增 evals/environment.py、evals/runner.py、evals/models.py、evals/environments/backpack.py、evals/environments/workflow.py、scripts/export_workflow_trace.py、tests/test_eval_runner.py；修改旧三套评测脚本使其委托公共组件，扩充 evals/workflow_cases.json。

**Interfaces:** Environment `reset(seed:int)->None / snapshot()->dict / apply(action:dict)->dict / invariants()->list[dict]`，apply 委托真实 runtime/platform，禁止绕审批；runner 输出逐次 JSONL 与独立汇总。模型模式 fixture/chaos/replay/remote。

- [x] 先用固定现有用例比较新旧 runner 的原始状态判分完全一致，再迁移入口；baseline hash 不符拒绝比较。
- [x] 新增独立预期、读故障、6条3–5步链路；固定种子 chaos 同时统计误拒和漏拦，验证全部拒绝不能得高分。
- [x] 测试 replay 动态ID映射和观察不匹配拒绝；真实重复与复用记录不能混计；副作用分提交/尝试/新动作。
- [x] 提供 `python -m evals.runner --suite workflow --model fixture --repeat 4`；remote 缺显式token上限拒绝运行。范围固定12条选择+6条链路，小批验收时另行执行。
- [x] 验证按scope导出trace/audit无凭证，离线完整回归通过后提交。

## 第五批

### Task 8：持久 job、受监督工具执行与取消恢复

**Files:** 新增 agent_core/workflow_jobs.py、agent_core/workflow_runner.py、agent_core/tool_executor.py、tests/test_workflow_jobs.py、tests/test_workflow_scheduling.py；修改 workflow.py、workflow_store.py、api/offline_server.py、start_server.sh。

**Interfaces:** `enqueue(task_id:str)->dict` 幂等；`request_cancel(task_id:str,context:dict)->dict` 只持久化控制指令；`execute_tool(request:dict,deadline:float)->dict` 运行隔离工具并收集结果。HTTP `dispatch=queued` 返回202，默认inline等待同一队列的本段结果，不绕过执行池。

- [x] 写测试：8任务提交、并发<=2、队列满无孤儿、重复投递不重复执行、批准等待不占worker；API状态/取消在慢工具期间仍响应。
- [x] 混合 inline/queued 请求仍满足并发<=2；两种模式共用锁和恢复；直接 SDK 持锁时服务恢复扫描不得抢占。
- [x] 实现任务/job原子创建、批准/job原子激活、单调度器锁与独立控制字段；重启扫描和任务锁阻止双执行者。
- [x] 工具子进程内创建SQLite连接，5秒deadline+1秒回收宽限；测试sleep(200)及提交前后kill，确认旧执行者消失才重试/恢复。
- [x] 测试排队取消、待批取消、执行中取消、提交后取消；对账如实记录既成副作用，未知结果进入reconciliation_required。
- [x] SIGTERM 10秒宽限；测试重启恢复、锁仍持有不抢跑、丢失执行区间保守预算、不重复提交。
- [x] 全套核心/兼容/评测回归通过；更新部署边界和运行命令后提交。发布仍走脱敏副本，不推送原工作区历史。

## 可选后续

S5 同契约同用例的 LangGraph 对照另立实验；生产认证、多租户、跨任务记忆、plan、多agent和外部评测仓库集成均不作为本计划验收项。

## 完成标准

每批有命令、实际结果和提交记录；已验证缺陷有行为回归；远程验收若未运行明确标“未运行”，不得用fixture/replay代替。第五批完成后定位为单机可调度运行时，仍不宣称真实平台端到端事务或生产多租户安全。
