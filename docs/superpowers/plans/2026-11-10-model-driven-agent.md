# Model-driven Agent Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; execute the approved four batches inline.

**Goal:** Make the existing remote workflow model-driven across decisions, conversation, memory and evidence-grounded completion.
**Architecture:** Keep WorkflowRuntime, governed tools and SQLite. NativeModel opts into a versioned decision protocol; legacy rule/fixture behavior remains explicitly separate. Model control functions update_task, recall_memory and finish_task are distinct from the ten business tools.
**Tech Stack:** Python, Pydantic, SQLite, OpenAI-compatible function calling, pytest.
**Spec:** User-approved four-batch design in this conversation; this document records its implementation decisions.

## Global Constraints
- Single agent, serial tools, mock business environment; no LangGraph migration or vector database.
- Preserve permission checks, exact-action approval, production write ban, receipts and idempotency.
- User corrections invalidate pending approvals before replanning; never rewrite committed actions.
- Same-session scoped memory only; persisted source references never confer permission or prove current state.
- All model calls use existing token/time/step budgets; remote acceptance initial cap 120000 tokens; a documented repair verification may use at most 60000 additional tokens (180000 conservative combined upper bound).
- Legacy offline fixtures remain runtime evidence, not model-quality evidence.

## Review Focus
- SDK and queued API correction behavior must match, including crash windows and stale approval IDs.
- Forged completion evidence or model-authored goals must not manufacture committed writes.
- Memory cannot cross operator/session/environment boundaries or resurrect old permissions.
- Compression must preserve latest corrections and critical write facts with provenance.
- Condition already satisfied, unsupported requests and missing data must not require unnecessary writes.

## Task 1: Model protocol and conversational correction
Files: agent_core/workflow_decisions.py (new), workflow_model.py, workflow.py, workflow_clarification.py, workflow_jobs.py, model_call.py, tests/test_agent_decisions.py.
Interfaces: agent_protocol=2 capability, decision_catalog(allowed), accept_model_reply(state,reply), update_task(state,args).
- [x] Write/run failing tests for multi-field corrections, pending-action invalidation, SDK/queue parity.
- [x] Add typed control schemas and remote-only routing; gate execution on a current sourced task description.
- [x] Verify targeted tests; commit.

## Task 2: Context and session memory
Files: agent_core/workflow_memory.py (new), workflow_context.py, workflow_store.py, tests/test_agent_memory.py.
Interfaces: SessionMemory(connection).recent(scope,exclude,offset,limit); context contains ordered reply/tool events, sourced task understanding and historical evidence.
- [x] Write/run failing tests for scope isolation, restart, chronological replies and bounded history.
- [x] Store bounded extractive summaries transactionally with terminal checkpoints; retrieve indexed scoped history; expose bounded recall control.
- [x] Verify targeted tests; commit.

## Task 3: Evidence-grounded completion
Files: agent_core/workflow_completion.py (new), workflow_decisions.py, workflow.py, tests/test_agent_completion.py.
Interfaces: finish_task(state,args,receipts) returns structured goal assessments and rendered answer.
- [x] Write/run failing tests for no-op conditions, unrelated/forged evidence, unmet goals and contradictory narrative.
- [x] Check typed goal predicates against scoped real receipts/current observations. Model selects evidence and answer composition using validated fact placeholders; unsupported prose falls back to factual response.
- [x] Verify targeted tests; commit.

## Task 4: Independent agent evaluation and documentation
Files: evals/agent_cases.py, scripts/evaluate_agent.py, tests/test_agent_evaluation.py, docs/model-driven-agent.md, README.md.
- [x] Add 12 scenario families with two variants, independent state/safety oracles, recording/replay and separate decision metrics.
- [x] Test evaluator and full regression. Execute one capped remote run; publish all failures as well as passes without claiming unrun cases passed.
- [x] Fresh whole-branch review; resolve material findings; update acceptance report and documentation; commit.

## Execution ledger
- Base e23ec91; isolated branch codex/model-driven-agent.
- Ruling: preserve compatibility fixtures via explicit protocol version rather than changing legacy behavior silently.
- Ruling: bounded extractive summaries avoid paid summarization and do not invent facts. Natural response uses model-composed evidence placeholders; unrestricted prose cannot be deterministically certified and is not presented as verified fact.

- Task 1–3 complete: protocol, corrections, context/memory and completion tests pass; baseline full suite 216 passed.
- Review fixes: newest evidence invalidates old reads; SDK approval checkpoint atomic; all committed writes retained; reset clears memory; conditional oracle requires post-write readback.
- Ruling: initial real-model run stopped after 5 completed cases (65368 reported tokens) exposed ambiguous write_goal schema. Preserve all failures; rename it write_goal_id with examples and add descriptions. One targeted verification of conditional_1, conditional_2 and missing_1 gets an additional 60000 cap. Initial interrupted request usage is unknown; conservative combined cap is 180000. Per-call reservation ledger added so future interrupted spending remains auditable.

- Task 4 complete: 12 families/24 variants, independent state oracle, proposal metrics, durable token reservations, real-call recordings and replay. Final full suite 231 passed/1 inherited warning; actual model trajectory replay2/2. Paid full coverage intentionally not claimed.
- Final review defects all covered by regressions, plus partial-commit memory retention and budget-vs-model-error classification.
