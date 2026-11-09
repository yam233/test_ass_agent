# Four-batch Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Continue all four authorized batches without approval pauses between batches.

**Goal:** Deliver the agreed four batches: real-model contracts, bounded multi-step tool loop, durable recovery/compensation, and measurable evaluation.
**Architecture:** Preserve existing single-action LangGraph API. Add a durable workflow API using native function calls and the existing SQLite action/receipt authority. Independent task state, refs, traces, and budgets survive restart. Local mock only; no old platform connections.
**Tech Stack:** Existing Python, Pydantic, SQLite, FastAPI, httpx; no new runtime dependency.
**Spec:** User-provided original proposal plus the four-batch scope approved in this conversation. Original attachment: (original proposal supplied in conversation)

## Global Constraints
- Conserve model calls and Codex tokens. Preserve all existing uncommitted files and credentials.
- All writes, including cleanup/rollback, need scoped immutable approvals. No model-controlled approval.
- Synthetic contracts are explicitly labeled; never claim real-platform fidelity.
- Task/ref access is scoped to actor/session/environment; identity remains local caller-supplied.
- Do not commit mixed pre-existing changes or publish. Existing branch codex/offline-mock-llm is retained.
- Framework comparison S5 is outside the four batches the user selected.

## Review Focus
- Process exit before/after side effects, including pending approval and read-result persistence.
- Concurrent resumes, changed actor/environment/parameters, stale approvals, and cleanup isolation.
- Budget accounting across pauses/restarts and malformed/provider responses.
- Large results never silently disappear or overflow model context; refs cannot cross scope.
- Evaluation uses independent state oracles, distinguishes deterministic/remote results, and reports missing usage/cost honestly.

### Task 1: Contracts and model adapter
Files: agent_core/workflow_contracts.py, agent_core/workflow_platform.py, contracts/, fixtures/, tests/test_workflow_contracts.py.
Interfaces: catalog() -> function schemas; normalize(name,args); WorkflowPlatform extends MockPlatforms; NativeModel.next(messages,context,max_tokens) -> decision + usage.
- [x] RED: schema/validation, config rollback, cleanup isolation, function call/usage tests.
- [x] GREEN: implement narrow tools, schema export + synthetic fixtures, native adapter; preserve old LLM methods.
- [x] Verify targeted tests, then run a bounded remote smoke sample; record evidence without secrets.

### Task 2: Bounded workflow engine
Files: agent_core/workflow_store.py, agent_core/workflow.py, tests/test_workflow.py.
Interfaces: WorkflowRuntime.start(text,context,budget), resume(task_id,context,action_id=None,decision=None,reply=None); scoped task status.
- [x] RED: seed -> query, approval/denial, three budgets, loop detection, transient/auth/bad-args/ambiguity handling.
- [x] GREEN: native single-tool loop, explicit stop reasons, persisted attempts and compact observations; 2 transient retries and one argument repair.
- [x] Verify tests without remote calls.

### Task 3: Recovery, refs, API
Files: api/offline_server.py, agent_core/workflow_store.py, tests/test_workflow_recovery.py.
- [x] RED: child-process exits, concurrent resume, tampering, reset, cleanup/rollback, scoped paginated refs, HTTP restart.
- [x] GREEN: checkpoints before side effects, cross-process task locks, refs/traces, scoped API controls.
- [x] Verify existing and new regression suites.

### Task 4: Evaluation and delivery
Files: evals/workflow_cases.json, scripts/evaluate_workflow.py, scripts/evaluate_model.py, evals/reports/, README.md.
- [x] RED: independent metric calculations and state-oracle failures.
- [x] GREEN: 30 cases (12 normal, 8 ambiguity, 6 faults, 4 adversarial), seven metrics, pass@1 and all-four-pass stability, baseline/current report, bounded real-model evaluation.
- [x] Run verification, one independent final review, fix important findings, document commands and residual limitations.

## Progress / rulings
- Pre-flight: contract schemas feed native model and executor; action_id + normalized arguments feed ledger and platform receipts; task_id scopes refs/traces and API controls.
- Ruling: work in existing branch with mixed prior changes, do not create a checkout omitting uncommitted foundation. Durable progress lives in this plan.
- Ruling: generic config/data tools cover a fixed synthetic gift domain, not arbitrary SQL or shell. Eight core tools plus explicit rollback/read_ref helpers implement the business chain safely.

## Completion evidence (2026-11-10)
- Task 1 complete: 10 strict tool contracts (8 core + rollback/read_ref), HTTP OpenAPI, synthetic fixtures, native function-call adapter. Model selection 12/12 accepted incrementally; two full remote chains verified after writes.
- Task 2 complete: bounded model/tool loop, scoped immutable approvals, classified errors, two transient retries, one argument repair, explicit final stop reasons. Conservative token reservation and active wall-clock checks survive restarts.
- Task 3 complete: durable preparing/executing phases, process-safe locks, externalized refs, status/resume/ref HTTP APIs. Real subprocess exits before receipt, after receipt, and after approval preparation recover without duplicate writes or repeated model decisions. Cleanup is batch-scoped; configuration preview/version conflicts fail closed.
- Task 4 complete: 30 fixed engine scenarios, repeated four times: 120/120. Seven metrics plus any-pass/all-pass stability. Existing nine-case before/after remains 5/9 -> 9/9. Full pytest: 118 passed, one inherited Pydantic deprecation warning. Real uvicorn HTTP smoke passed.
- Independent review closed four findings: post-write read loop false positive; synchronous work exceeding deadline; approval prepare/checkpoint crash gap; weak remote chain verification order. Each was reproduced in a failing test before repair. Reviewer reran relevant tests: 31 passed.
- Ruling: no comparable pre-change executable for new 30-case set. Preserve real 9-case before/after; do not invent a new baseline. --baseline requires identical case_set_hash.
- Ruling: successful model selection samples are reused between bounded acceptance runs to conserve cost; initial/intermediate/final reports retained. Initial output cap 256 produced one unparsed response; 512 resolved follow-up samples. Final two chains rerun against the strengthened independent oracle.
- Ruling: read repeat detection resets only after a successful write; repeated identical writes still stop. Wall-clock budget cannot interrupt an in-flight synchronous SQLite operation, but explicit checks prevent subsequent work after its deadline.
- Remaining scope limitations are in docs/workflow-guide.md: local synthetic domain, caller-supplied identity, macOS/Linux fcntl, no production connectors or S5 framework comparison.
