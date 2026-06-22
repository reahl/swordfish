# Swordfish Design Conventions

This is the **living design language** for Swordfish: the things we deliberately do
consistently, the metaphors we stay inside, and the architectural constraints we keep to.

It exists so that new work *looks and behaves like the rest of the IDE* without having to
rediscover the conventions each time. It is not a description of every feature — it is the
set of rules a feature must conform to.

**How to use this document**

- **Before** building or changing any UI or user-facing behaviour, read the relevant section
  here and conform to it.
- When you establish a **new** convention, or deliberately **change** an existing one, update
  this document **in the same change** (same commit/PR). A convention that lives only in one
  screen is not a convention.
- If a request conflicts with a convention here, say so and reconcile it explicitly (change
  the convention here, or make a documented exception) rather than silently diverging.
- Keep it concise. Each entry says *what* we do and *why*, and points at where it lives in the
  code. It is not API documentation.

---

## Metaphors we stay inside

- **Tools in a workspace.** The IDE is a set of *tools* (browser, workspace/run, find,
  inspector, debugger, class/object diagrams) placed in a splittable two-pane area
  (`PaneArea`). The user arranges tools; the IDE does not dictate one fixed window. New
  surfaces are *tools that open in a tab*, not bespoke top-level windows.
- **Classic Smalltalk IDE.** Browsing is the familiar column cascade
  (package/dictionary → class → category → method); editing, running and debugging are live
  against the image. Stay within the idioms a Smalltalker already knows; don't invent novel
  navigation where a classic one exists.

---

## UI / interaction conventions

### Tools open in tabs, in a left or right group
The `PaneArea` has two tab groups. By convention:
- **Left group (group 0):** the primary working tools — Browser, Workspace/Run, Find.
- **Right group (group 1):** auxiliary tools opened *about* something — Inspector, Debugger,
  class/object Diagrams, Run output.

A tool opens in its conventional group. Opening a tool that is already open re-uses its tab
(de-duplication) rather than stacking duplicates. See `pane_area.py`, `tab_registry.py`,
`auxiliary_notebook()`.

### Tabs are closable, and closing tidies up
Every tool tab carries a close **`x`** (the closable-notebook behaviour). Closing the last tab
in the right group **collapses the group** so there's no empty pane left behind. The browser
and find tabs that anchor the left group are intentionally *not* closable. See
`closable_notebook.py`, `install_close_buttons`, `remove_group_if_empty`.

### Buttons are small icon buttons that name themselves on hover
Actions are **compact glyph icon buttons**, not wide text buttons. Each carries a **hover
tooltip** that names it (the glyph is the affordance, the tooltip is the name). Use the
reusable `Tooltip` (`ui_support.py`). Examples: Run `▶`, Inspect `⊙`, Debug `▷`, debugger
Continue `▶` / Over `↷` / Into `↓` / Through `⤓` / Restart `↺`, Find `⌕`, Refresh `⟳`, Stop `■`,
history Back `←` / Forward `→`, inspector page Previous `‹` / Next `›`, Browse class `▣`, diagram
Clear `⊗` / Rearrange `⤢` / Undo `↶` (a semicircle, kept visually distinct from the full-circle
Refresh `⟳`). This applies to **persistent chrome** (toolbars, navigation
bars, tool footers); **modal dialog** buttons (Login, File out, Add/Cancel and the like) stay as
words — a transient dialog's named confirm/cancel is its own idiom and reads worse as a lone glyph.

### Glyphs are BMP-only
Tk 8.6 cannot render characters outside the Basic Multilingual Plane (e.g. most emoji like
🔍 U+1F50D show as tofu). Every glyph used as an icon must be a **BMP** code point. But BMP is
**necessary, not sufficient** — Tk only draws a glyph the *system font actually covers*, so a
BMP code point in a sparsely-covered block (e.g. `⎚` U+239A in Miscellaneous Technical) still
shows as a tofu box. Pick glyphs from blocks the app already renders elsewhere: Arrows
(`←↺↷`), Geometric Shapes (`■▶▷▣`), Mathematical Operators (`⊙⊗`), and the arrow/symbol
blocks proven by `⤓`/`⟳`. When a glyph reads poorly or boxes out, swap it for a neighbour in a
proven block (and the tooltip clarifies meaning regardless).

### Find: one regex filter box per visible column, aligned to it
Find results are a `Treeview` with adaptive columns per result kind. Filtering is **one
unlabelled regex box per visible column**, overlaid directly **above its column heading** and
kept **aligned and resized** with the column. The single source of truth is
`result_column_specs(kind)` (column id, heading, value function), which drives the tree
columns, the filter boxes, and the filtered values together. All result paths funnel through
one render path that keeps an unfiltered baseline, so filtering re-renders without re-querying
the gem. See `FindPane` in `main.py`.

### Anything that can run long is interruptible from the IDE
If an operation can take a noticeable time (a search, a run/inspect/debug of user code, a test
run, a debugger resume/step, an MCP tool's work), it must run as a **foreground activity** and
be stoppable with the single **Stop `■`** button (bottom-right of the status bar). The Stop
button is **live only while an activity holds the session** and interrupts whatever is running.
This is non-negotiable for new long-running work — never block the UI thread on an
uninterruptible gem call. See the session-activity model below and `session_activity.py`,
`Swordfish.run_foreground_activity`, `update_status_stop_button`.

### Evaluating a selection is one interruptible path
Every "evaluate the selected source" action — **Run**, **Print**, **Inspect**, **Show in
Object/Class Diagram**, and their debugger in-frame counterparts — evaluates through the
`SelectionEvaluation` collaborator (`ui_support.py`), which runs the doit as a `ForegroundActivity`
on the worker thread so the Stop button can `hard_break` a slow expression. The caller supplies
*what to evaluate* (run on the worker thread) and *what to do with the result* (on the UI thread);
a failure falls back to a dialog named for the action. Never evaluate a selection synchronously on
the UI thread again — that was the old inconsistency this consolidates. Editors share the action
set via `add_run_commands`, so every code editor exposes the same group.

### Print It splices the result back into the editor
**Print** is the classic Smalltalk *print it*: evaluate the selection and insert the result's
`printString` immediately **after** the selection, leaving the inserted text selected (one delete
removes it). The gem work (the doit **and** the `printString`) happens inside the activity's worker
step; only the insert touches widgets, via the reusable `EditableText.insert_after_selection`. The
menu order is the classic do-it / **print-it** / inspect-it / debug-it.

### Consistent menu placement
Top-level menus, in order: **Session, Find, Code, UML, MCP, FileTree** (native OS menu bar).
Exit lives on **Session**. New menu commands go on the menu that names their domain; keep the
ordering stable. The menu bar is the *native* Tk menu bar — it cannot host widgets or tooltips
(see constraints), so icon controls (Refresh/Stop) live in the **status bar**, not the menu
row.

### Status feedback
Long activities set a status message and the activity indicator (the watch cursor + the
collaboration status bar). A user-requested **Stop is not an error** — it reports "stopped"
and must never drop the user into a debugger; a genuine trap (unhandled error / breakpoint)
*does* open the debugger. Keep that distinction.

### Colour comes from the theme, by semantic role — never hardcode a colour
Every colour is named by a **semantic role** (what it means: `editor_keyword`, `class_node_outline`,
`risk_safe`) and looked up on the active theme, never written as a literal. The vocabulary and the
light/dark palettes live in `theme.py`; a widget asks `active_theme.current().color_for('role')` as
it builds. Both palettes must define **identical roles** (a test enforces this) so any screen is
fully themeable in either — add a role to *both* or to neither. When a colour carries a distinction
(direct vs inferred inheritance, safe vs unsafe risk), give each side its own role rather than
inverting lightness, so the meaning survives in both palettes.

The theme is **resolved once at startup** (configured `appearance.theme` → OS preference via
`OperatingSystemAppearance` → light default) and **fixed for the session** — changing it means
restarting. There is deliberately no on-the-fly switch: that would need a re-apply path through
every open tool and the diagrams' canvas redraw. Light is the host's **native** look and applies
no global styling (its per-site colours equal the original appearance, so zero regression); only a
departing theme (dark) restyles, via `ThemeApplication` — the Tk **option database** for classic-tk
widgets plus a `clam`-based `ttk.Style` for ttk widgets (the two families don't share a styling
mechanism). New colour sites read a role; new screens get themed for free.

---

## Architectural constraints

### Event-driven: the `EventQueue` is the spine
UI components **react to published events** rather than calling each other directly. Publish a
typed event; subscribers (weak-ref callbacks, optionally `ui_context`-scoped) update themselves.
Derived views (browser columns, editor tabs, breakpoints) re-read from the image on the typed
change events; snapshot views (diagrams, inspector) opt into a generic `RefreshFromImage`. When
adding behaviour that several components care about, **add an event**, don't wire direct
cross-references. See `EventQueue` in `main.py` and `reference_mcp_ide_refresh_bridge`.

### One shared GemStone session; gem work off the UI thread
There is one `ide-session` and it runs **one GCI call at a time**. Long gem work runs on a
**worker thread** (never the Tk UI thread); results are marshalled back and all widget updates
happen on the UI thread. Gem-free UI events (e.g. announcing that an activity started) must
reach the UI **even while an MCP operation holds the session** — they bypass the
session-admission gate via `SESSION_SAFE_EVENT_NAMES`; gem-touching events still defer to avoid
a 2203 collision. Do not run IDE GCI from the event drain while the session is held.

### Interruptible work: the session-activity model
A long operation is a **`ForegroundActivity`** (`session_activity.py`): `work(should_stop)` runs
on the worker thread; the outcome is delivered on the UI thread to `on_finished` /
`on_interrupted` / `on_failed`. At most one activity holds the session at a time
(`Swordfish.current_session_activity`); the Stop button drives `request_stop()` — a cooperative
flag then a session-scoped `hard_break`. MCP tool calls register as the activity too, so the
same Stop interrupts them. New long operations use this model, not inline blocking.

### Designed objects, not module-level functions
Share behaviour through a **class that names the concept**, not a module-level `def`. Example:
test running is a `TestExecution` object, not a `run_tests(...)` function. (Module-level
*constants* are fine.) See `feedback_no_module_level_functions`. Also follow the global coding
conventions in the user's `CLAUDE.md` (no static methods, no base/utility/helper names, class
names are domain nouns, methods are verbs, `AI:` comment prefix, Reahl testing tools).

### Tk constraints we work within
- The **native menu bar** (`root['menu']`) is OS-drawn outside the client area: it can host
  neither widgets nor hover tooltips. Icon controls therefore live in panels or the status bar,
  not the menu row. (We tried a custom Menubutton bar to share the row — it looked wrong; the
  native menu bar stays.)
- **`createfilehandler` / cross-thread wakeup** and **`event_generate` from another thread** are
  unreliable; cross-thread delivery goes through the `EventQueue`'s marshalling, not ad-hoc Tk
  calls.
- Absolute **grid row/column indices** are fragile: inserting a row at the top silently
  invalidates hardcoded indices in methods far away. Prefer self-contained layout and re-check
  every row reference when you add a row.

### Testing
A test explains one domain insight; coverage is secondary. GUI behaviour runs **synchronously**
under test via the `run_activities_synchronously` seam (the fake application mirrors it), so a
search/run completes within the call — no thread/Tk-timing races. The real threading is
exercised by its own dedicated test. Use the project's Reahl testing tools. Run the suite with
`./docker-run-over-ssh.sh pytest tests/` before committing.

---

*Add new conventions here as we establish them. If you changed how something works and didn't
update this file, you haven't finished the change.*
