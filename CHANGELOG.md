# Changelog

## 0.1.0 (2026-03-06)

Initial release.

- `WorkflowStreamer` — streaming wrapper around soprano-sdk workflows
- 5 typed event dataclasses: `NodeCompleteEvent`, `CustomEvent`, `InterruptEvent`, `CompleteEvent`, `ErrorEvent`
- `events_to_sse()` helper for FastAPI / sse-starlette integration
- `from_env()` factory for quick setup from environment variables
- Migration guide from `WorkflowTool.execute()`
