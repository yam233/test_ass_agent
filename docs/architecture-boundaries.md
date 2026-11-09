# TestOps Agent 运行与代码边界

当前交付是 Linux/macOS 上的单机合成平台运行时。平台只修改本地 SQLite；operator 是本地身份声明，不是生产认证。未实现生产多租户、跨系统事务、任意脚本执行或分布式 worker。

| 路径 | 职责 |
|---|---|
| agent_core/workflow*.py、model_call.py、tool_executor.py | 新工作流：状态、策略、上下文、审计、调度和受监督执行 |
| agent_core/action_store.py、mock_platforms.py | 新旧入口共用的合成状态、审批和事务回执 |
| api/offline_server.py | 默认本地服务；新工作流和兼容单动作入口 |
| agent_core/langgraph_agent、offline_runtime.py | 可选图编排/手动兼容入口，保留旧行为范围 |
| business_logic、agent_plugins、mcp_servers、api/mcp_http_server.py、utils | 继承的业务与真实平台适配代码，不属于默认 mock 支持清单 |
| tests / tests_legacy | 核心回归 / 显式依赖的旧架构回归 |
| evals/runner.py、environment.py、environments、models.py | 统一评测入口、环境边界、脚本与错误决策、轨迹回放 |

运行时配置：服务端 policy 文件决定工具授权，prod 全局禁写。模型密钥仅放忽略的本地配置或环境变量。使用 requirements-core.txt 安装核心；requirements-offline.txt 增加图入口依赖；requirements-legacy-test.txt 用于完整旧架构测试。

调度：一个服务进程持有调度器独占锁，默认两个任务执行进程；每个任务的同步工具由受监督子进程运行。任务/审批与 job 激活事务提交。人工等待不占执行槽；取消仅阻止后续步骤，已提交写入按回执报告。最多等待 10 秒优雅停机，再终止并回收执行组；重启先检查独占锁与回执。

直接 Python SDK 调用仍有任务锁，服务不会抢占；SDK 的并发不属于 HTTP 池上限。默认工具隔离；显式 isolate_tools=False 仅适合可信、能自行保证时限的嵌入式执行或父进程崩溃测试，此时不承诺强制终止同步工具。

已有提交是实际交付快照；后续提交按真实改造批次记录，不重建虚构历史。框架对照 S5 与其他仓库的评测适配属于后续可选实验。
