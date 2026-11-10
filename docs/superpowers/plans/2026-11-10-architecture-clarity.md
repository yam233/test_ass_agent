# Architecture clarity — scoped implementation

Approved scope: make the existing workflow understandable; no new tools, framework, platform integration, database abstraction, or paid model calls. Base e0739b3. Preserve existing request/approval/receipt semantics. Implement locally in codex/architecture-clarity, sync changed source to original after validation; no automatic push/merge.

## Design
- `/workflows` is the primary runtime. Health describes it without constructing the compatibility agent; report compatibility status separately. Move historical README content into a clearly marked legacy guide; current README and an architecture guide explain actual dependencies.
- Put shared request validation in workflow_contracts. Move the shared LLM client out of the legacy LangGraph directory, retaining the old import path; expose public completion/setting methods and keep private aliases for compatibility. Default runtime dependencies are assembled in one factory; custom model injection is preserved.
- Move Runtime SQL for receipts, task receipt listing, cancellation and audit into scoped ActionStore methods. Move platform preflight DB access behind a platform method. Keep JobStore approval+enqueue transactions and platform write+receipt transactions unchanged; no blanket storage abstraction.

## Review Focus
1. Legacy import identity, HTTP client configuration and transport behavior remain compatible; default/custom models still select correctly without hidden network calls.
2. Health reflects the primary runtime and never initializes legacy execution merely to report status.
3. Receipt methods enforce operator/session/env and task boundaries; cancellation preserves committed results and audit atomicity.
4. Database transaction scopes remain exactly where approval/enqueue and write/receipt invariants require them.

### Task 1: Public boundaries and assembly
Files: workflow_contracts, workflow, workflow_jobs, model_client, legacy llm shim, workflow_model, model_call, workflow_rules, workflow_factory; affected model mocks.
- [ ] RED: public-client NativeModel contract, legacy client identity, configured/default/custom factory selection, shared validation.
- [ ] Implement public interfaces and centralized assembly; retain compatibility aliases.
- [ ] Targeted model/contracts/SDK/job/recovery regression; commit.

### Task 2: Runtime storage boundary
Files: action_store, workflow_platform, workflow; scoped repository tests.
- [ ] RED: task-scoped receipts and scope rejection, cancellation audit rollback, committed action preservation.
- [ ] Move queries behind public methods without changing transaction scopes.
- [ ] Run approval/jobs/policy/recovery/usability tests; commit.

### Task 3: Primary entry and documentation
Files: api/offline_server, README, docs/architecture, docs/legacy-runtime, API boundary tests.
- [ ] RED: health reports primary workflow and leaves compatibility uninitialized; initialized legacy status separate.
- [ ] Implement health and current/legacy documentation; preserve endpoint behavior.
- [ ] Full offline core+legacy suite, one independent whole-branch review and necessary fix pass, sync changed source to original; commit evidence.
