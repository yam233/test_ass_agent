# TestOps Agent

面向测试运维场景的单 Agent Runtime。当前使用 SQLite 有状态 mock，支持查询、礼物造数、配置修改与回滚、批次清理、内置模拟脚本；所有写入都经过审批。

**主入口是 `/workflows`，编排内核为手写 Python Runtime。** 模型负责选择工具，Runtime 负责预算、安全闸门、持久化和续跑，工具层负责实际操作。

- [架构与模块职责](docs/architecture.md)：从哪里读代码、依赖如何流动、哪些边界刻意保留。
- [工作流使用指南](docs/workflow-guide.md)：请求、审批、澄清、查询、取消与恢复。
- [可用性验收](docs/usability-acceptance.md)：既有功能测试及真实模型 mock 小样本。
- [兼容入口与历史说明](docs/legacy-runtime.md)：旧入口用法和历史平台能力，独立于主工作流。

## 启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-core.txt
LLM_MODE=offline ./start_server.sh start
curl http://127.0.0.1:8002/health
```

主工作流只需核心依赖；需要真实 LangGraph 兼容执行时再安装 `requirements-offline.txt`。

默认监听 `127.0.0.1:8002`；支持 `./start_server.sh stop/status/logs`。状态保存在 `.mock_state/platforms.sqlite`，可用 `MOCK_DB_PATH` 指定隔离文件。重启保留任务、审批和回执。

`offline` 使用有限句式的规则模型，适合演示和回归。远程模型需要显式配置，接口失败不会暗中退回规则解析。

## 创建与审批任务

```bash
curl http://127.0.0.1:8002/workflows -H 'Content-Type: application/json' \
  -d '{"user_input":"给用户123发10个礼物301到背包，然后查询本批次核验数量","context":{"operator":"tester","session_id":"demo","env":"uat"}}'
```

写操作返回 `status=approval_wait`、`task_id` 和 `pending.action_id`。核对动作快照后，对同一任务提交审批：

```bash
curl http://127.0.0.1:8002/workflows/TASK_ID/resume -H 'Content-Type: application/json' \
  -d '{"context":{"operator":"tester","session_id":"demo","env":"uat"},"action_id":"ACTION_ID","decision":"approve"}'
```

替换上面的两个 ID。每次新写操作单独审批；清理还需要二次确认和预检快照哈希，详见使用指南。缺参会进入 `clarification_wait`，向同一 `/resume` 地址传 `reply`。默认等待任务执行到完成或需要交互；传 `dispatch="queued"` 可在入队后返回202。

最终结果由工具记录和实际回执生成，包含写入、读取和核验证据；`completed` 不等于任意自然语言目标已经得到完整语义验证。

## 入口边界

| 入口 | 职责 |
|---|---|
| `/workflows`、`/{task_id}/resume` | 主工作流创建、澄清、审批与续跑 |
| `/workflows/{task_id}/status`、`/refs`、`/cancel` | 主工作流状态、引用与取消 |
| `/health`、`/` | 返回主链路状态，旧链路状态放在 `compatibility` 字段 |
| `/agent/execute`、`/agent/langgraph/execute` | 保留的单动作兼容链路 |

健康检查的顶层 `orchestrator` 为 `workflow_runtime`，`llm_mode` 描述 HTTP 工作进程的默认模型配置，`model_scope=configured_worker_default`。它不调用模型服务，也不证明服务连通性。兼容 Agent 未初始化时，`compatibility.initialized=false`，编排和模型信息为 null。它不会把主工作流误报为 LangGraph。

## 模型配置

本地配置路径为被 Git 忽略的 `config/local/agent_secrets.json`，参照同目录 example 文件；已有配置请保留。远程模式设置 `LLM_MODE=remote`，配置以下一组字段：

- 通用接口：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
- OpenCode 别名：`OPENCODE_API_KEY`、`OPENCODE_BASE_URL`、`OPENCODE_MODEL`。

同组环境变量优先于本地文件，通用字段优先于 OpenCode 别名。Base URL 使用服务商完整前缀，客户端追加 `/chat/completions`。当前配置示例为 `https://opencode.ai/zen/go/v1`、`deepseek-v4.1-flash`。凭证只放本地配置或环境变量。

共享客户端位于 `agent_core/model_client.py`，`DeepSeekLLM` 是保留的兼容类名，传输支持 OpenAI 兼容接口。默认依赖由 `workflow_factory.py` 统一组装。

## 验证与边界

```bash
# 核心测试
.venv/bin/python -m pytest tests -q
# 完整兼容依赖安装后，还可运行历史架构测试
.venv/bin/python -m pytest tests tests_legacy -q
# 固定回归与故障评测，不调用付费模型
.venv/bin/python -m evals.runner --model fixture --repeat 4
.venv/bin/python -m evals.runner --model chaos --seed 17 --repeat 4
```

平台当前均为合成 mock；没有连接旧数据库、后台或脚本仓库，也不运行任意脚本。SQLite 内的写入与回执原子提交，不代表真实外部平台具备同样的事务保证。`operator` 是本地调用者标识，不能替代部署到多人环境所需的身份认证。

项目保持单 Agent、串行工具、单主机调度与 SQLite；不包含多智能体、前端、通用数据库适配框架或真实平台接入。
