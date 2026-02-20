# SwordfishMCP Implementation Plan

Date: 2026-02-13

## Goal

Build an MCP server (`SwordfishMCP`) that allows AI tools (Codex, Claude Code, others) to connect to GemStone via Parseltongue, browse code, perform targeted edits, and run tests.

## Constraints and Principles

- Ship as one project with Swordfish GUI + MCP server.
- Prefer no custom GemStone-side code in phase 1.
- Keep outputs JSON-safe (no leaked GemObject instances).
- Prioritise safe, explicit transaction handling.
- Preserve existing Swordfish behaviour while extracting reusable domain logic.

## Current Evidence From Code

- Swordfish already uses Parseltongue for:
  - class/package browsing
  - selector/category listing
  - method lookup/source/compile
  - implementor lookup
  - evaluation and debugger stepping patterns
- Parseltongue provides:
  - `LinkedSession`, `RPCSession`
  - `execute`, `resolve_symbol`, dynamic `perform`
  - transaction operations (`begin`, `commit`, `abort`)
  - debugger continuation/stack control via `GemstoneError`

## Proposed Packaging

- Keep existing script:
  - `swordfish = reahl.swordfish.main:run_application`
- Add MCP script:
  - `swordfish-mcp = reahl.swordfish.mcp.main:run_application`
- Keep this as a single distributable project.
- Add MCP dependencies as optional extras to avoid forcing MCP runtime on all users.

## Suggested Code Layout

- `src/reahl/swordfish/gemstone/session.py`
- `src/reahl/swordfish/gemstone/browser.py`
- `src/reahl/swordfish/gemstone/editing.py`
- `src/reahl/swordfish/gemstone/evaluation.py`
- `src/reahl/swordfish/gemstone/debugging.py` (phase 3)
- `src/reahl/swordfish/mcp/server.py`
- `src/reahl/swordfish/mcp/tools.py`
- `src/reahl/swordfish/mcp/session_registry.py`
- `src/reahl/swordfish/mcp/main.py`

## MCP Tool Set (Phase 1)

- `gs_connect`
- `gs_disconnect`
- `gs_begin`
- `gs_commit`
- `gs_abort`
- `gs_list_packages`
- `gs_list_classes`
- `gs_list_method_categories`
- `gs_list_methods`
- `gs_get_method_source`
- `gs_find_classes`
- `gs_find_selectors`
- `gs_find_implementors`
- `gs_compile_method`
- `gs_eval`

## MCP Tool Set (Implemented Additions)

- `gs_create_class`
- `gs_create_test_case_class`
- `gs_get_class_definition`
- `gs_delete_class`
- `gs_delete_method`
- `gs_set_method_category`
- `gs_preview_selector_rename`
- `gs_apply_selector_rename`
- `gs_list_test_case_classes`
- `gs_run_tests_in_package`
- `gs_run_test_method`
- `gs_global_set`
- `gs_global_remove`
- `gs_global_exists`
- `gs_run_gemstone_tests`
- `gs_debug_eval`
- `gs_debug_stack`
- `gs_debug_continue`
- `gs_debug_step_over`
- `gs_debug_step_into`
- `gs_debug_step_through`
- `gs_debug_stop`

## Phased Delivery

1. Phase 0 (spike)
- minimal MCP bootstrap
- connect/eval/disconnect
- error mapping

2. Phase 1 (browser MVP)
- all read-only browse/find/source tools
- robust session lifecycle

3. Phase 2 (safe edits + tests)
- compile/update tools
- explicit transaction flow
- test execution tools

4. Phase 3 (advanced)
- targeted refactor tools (selector rename workflow)
- debugger-oriented MCP operations

## Testing Approach

- Start with `pytest` for MCP contract and integration tests.
- Add Reahl testing tools where scenario matrices become complex.

## Known Risks

- Linked session is single-active-per-process.
- Long-lived object cleanup (`remove_dead_gemstone_objects`) must be handled.
- `gs_eval` can be risky and should be policy-gated.
- Performance on large images may require caching/indexing.

## Pending Decisions

1. Write transaction policy:
- explicit `gs_begin` / `gs_commit` only (recommended) vs auto-commit per write.

2. `gs_eval` safety:
- disabled unless `--allow-eval` flag (recommended) vs enabled by default.

## Next Implementation Step

Create the MCP scaffolding and tool schemas first, then wire read-only browser tools to extracted shared GemStone domain modules.
