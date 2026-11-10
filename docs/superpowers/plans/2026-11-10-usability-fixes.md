# Existing capability usability fixes

User-approved scope: repair existing behavior, do not expand tools/frameworks/storage abstractions. Base a616b70. Single-session implementation and one final independent review. Preserve original local configuration and unrelated work. No automatic push.

## Design and boundaries
- Authoritative final summaries come from recorded tool outcomes and committed receipts, never model prose. For the existing explicit operation phrases, missing requested operations cannot finish successfully. Unknown wording is not claimed as semantically verified; report only observed execution facts. No general-purpose planner or intent model added.
- Schema missing fields pause for clarification; malformed values get one repair. Persist clarification metadata, expose exact missing fields, retain normal model-based follow-up interpretation. Write identity validation occurs before action preparation and is BAD_ARGS; permission denial remains auth.
- Keep SQLite/schema; use indexed JSON status expressions and bounded cursor scans rather than new storage interfaces. Recovery is periodic (1s), scans at most100 task IDs per batch, retries contended tasks after5s, includes old tasks. Expiry considers only pending overdue approvals. Queue generation and lock guarantees remain.
- Retry hints only for proven no-side-effect contention; clients retain original task/action. No automatic replay of arbitrary approvals. Use Retry-After integer seconds.
- Real-model acceptance: original local credentials loaded without printing/copying them, temporary mock DB only, total conservative budget80000 tokens across a small fixed sample; no broad benchmark/record-replay expansion. Report service/model failures honestly and avoid repeated paid runs.

## Review Focus
1. A read cannot substantiate a claimed write; unrelated receipts and unverified model text cannot appear as successful effects.
2. Clarification after restart preserves scope, mode, budgets and approval; missing/invalid fields never fabricate values.
3. Scanning throttling never permanently abandons old or lock-contended SDK tasks; expiry and resume remain transactional.
4. Busy responses cause no duplicate approval/write, and retries never suppress actual failures.
5. Real-model verification cannot touch real platforms or expose credentials; runtime success and scenario success remain separate.

### Task 1: Evidence-backed outcomes
Files: workflow_outcome.py (small factual formatter and supported-intent checks), workflow.py, tests/test_workflow_usability.py.
Interfaces: finalize_outcome(state, receipts)->dict with message/effects/observations/unfulfilled/verification; missing evidence uses no_evidence. Preserve successful read and approved-write behavior; structured evidence remains available on interrupted tasks.
- [x] RED: read then fabricated-write final; successful seed+batch verification; unrelated read cannot verify write; unknown phrasing reports evidence scope only.
- [x] Implement factual summary and final completion guard. Expected: no invented effects, real quantities/action IDs retained.
- [x] Run targeted tests plus workflow/recovery; commit. Expected: all pass.

### Task 2: Clarification and error semantics
Files: workflow.py, workflow_policy.py, workflow_jobs.py, workflow_clarification.py, tests/test_workflow_usability.py.
Interfaces: missing-field metadata persists across resumes; single-field scalar/JSON replies can merge only missing fields under strict schema; ordinary natural-language replies still use existing model interpreter. BAD_ARGS maps bad_args with nonempty result.
- [x] RED: missing quantity waits; restart+reply+approval writes exactly requested amount; invalid reply cannot write; missing env/operator bad_args; invalid values repair once.
- [x] Implement bounded clarification and error classification; permission revocation remains auth. Expected: no effects before valid approval.
- [x] Run workflow/policy/recovery/jobs/eval tests; commit. Expected: all pass; intentional missing-args chaos expectation becomes clarification.

### Task 3: Bounded maintenance and contention
Files: workflow_store.py, workflow_runner.py, api/offline_server.py, tests/test_workflow_maintenance_bounds.py, tests/test_workflow_scheduling.py.
Interfaces: recovery one-second cadence; at most100 orphan candidates per cursor batch; failed locks retry after5s, bounded memory; due-approval selection avoids locking irrelevant tasks; retry headers for RESOURCE_BUSY/STATE_CONFLICT.
- [x] RED: old orphan eventually recovered despite full queue/held lock; terminal task payloads not loaded by scan; non-expired tasks not locked by expiry; API busy hint and unchanged task followed by one successful approval.
- [x] Add indexes/cursor batches, cadence and filtered expiry; preserve public recover(force=True) for startup/manual recovery. Expected: no new DB/framework; scanning work bounded per tick.
- [x] Run lifecycle/jobs/scheduling/recovery and benchmark representative historical data; commit. Expected: green and report actual timing.

### Task 4: Existing-chain acceptance
Files: bounded real acceptance script/report if necessary, docs/usability-acceptance.md, workflow-guide.md; no new features.
- [x] Run full core+legacy suite repeatedly (5 runs, record first failure instead of masking); offline fixture/chaos regressions. Expected: all pass or explicitly fix root cause.
- [x] Run small real-model cases for existing five operations and missing-field follow-up, approve only case-exact synthetic writes. Expected: independent DB/receipt verdict, actual tokens/error types, never fake success.
- [x] Whole-branch independent review, one fix pass, final verification; compare/sync source back to original without secrets or unrelated edits. Expected: evidence report states verified limits and paid budget usage.

执行结果与范围边界见 ../../usability-acceptance.md。实现任务合并提交以保留共享回归用例的完整性；独立静态审查未发现 Critical/Important 问题。结构化缺参只接受显式补充，普通模型追问保留自然语言解释。
