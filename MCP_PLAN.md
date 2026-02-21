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
- `gs_transaction_status`
- `gs_begin_if_needed`
- `gs_find_senders`
- `gs_tracer_status`
- `gs_tracer_install`
- `gs_tracer_enable`
- `gs_tracer_disable`
- `gs_tracer_uninstall`
- `gs_tracer_trace_selector`
- `gs_tracer_untrace_selector`
- `gs_tracer_clear_observed_senders`
- `gs_tracer_find_observed_senders`
- `gs_plan_evidence_tests`
- `gs_collect_sender_evidence`
- `gs_capabilities`
- `gs_guidance`

## MCP Tool Set (Planned Semantic + Refactoring Additions)

Semantic/AST access tools:
- `gs_method_ast` (structured AST for one method)
- `gs_method_structure_summary` (node counts, sends, blocks, returns, temporaries)
- `gs_method_sends` (message sends with source ranges and receiver shape hints)
- `gs_query_methods_by_ast_pattern` (find methods matching structural constraints)
- `gs_method_control_flow_summary` (basic branch/block nesting summary for AI reasoning)

Common refactoring tools:
- `gs_preview_rename_class` / `gs_apply_rename_class`
- `gs_preview_rename_method` / `gs_apply_rename_method`
- `gs_preview_extract_method` / `gs_apply_extract_method`
- `gs_preview_inline_method` / `gs_apply_inline_method`
- `gs_preview_add_parameter` / `gs_apply_add_parameter`
- `gs_preview_remove_parameter` / `gs_apply_remove_parameter`
- `gs_preview_move_method` / `gs_apply_move_method`

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

5. Phase 4 (hardening)
- extend selector rewrite coverage for cascades and multiline selector layouts
- broaden live integration coverage for longer AI-like edit/test sessions

6. Phase 5 (semantic analysis + refactoring suite)
- add AST/semantic introspection APIs suitable for AI planning and navigation
- add preview/apply workflows for common refactorings
- add safety checks that combine static structure and runtime evidence where available

## Current Status

- Phase 0: completed
- Phase 1: completed
- Phase 2: completed
- Phase 3: completed for targeted selector rename + debugger operations
- Phase 4: in progress
- Phase 5: not started

## Testing Approach

- Start with `pytest` for MCP contract and integration tests.
- Add Reahl testing tools where scenario matrices become complex.

## Known Risks

- Linked session is single-active-per-process.
- Long-lived object cleanup (`remove_dead_gemstone_objects`) must be handled.
- `gs_eval` can be risky and should be policy-gated.
- Performance on large images may require caching/indexing.

## Resolved Decisions

1. Write transaction policy:
- explicit `gs_begin` / `gs_commit` only.
- write tools now require an active transaction and return a clear error otherwise.

2. `gs_eval` safety:
- `gs_eval` remains gated by `--allow-eval`.
- even when enabled, callers must pass `unsafe=True` (optionally with `reason`).

3. Commit safety:
- `gs_commit` is now gated by `--allow-commit`.
- default MCP startup runs without commit permission for safer sessions.

4. Selector rename rewrite safety:
- selector rewrite now uses token-aware, statement-scoped matching.
- keyword selector renames avoid rewriting unrelated sends and skip strings/comments.

5. Implementor/sender discovery hardening:
- `gs_find_implementors` now supports `max_results`, `count_only`, and returns timing.
- `gs_find_senders` provides explicit sender search without requiring `gs_eval`.

6. Tracer version safety:
- tracer Smalltalk source is shipped in-project and installed via explicit MCP tools.
- image manifest stores tracer version/hash and `gs_tracer_status` verifies it against local source.

7. Runtime caller evidence:
- tracer can instrument selector senders and record observed caller edges while tests run.
- observed callers are queryable via `gs_tracer_find_observed_senders`.
- static recursive sender expansion can suggest candidate tests via `gs_plan_evidence_tests`.
- `gs_collect_sender_evidence` can run planned tests and collect evidence in one workflow.

8. Tracing policy gate:
- tracer and evidence tools are now controlled by `--allow-tracing` (disabled by default).

9. AI tool-usage onboarding:
- `gs_capabilities` reports active policy flags and tool groups.
- `gs_guidance` provides intent-based workflow and decision rules so new AI sessions can self-bootstrap safely.

10. Phase 4 hardening progress:
- added selector rename coverage for multiline keyword send layouts and cascaded sends.
- added a longer live guided refactor workflow test that bootstraps via `gs_capabilities`/`gs_guidance`, performs preview/apply rename, and validates via test execution.

## Next Implementation Step

Phase 4 hardening:
- extend selector rewrite coverage for cascades and multiline selector layouts
- broaden live integration coverage for longer AI-like edit/test sessions

After Phase 4, start Phase 5 with this order:
1. Deliver `gs_method_sends` and `gs_method_structure_summary` as minimal semantic APIs.
2. Deliver `gs_method_ast` with stable JSON schema and source ranges.
3. Deliver first refactoring pair: `gs_preview_rename_method` / `gs_apply_rename_method`.
4. Expand to extract/inline/parameter and move-method workflows.
