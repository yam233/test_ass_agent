# Offline runtime implementation plan

Goal: restore a runnable project using stateful platform mocks and a configurable LLM, preserving the existing LangGraph orchestration.

Scope approved in conversation: replace unavailable platforms; replace unavailable model API. No new autonomous loop or checkpoint framework in this increment.

Architecture: local SQLite mock adapters behind existing metadata/tools; lightweight offline HTTP entry point with the existing execute URL; OpenAI-compatible chat transport with explicit offline mode and observable failures. Legacy entry point remains available explicitly.

Constraints: preserve existing uncommitted changes; credentials stay in ignored local configuration; no real platform calls in mock mode; use a project venv and implement inline to conserve tokens.

- [x] Test then implement durable mock writes/queries, confirmation gating, reset and deterministic failure injection.
- [x] Test then implement configurable model/base URL/key and explicit offline mode; transport errors must not masquerade as model success.
- [x] Wire HTTP and command-line startup, document supported mock scope and model configuration.
- [x] Run offline integration and existing architecture tests; review changed paths and report limitations.

Review focus: missing required params; unauthorized writes; persistence after reopen; partial writes; failed model credentials; unsupported tools must fail closed.

Baseline: existing tests cannot collect in system Python (aiohttp missing). Dependencies will be installed in .venv. Work proceeds on codex/offline-mock-llm with the existing working changes preserved.

Validation: 17 new regression tests and 34 existing architecture tests passed in the local venv; compilation and shell syntax checks passed. Actual HTTP socket smoke passed for pending confirmation → write → query. OpenCode remote parsing → mock query passed with deepseek-v4.1-flash. Credentials saved only in ignored configuration with mode 0600.

Review fixes: copy request context to avoid confirmation leakage; preserve full timestamps; route script-history queries before script execution. Pending approvals remain in memory; persistent task recovery/idempotency are explicitly out of scope.

Dependency note: official wheel host returned TLS errors; the pinned LangGraph runtime was installed through the Tsinghua PyPI mirror. Real LangGraph compilation exposed an existing state/node name collision (permission); renamed the node to permission_check and verified actual graph execution. The manual compatibility chain was also independently verified. No legacy platform services were contacted.

Final validation: reran the 17 new and 34 existing tests with real LangGraph installed. Permission error creation now happens in the node, not the conditional router (router mutations are not persisted by LangGraph). Existing Pydantic v1-validator deprecation warning remains. Local venv includes py==1.11.0 for compatibility with the machine’s pre-existing pytest-html plugin. No commit/push performed; existing working changes preserved.
