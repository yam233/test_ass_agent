# 多步测试工作流

当前交付的是本地合成 mock 环境。数据库、测试后台和脚本仓库都不会连接原平台；脚本工具只改变 SQLite 中的模拟数据。旧 `/agent/execute` 保持单动作兼容，新 `/workflows` 支持模型根据上一步工具结果继续执行。

## 启动与最短体验

```bash
# 无模型费用，支持文档中的固定示例句式
LLM_MODE=offline ./start_server.sh start
# 使用已配置的真实模型时改为 LLM_MODE=remote；已有服务需先 stop
```

```bash
curl http://127.0.0.1:8002/workflows -H 'Content-Type: application/json' -d '{
  "user_input":"给用户123发10个礼物301到背包，然后查询核验",
  "context":{"operator":"tester","session_id":"demo","env":"uat"},
  "budget":{"max_steps":16,"max_tokens":60000,"max_seconds":120.0}
}'
```

响应 `status=approval_wait`，其中 `task_id` 标识整个任务，`pending.action_id` 标识当前待批准写操作。检查 `pending.snapshot` 中的工具、参数、风险与预计影响后：

```bash
curl http://127.0.0.1:8002/workflows/TASK_ID/resume -H 'Content-Type: application/json' -d '{
  "context":{"operator":"tester","session_id":"demo","env":"uat"},
  "action_id":"ACTION_ID","decision":"approve"
}'
```

每次新写操作都返回独立审批；查询自动继续。拒绝用 `decision=deny`。缺参时返回 `clarification_wait`，向同一 resume 地址提交 `{"context":{...},"reply":"10个"}`。每个请求都必须使用相同操作人、会话和环境。未提供 session_id 的创建请求会生成并返回 session_id，后续必须带回。

进程中断后，用原 task_id 调 resume，仅传 context 即可。程序从持久化 pending 步骤继续；已经完成的步骤不再执行，已提交但丢失响应的写操作先查平台回执。审批等待状态不会被无参数 resume 自动批准。

状态查询：`POST /workflows/TASK_ID/status`，请求 `{"context":{...}}`。本地 Swagger 位于 `/docs`，完整 HTTP 契约在 `contracts/http.openapi.json`。

## 工具范围与权限

| 工具 | 风险 | 行为 |
|---|---|---|
| list_scripts | read | 列出内置 send_gifts |
| query_config | read | 读取 gift_multiplier / maintenance_mode |
| query_data | read | 查询当前操作人、会话、环境的 gifts / script_runs |
| update_config | write_rev | 修改配置，保存 before/after/version |
| seed_test_data | write_rev | 向指定用户背包发放测试礼物，返回 batch_id |
| cleanup_data | write_destr | 清理本会话创建的单个批次，显示预计数量 |
| run_script | write_rev | 模拟执行 send_gifts，不执行任意代码 |
| ask_clarification | meta | 持久化追问并等待补充 |
| rollback_config | write_rev | 按 change_id 回滚；如果已有后续修改，拒绝覆盖 |
| read_ref | read | 分页读取本任务的大结果引用 |

8 个核心工具加 rollback_config、read_ref 两个辅助工具。工具含严格参数 schema、适用/不适用说明与返回值。`contracts/tools.json`、`fixtures/workflow.json` 为合成契约与样本，不代表找回的生产契约。运行 `python -m scripts.export_contracts` 可重新导出。

审批有效期 5 分钟，绑定 actor/session/env/tool/args，布尔 approved 不生效。生产环境 prod 禁写；环境只接受 uat/staging/dev/test/prod。清理、回滚也要审批，不能跨用户/会话使用 batch_id/change_id。配置在同一环境共享，因此回滚检查版本，避免覆盖他人的后续修改。actor 仍是调用者提交的本地身份，当前服务不具备生产认证。

## 预算、终止与故障

`max_steps` 限制模型决策次数；`max_tokens` 限制模型 token 预算；`max_seconds` 限制累计活动运行时间（审批/澄清等待不计时）。预算随任务持久化，重启不能刷新。模型调用前使用 UTF-8 字节数加消息开销保守预留，收到 usage 后按实数结算；没有 usage 时保留预留量。它可能提前停止，不是精确分词器。进程未正常结束的运行区间按重启时的经过时间保守计费。

终止原因包括 finished、denied、max_steps、budget、timeout、loop、auth、bad_args、partial、model_error、no_evidence、unrecoverable。没有成功写入改变状态时，相同只读调用第二次即拦截；写入后可再次查询核验。相同写工具及参数在整个任务内禁止重复；显式重试属于同一步，不会误计为模型循环。需要再次发放相同数据时新建任务，不能用循环绕过审批。

- TRANSIENT / TIMEOUT：最多重试 2 次，等待 1s、3s；每次先查回执。
- 权限失败：立即停止，不重试。
- BAD_ARGS：将错误与 hint 回给模型，最多修复 1 次；修复写参数后重新审批。
- AMBIGUOUS：暂停并向用户澄清。
- 半写：返回 partial_success，不自动补发或回滚。补偿操作必须明确提交并审批。

创建请求的 context 支持确定性 fault_id：f_403 / f_5xx / f_timeout / f_halfseed / f_response_loss / f_bad_type / f_ambiguous；可用 fault_count 限制前 N 次工具执行注入。fault 配置会写入任务，不允许续跑请求悄悄改变原场景。f_timeout 模拟写入前超时结果；真实模型等待受运行时墙钟预算限制。

## 上下文与可观察性

大型结果存入 scoped refs，模型只收到 ref_id、行数、字段和最多三条样本；保留最近 5 步详细结果，更早步骤只保留摘要。读取接口：`POST /workflows/TASK_ID/refs`，请求 `{"context":{...},"ref_id":"...","offset":0,"limit":20}`，limit 上限 100。模型使用同名 read_ref 工具。

任务响应和持久化 trace 包含模型、prompt 版本、参数 hash、耗时、token、provider 成本字段、结果、终止原因。未提供金额/币种时保持空值，不将未知成本报告成零。SQLite 表 workflow_tasks / workflow_refs / actions / platform_receipts / workflow_config / workflow_changes 可直接复核。配置审批保存预检版本；审批期间配置变化会返回 CONFLICT，避免覆盖新值。配置和清理副作用与回执同事务提交；任务 checkpoint 单独保存，测试覆盖两者之间的进程退出。

同一任务使用操作系统文件锁，跨进程并发 resume 返回 RESOURCE_BUSY；进程退出后自动释放。支持 macOS/Linux，本实现使用 fcntl，不支持原生 Windows。reset 必须先停止服务；reset 同时清空任务、引用、动作、回执、配置与模拟业务数据。

## 验证与报告

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.evaluate_workflow --repeat 4
.venv/bin/python -m scripts.evaluate_backpack --output evals/backpack_after.json
# 下面命令会访问已配置模型；默认最多12条选择案例 + 两条各至多4次模型调用的完整链
.venv/bin/python -m scripts.evaluate_model --remote
```

pytest 只收集 tests/，避免误执行历史目录中需要旧平台的脚本。架构测试强制离线；远程传输测试使用 httpx 假传输，不付费。

- workflow_after.json：30 条工程场景（12 正常 / 8 澄清或错误输入 / 6 故障 / 4 对抗），默认各运行 4 次；按原始 SQLite 数据判分。
- model_acceptance.json：真实模型选择与参数验收、两条完整业务链。首轮输出上限较小出现一条未解析响应；补测提高输出空间，复用已经通过的 10 条，新增或重测两条。不是一轮全新的 12 条独立测试。
- backpack_baseline.json / backpack_after.json：同一批 9 条老场景的 before/after，5/9 → 9/9。新 30 条没有可运行的历史版本，不将不同集合的分数拼成提升率；以后用 `--baseline` 对比相同 case_set_hash 的报告。

指标包括任务验收通过率、工具选择匹配率、参数非法率、平均步骤、重复副作用、恢复成功率和每任务 token/成本。工程回归中的模型决策是可控 fixture，工具匹配率不能代表 LLM 准确率；真实选择准确率看 model_acceptance。all_runs_pass_rate 是连续多次全通过的稳定性，at_least_one_pass_rate 是至少一次通过，两者不要混称 pass@4。

范围：四批运行时改造已实现。没有接回真实平台，没有生产身份系统、任意 SQL/脚本执行、前端、多智能体或自研/LangGraph 框架对照实验。旧单动作 LangGraph 入口保留，新多步入口为显式 Python 循环；尚未用两种框架实现同一工作流做对照。

### 预演与引用页

`context.dry_run=true` 固定为任务模式：运行到第一个写意图时返回 `planned` 和影响预览，不创建可审批动作。后续 resume 无法把它变成正式执行；正式执行需新建任务。预演不声称已验证依赖该写结果的后续步骤。

`read_ref` 每页最多 100 行、16 KiB UTF-8 响应，返回 `returned_count/next_offset/truncated`。使用 `next_offset` 继续读取；单行超限返回 `ROW_TOO_LARGE`。读取页不会再次生成引用。

### 服务端策略

创建任务时固定 operator/session_id/env，续跑与审批需使用相同 scope。写操作显式提供 operator/env；服务端 `config/workflow_policy.json` 决定工具权限，客户端 allowed_tools 仅能收窄。创建时权限与当前权限取交集，撤销即时生效。

`cleanup_data` 还需在 resume 顶层传 `confirm_effect: "delete_batch"` 和待批响应中的 `snapshot_hash`；默认影响量上限 1000 个礼物。执行前影响量变化会拒绝旧审批。prod 禁写不能通过策略配置解除。本地身份声明不等于生产认证。
