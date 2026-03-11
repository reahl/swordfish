# `main.py` Split TODO

Status after commit `45a0f43`:
- `src/reahl/swordfish/main.py` is down to about 6813 lines.
- The browser, execution, inspector, navigation, object diagram, class diagram, text editing, tab registry, selection list, UI context, UI support, and exception code have already been extracted.
- The full suite passed at this point: `531 passed, 1 warning`.

## What is still in `main.py`

- `GemstoneSessionRecord`
- `UiDispatcher`
- `BusyCoordinator`
- `ActionGate`
- `EventQueue`
- `McpConfigurationStore`
- `McpRuntimeConfig`
- `McpServerController`
- `McpConfigurationDialog`
- `MainMenu`
- `FindDialog`
- `CoveringTestsSearchDialog`
- `BreakpointsDialog`
- `Swordfish`
- `LoginFrame`

## Highest-value next splits

1. Extract search and tool dialogs.
   Move `FindDialog`, `CoveringTestsSearchDialog`, and `BreakpointsDialog` into a dedicated module such as `search_dialogs.py`.

2. Extract MCP runtime and configuration UI.
   Move `McpConfigurationStore`, `McpRuntimeConfig`, `McpServerController`, and `McpConfigurationDialog` into an MCP-focused module.

3. Slim `Swordfish`.
   Split `Swordfish` by responsibility rather than by widget type:
   - global navigation
   - MCP IDE action execution
   - collaboration status / busy state handling
   - tab opening and closing orchestration

4. Decide whether `GemstoneSessionRecord` should remain in `main.py`.
   It may deserve its own module if we want `main.py` to become only UI composition and application coordination.

5. Decide whether `MainMenu` and `LoginFrame` should move.
   They are smaller than the other seams, but they still keep UI construction mixed into `main.py`.

## Suggested extraction order

1. `search_dialogs.py`
2. `mcp_runtime.py` or `mcp_ui.py`
3. `swordfish_navigation.py` for the app-level global navigation logic
4. `swordfish_actions.py` for MCP IDE actions and tab-opening workflows
5. `session_record.py` if we still want `main.py` to shrink further

## Rule for future extractions

- Keep `Swordfish` as the coordinator.
- Prefer modules that depend on `Swordfish` over modules that import each other.
- Avoid creating circular imports between extracted UI modules.
- Run the full suite after each extraction step.
