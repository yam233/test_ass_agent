# Write reliability implementation plan

Goal: fixed backpack regression suite, persistent actions/idempotency, and approval bound to an immutable operation snapshot. User approved implementation in conversation.

Architecture: keep LangGraph; governed offline subclass routes confirmation/cancellation/retry using stored action IDs. SQLite action ledger stores owner/session/environment/tool/normalized arguments and approval expiry. A separate platform receipt table commits atomically with mock side effects; recovery queries receipts before retrying. This is a single-action guarantee for the local mock, not remote-platform exactly-once or a general checkpoint engine.

- [x] Record baseline using a small fixed offline case set.
- [x] Test then implement ledger and atomic platform receipts, including concurrent retries and the commit-before-ledger crash window.
- [x] Bind natural-language/API confirmation and retries to stored snapshots; reject changed scope/parameters and boolean approval bypass.
- [x] Re-run the fixed cases and existing tests, independently review, document the API and scope.

Constraints: conserve tokens; use the existing venv and architecture; no real LLM or platform calls are needed; preserve existing uncommitted changes. Existing local server is a personal mock, so operator is a caller-supplied identity, not production authentication.

Acceptance: partial writes report 5/10; retry after lost response or process exit produces exactly 10; explicit new action can produce another 10; unapproved/expired/denied or mismatched actions never write. Reset clears actions and receipts together with state.

Validation: fixed offline regression improved from 5/9 to 9/9; write reliability plus offline compatibility 46 passed; existing architecture guards 34 passed. Review identified and closed two concurrency gaps, with three regression cases first observed failing, then passing. Receipt completion now outranks late failure; approval transition races recheck receipts. Real subprocess exits test both sides of the platform transaction commit. The suite retains one pre-existing Pydantic deprecation warning. No remote model or platform calls were used.
