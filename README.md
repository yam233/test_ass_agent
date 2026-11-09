# TestOps Agent

基于可替换 LLM 的本地合成测试助手，支持礼物造数与查询、配置修改与回滚、批次清理和内置模拟脚本；提供审批、持久调度、取消、恢复和离线评测。

## 多步工作流入口

`/workflows` 提供原生工具调用、三重预算、逐步审批、持久化 checkpoint、配置回滚、批次清理、结果引用与评测。本轮五批加固增加策略约束、审计、上下文预算、持久队列和取消恢复。使用方法见 [多步工作流指南](docs/workflow-guide.md)，实际验收见 [改造验收记录](docs/runtime-hardening-acceptance.md)。`/agent/execute` 保留原单动作行为。

## 当前运行方式：平台 mock + 可替换模型

项目名称统一为 **TestOps Agent**，业务代码为 `testops`。显式传入 `business_code` 的客户端应使用该值；省略时继续使用默认业务。

原平台目前无访问权限。默认入口使用 SQLite 重建的有状态 mock，不连接旧数据库、后台或脚本仓库。样本为合成数据，支持范围依据现有工具元信息重建，不代表真实平台的完整契约。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-offline.txt
./start_server.sh start
```

默认只监听 `127.0.0.1:8002`，保留 `/agent/execute` 和 `/agent/langgraph/execute` 两个地址。`GET /health` 显示 mock、模型模式及是否使用真实 LangGraph。`stop/status/logs` 命令照常使用。

无需模型费用的演示：`LLM_MODE=offline ./start_server.sh start`。离线规则只覆盖下面列出的句式，不能作为 LLM 准确率结果。远程模式 API 失败会明确返回 `LLM_ERROR`，不会暗中退回规则解析。

模型配置放在已被 git 忽略的 `config/local/agent_secrets.json` 的 `secrets` 中，参照 example 文件；保留已有配置，不要覆盖凭证。设置 `LLM_MODE=remote` 并填写：

- `OPENCODE_API_KEY`：本地 Key。
- `OPENCODE_BASE_URL`：`https://opencode.ai/zen/go/v1`。
- `OPENCODE_MODEL`：默认 `deepseek-v4.1-flash`；可改为 `deepseek-v4-pro`。

OpenCode 请求包含稳定的会话路由头和项目客户端标识，参照[服务商接口要求](https://opencode.ai/docs/console/go/#where-can-i-use-it)。

也支持通用的 `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL`。同组环境变量优先于本地文件；通用配置优先于 OPENCODE 别名。Base URL 使用服务商完整前缀，程序仅追加 `/chat/completions`。修改后重启服务。Key 不写入 README 或跟踪配置。

### 本次 mock 覆盖范围

| 平台 | 已支持行为 | 规则模式示例 |
|---|---|---|
| 数据库 | 专属礼物、背包礼物发放及查询 | 给用户123发10个礼物301到背包；查询用户123的礼物记录 |
| 测试后台 | 活动时间保存及查询 | 把活动42的时间偏移到明天；查询活动42的时间 |
| 脚本仓库 | 内置脚本列表/源码、模拟送礼、执行记录 | 扫描测试脚本；用用户123给直播间8888送礼物10001，每次2个，执行3次；查询脚本执行记录 |

写操作先返回 `data.action_id`、完整动作快照和审批有效期（5 分钟）；带回该 ID，并使用相同 `context.operator`、`context.session_id`、`context.env` 回复“确认执行”。省略 session_id 时响应会生成一个，下一轮需要带回。模拟脚本只修改本地状态，不运行真实脚本。未覆盖的旧业务明确不支持；不将旧版功能清单当作 mock 支持清单。

```bash
curl http://127.0.0.1:8002/agent/execute -H 'Content-Type: application/json' \
  -d '{"user_input":"给用户123发10个礼物301到背包","context":{"operator":"tester","session_id":"demo","env":"uat"}}'
curl http://127.0.0.1:8002/agent/execute -H 'Content-Type: application/json' \
  -d '{"user_input":"确认执行","context":{"operator":"tester","session_id":"demo","env":"uat","action_id":"替换为上一步返回的动作ID"}}'
.venv/bin/python -m scripts.mock_state snapshot
```

状态默认在 `.mock_state/platforms.sqlite`，服务重启后保留；`MOCK_DB_PATH` 可指定隔离文件。`python -m scripts.mock_state reset` 清空该 mock 数据库（使用 `.venv/bin/python`）。reset 前停止服务，避免与正在执行的操作竞争；reset 同时清空动作记录、审批和平台回执，旧 action_id 随即失效。普通服务重启保留这些记录；缺参追问上下文仍只在内存。

故障在执行请求或确认请求的 `context.fault_id` 指定：`f_403`、`f_5xx`、`f_timeout`、`f_halfseed`、`f_response_loss`。超时是确定性错误模拟，不等待真实超时；半写只作用于礼物发放，返回 `partial_success` 与 expected/actual。`context.dry_run=true` 只生成计划。

### 写操作审批、幂等和重试

- 审批绑定操作人、会话、环境、工具与规范化参数。新参数必须创建新动作；`approved=true` / `execute_confirmed=true` 不再能批准 mock 写操作。
- “确认执行”批准指定动作；“取消执行”或“拒绝”使待执行动作失效；“重试执行”必须携带原 `action_id`。第一次只有一个未被替换的待审批动作时，可在同会话省略 ID；该会话发生过替换后必须明确 ID，避免延迟确认误批新动作。
- 相同 `request_id`（同操作人和会话）重放原始指令会复用动作，参数不同则返回 `REQUEST_CONFLICT`。新请求 ID 或不提供请求 ID会创建新动作。“再发一次”复制最近已完成的礼物动作，生成新 ID，并再次要求审批。
- 平台写入与按动作 ID 索引的回执在同一 SQLite 事务提交。多个进程重复执行同一动作，只有一次副作用。Agent 动作结果另行保存，因此可以测试平台提交后、Agent 记账前的崩溃窗口。
- `f_response_loss` 在平台提交后模拟丢响应，返回 `OUTCOME_UNKNOWN`。用原 ID 重试时先查平台回执，返回 `reconciled=true`，不重新发放。若提交前进程退出，SQLite 回滚，审批仍有效时可安全重试。
- 半写返回 5/10 和 `partial_success`；同动作重试仍返回 5/10，不自动补发。补发需要用户新建明确的补偿动作。
- 审批过期阻止新的写入，但仍允许读取已经提交的回执来核对结果。403 和确定性失败不盲重试；超时/500 可按 ID 显式重试。执行时再次检查当前工具白名单与环境限制。
- `dry_run=true` 只返回计划，不创建审批或执行记录，不能通过后续空白确认变成写入。

```bash
.venv/bin/python -m scripts.mock_state actions
.venv/bin/python -m scripts.evaluate_backpack --output /tmp/backpack-report.json
.venv/bin/python -m pytest tests/test_write_reliability.py tests/test_offline_runtime.py -q
```

固定回归定义在 `evals/backpack_cases.json`，按 SQLite 实际状态判分；改造前基线 `evals/backpack_baseline.json` 为 5/9，改造后 `evals/backpack_after.json` 为 9/9。这是离线规则与工程可靠性回归，不代表 LLM 准确率。

上述旧入口保证本地 mock 的单动作审批和安全重试；新增 `/workflows` 支持多步 checkpoint，见工作流指南。两种入口均不保证真实平台跨系统事务，也不覆盖全部旧平台接口。operator 是本地调用者传入的身份标识，不是生产身份认证；部署到多人环境前需要可信的认证与授权入口。

```bash
# 新增测试不访问外部平台或真实模型
.venv/bin/python -m pytest tests/test_offline_runtime.py -q
# 旧版架构测试需要完整旧运行依赖；固定离线模型避免费用
LLM_MODE=offline .venv/bin/python -m pytest tests_legacy/test_agent_architecture_guards.py -q
```

旧网关可显式用 `AGENT_APP=api.mcp_http_server:app` 启动，但仍需要旧依赖与平台权限，不属于当前 mock 运行模式。下方保留历史业务和架构说明。

## Main Features

- 用户信息查询：用户 ID、手机号、邮箱、直播间 ID、验证码。
- 礼物发放：专属 tab、直播间专属、随机礼物、背包礼物。
- 钻石充值：支持用户 ID、手机号、邮箱。
- 奖池配置：查询奖池、调整礼物权重、调整大奖权重。
- 后台功能搜索：Grafana、MongoDB、MySQL 地址搜索。
- 配置核验：外观配置、奖励配置。

执行类操作默认需要二次确认，避免误发放、误充值或误改配置。

## Project Structure

```text
agent_core/                 # Agent 主链路、全局能力层、Skill 标准范式
agent_core/layers/          # 感知解析、安全配置、执行保障、记忆、格式化
agent_core/langgraph_agent/ # Python + LangChain/LangGraph 新主链路
agent_core/skills/          # DB/后台/脚本 Skill 标准家族
agent_plugins/testops/     # 测试助手业务插件与 skill
api/                        # HTTP 入口
business_logic/             # 用户、礼物、奖池、配置核验等业务服务
config/                     # 框架配置和业务配置
mcp_servers/                # 数据查询相关 MCP/HTTP 服务
references/                 # LLM prompt 参考材料
regression_tests/           # 手工/批量回归脚本和用例
scripts/                    # 维护脚本
tests/                      # 单元测试
utils/                      # 通用基础设施工具
```

## Runtime Flow

```text
输入
 -> 感知解析：闲聊直出，业务指令进入 Skill 路由
 -> 权限校验：查询开放，写操作/脚本执行需要确认
 -> Skill 匹配与参数解析
 -> 缺参追问或执行
 -> 结果格式化
 -> 短期/长期记忆更新
```

新架构入口采用 Python + LangChain/LangGraph 分层：

- LLM 接入层：`DeepSeekLLM` 封装 DeepSeek，Few-Shot Prompt 做意图识别；无依赖或无密钥时自动降级到规则解析。
- Tool 层：数据库查/写/导出、后台元信息、测试脚本扫描/读取/执行均按 LangChain `BaseTool` 风格封装。
- 公共组件：Pydantic 参数模型、tenacity 重试适配、统一结果格式化。
- 记忆层：短期保留 5-8 轮上下文，长期预留 Chroma Skill 元信息索引。
- 图编排：`parse -> permission -> tool_or_clarify -> memory -> response`，未安装 LangGraph 时使用同构手动执行链。

## Local Secrets

敏感配置不要提交到仓库。复制示例文件后在本地填写：

```bash
cp config/local/agent_secrets.example.json config/local/agent_secrets.json
```

`config/local/agent_secrets.json` 已加入 `.gitignore`，可放数据库密码、后台凭证和 GitLab Token。环境变量仍然优先，例如 `DEEPSEEK_API_KEY`。

## API Example

```bash
curl -X POST http://localhost:8002/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"business_code": "testops", "user_input": "查询用户9075333的信息"}'
```

新架构灰度入口：

```bash
curl -X POST http://localhost:8002/agent/langgraph/execute \
  -H "Content-Type: application/json" \
  -d '{"user_input": "扫描测试脚本", "context": {"env": "uat", "operator": "tester"}}'
```

执行类示例：

```text
给用户9075566发礼物20123到专属tab
给用户9075566发10个礼物301到背包
给手机号15000000490充值500万钻石
```

系统会先返回待确认计划，回复“确认执行”后才会执行。

## Tests

```bash
python -m pytest tests_legacy/test_agent_architecture_guards.py -q
python -m compileall agent_core api agent_plugins tests utils
```

完整手工回归用例在 `regression_tests/test_ml.md`。

## Development Notes

新增或调整 skill 时，优先检查：

- `config/business/testops/skills_registry.json`
- `config/business/testops/mcp_registry.json`
- `agent_plugins/testops/skills/`
- `agent_plugins/testops/local_handlers.py`

执行类 skill 需要关注参数校验、实体存在性校验、二次确认和审计记录。

当前迁移状态：礼物发放类、后台元信息查询、通用结构化查询、数据库只读校验、测试脚本扫描/源码查询/受控执行已接入 `agent_core/skills` 标准范式；LangGraph 新主链路已具备独立入口，可逐步承接旧 `/agent/execute` 流量。

## 独立环境验证

核心安装：`python -m pip install -r requirements-core.txt`，运行 `python -m pytest tests -q`。
兼容图入口可安装 `requirements-offline.txt`；无 LangGraph 时旧入口使用明确标注的手动编排。
旧架构测试另装 `requirements-legacy-test.txt`，运行 `python -m pytest tests_legacy -q`。
两组测试均使用合成平台和假传输，不需要数据库权限或模型凭证；CI 在仓库外创建虚拟环境。

写操作要求显式 `operator` 与 `env`。工作流工具授权在 `config/workflow_policy.json` 配置；默认仅列出的本地演示身份可写，未知身份只读。`allowed_tools` 只能收窄权限，续跑不能扩大原任务权限；本地身份声明不替代认证。

运行与代码边界见 [架构边界](docs/architecture-boundaries.md)。工作流 HTTP 默认等待结果，`dispatch=queued` 返回 202；两种模式共用单机持久队列和两个执行槽。
