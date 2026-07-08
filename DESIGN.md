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

### Find: one intent chosen via category tabs, not a grid of radio buttons
The Find dialog presents **one choice — the search intent** — not a cross-product of "search
type × match mode × reference target" radio groups. The intents are grouped into three
**category tabs** and selected by a short **variant** row within the active tab:

- **Class** — Containing · Exact · References
- **Method** — Implementors · Containing · Senders
- **Variable** — Inst var · Class var

The chosen intent drives, *behind the scenes*, the engine's existing `search_type` /
`match_mode` / `reference_target` model (`FindPane.SEARCH_INTENT_TO_CONFIG`); those are no longer
user-facing controls. Switching to a category whose variants do not include the current intent
falls back to that category's first variant (`default_intent_for_tab`).

**The inputs live inside the tab body, not below the tab bar.** Each tab carries its variant row
*and* the inputs that category needs: a query entry (labelled per category — "Class:" /
"Selector:" / "Variable:") with an icon find button, plus the owning-class entry on the Variable
tab and the receiver-class entry on the Method tab (shown only for Senders). The per-tab query
entries share one `query_var`, so the typed text is the same whichever tab is shown.

Programmatic openers (`open_find_dialog_for_class` / `_for_instvar` / `_for_classvar`, senders,
implementors) still pass the legacy triple; `sync_intent_from_config` selects the matching
tab/variant so the visible control reflects the search. Because `ttk.Notebook.select()` only
sticks once the pane is mapped (an unmapped notebook snaps to tab 0 and fires
`<<NotebookTabChanged>>` on realization), the tab-change handler stays inert until
`activate_search_tabs` runs after the pane is shown — otherwise realization would overwrite a
programmatically chosen intent. There is **no separate "search intent" sentence** — the selected
tab + variant *is* the statement of intent; a short result-action hint remains. See `FindPane` in
`main.py`.

### Find References: class, method, and variables
Reference searches are the **References** (Class tab), **Senders** (Method tab), and **Inst var**
/ **Class var** (Variable tab) intents. The two variable intents share
the result shape (`class TAB side TAB selector`) and downstream navigation/highlight, but use
**different gem queries** because the two variable kinds are found in fundamentally different ways:

- **Inst Var** uses `GsNMethod>>instVarsAccessed`, searching the selected class + its subclasses
  on **both the instance and class sides**. This also covers **class-instance variables**, which
  are simply the metaclass's instance variables and so show up on the class side.
- **Class Var** cannot use `instVarsAccessed` (it does not see class variables). A class-variable
  reference compiles to a `SymbolAssociation` literal whose **key** is the variable name, so the
  search walks up to the variable's **owner** (the highest ancestor declaring it) and scans that
  whole subclass hierarchy's method `literals` for an `Association` with that key. Identity on the
  association does **not** work (the compiler binds a different association object), so it matches
  by key symbol. Portable selectors (`detect:ifNone:`, `isKindOf: Association`) are used so the
  query also runs on GemStone 3.6.5. See `GemstoneBrowserSession.find_classvar_references`.

The variable modes are reached by right-clicking a class — in **both** the class **list** and the
**hierarchy tree** — which opens a **Variable References** cascade submenu of that class's
*accessible* variables. The submenu groups them under three **underlined, normal-weight, inert
heading rows** — *Instance*, *Class-instance*, *Class* — and a heading appears only when that kind
has members. Headings carry no command (they are not selectable) but stay in the normal colour
(**not** greyed) so they read as section titles, not disabled variables. Within each kind the
class's **own** variables come first in normal colour, then **inherited** ones (defined on a
superclass) in the muted `disabled_list_item` colour — the **same grey-means-inherited convention
used for inherited methods in the method list** (`ClassSelection.style_method_entry`). Inherited
entries stay **selectable** (greyed for emphasis only). Choosing a variable opens the Find dialog
with both fields pre-filled — instance and class-instance entries route to the Inst Var search,
class-variable entries to the Class Var search.

The submenu is read **fresh from the gem each time the menu is posted** (no per-class cache) so
right-clicking a class always lists that class's variables, even when a different class is
currently selected. Both context menus build the submenu through the one shared
`ClassSelection.add_instvar_references_cascade`; the per-kind own/inherited variable lists come
from `GemstoneBrowserSession.accessible_var_names`, which derives "own vs inherited" from the
GemStone invariant that `instVarNames`/`classVarNames`/`class instVarNames` are own-only while
`allInstVarNames` is the full chain.

**Every reference search highlights its term where it occurs in the result method** — and it does
so on **both peek (single click) and open (double click)**, so a glance shows the references in
context. Each result row carries a `highlight_term`: the variable name for inst/class-var
searches, the class name for class references, and the sent selector for senders. Selecting the
row publishes the `OccurrenceHighlightRequested` event →
`MethodEditor.apply_occurrence_highlight_to_active_tab` → `CodePanel.apply_occurrence_highlight`,
which marks every matching token. Matching covers the token kinds a reference can take: identifiers
(variables, class names, unary selectors), keyword-message parts (e.g. `printOn:`) and binary
selectors; a multi-keyword selector such as `at:put:` is several tokens and is not highlighted as
a unit (whole-token matching avoids false positives). The highlight uses the
`reference_highlight_background` theme role and the `occurrence_highlight` text tag (applied after
syntax tags so it wins background priority while syntax foreground colours remain active).
Clearing the highlight is implicit the next time a different method opens or it is re-applied.

### Find results: run or debug a test method in place
A Find result that is a **test method** can be run or debugged straight from the results list —
right-click → **Run Test** / **Debug Test** — without first navigating to its class. The menu also
carries **Senders** / **Implementors** (any method result), mirroring the method-list and
source-window menus so the same selector navigation is reachable wherever a method appears.
Navigating *to* a method result is the job of click (peek) / double-click (pin), so there is
deliberately **no Jump to Class** here. Every action in this menu drives the gem, so **all are
greyed while the session is busy with any other activity** (`Swordfish.session_is_busy()` — a find,
a test run, an MCP tool): the single-threaded session runs one call at a time, so a second gem
operation must never be launched on top of one still running.

A **class-bound** result (Implementors / Senders / References, which carry a class) is runnable when
it is a test method by the **same rule the sender scan uses**: an **instance-side** method whose
selector starts with `test` on a **`TestCase` subclass**. A **bare-selector** result — the **Methods
containing** search returns selector names with **no owning class** — is offered when the selector
merely *names* a test (`test…`); its owning test class is **resolved from the selector's implementors
only when actually run**, so drawing the menu stays a cheap, local check (no gem round-trip per
right-click). On run, a bare selector resolves to its instance-side `TestCase` implementors and:
**one** → runs it directly; **several** → **pivots the search to Implementors** (the same pivot
double-click uses) so the user picks which to run; **none** → says so.

Run Test / Debug Test are **always shown but greyed when the result is not a runnable test** (an
ordinary method, a class-side method, a method on a non-`TestCase` class, a non-`test…` bare
selector, or a bare class result) — the **greyed-means-not-applicable, never hidden** convention used
elsewhere, so the affordance stays consistently placed and discoverable. The class-lineage answer is
cached per class (`FindPane.test_case_class_by_name`, reset when results are replaced) so the at-most
one gem round-trip per distinct class is not repeated.

Running and debugging a test go through the **one shared path** every test-bearing pane uses —
`Pane.run_test_for` / `Pane.debug_test_for` (a passing run reports via `show_test_result`, a genuine
trap opens the debugger) — the same wiring behind the browser's method-list **Run Test / Debug
Test** and the class-list **Run All Tests**. See `FindPane.show_result_context_menu` in `main.py`.

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

The theme is **resolved once at startup** (the `--theme` command-line flag overrides the
configured `appearance.theme`, which overrides the OS preference via `OperatingSystemAppearance`,
falling through to a light default) and **fixed for the session** — changing it means
restarting. There is deliberately no on-the-fly switch: that would need a re-apply path through
every open tool and the diagrams' canvas redraw. Light is the host's **native** look and applies
no global styling (its per-site colours equal the original appearance, so zero regression); only a
departing theme (dark) restyles, via `ThemeApplication` — the Tk **option database** for classic-tk
widgets plus a `clam`-based `ttk.Style` for ttk widgets (the two families don't share a styling
mechanism). New colour sites read a role; new screens get themed for free.

A departing theme also has a third, narrow reach: **`ThemeApplication.install_native_dialog_overrides`**
for Tk's own dialogs that neither mechanism can reach. The native directory chooser
(`filedialog.askdirectory`) draws its file listing with a Tk-shipped `::tk::IconList` whose canvas
hardcodes a white background and black text *at construction time* — colours that beat the option
database, and a canvas item's colour ignores it entirely. Dark mixes a themed `Create` into that
class (deferring to the original via `next`, then rebinding only the canvas background and item
text to the editor roles) so the listing matches every other list instead of a white rectangle in a
dark dialog. Reach for our own themed widget before a native Tk dialog; when a native dialog is
unavoidable and shows through unthemed, patch it here rather than re-implementing Tk's dialog.

**Prefer `ttk` widgets over classic `tk` ones** (checkbuttons, radiobuttons, buttons, …) so they
pick up the `clam`-based dark styling — in particular the selected-indicator colour
(`TCheckbutton`/`TRadiobutton` `indicatorcolor` map). A classic `tk.Checkbutton`/`tk.Radiobutton`
is only reachable through the option DB and its selected indicator goes invisible on a dark
background; the browser's controls are `ttk` for exactly this reason. (Note: ttk's `cget('state')`
returns a Tcl object, not a bare `str` — compare `str(widget.cget('state'))` in tests.)

**User editor preferences** live under the top-level `appearance` key in the JSON config file,
alongside `appearance.theme`. Current keys:

| Key | Values | Default | Effect |
|---|---|---|---|
| `appearance.theme` | `"light"` / `"dark"` | OS preference, then light | Colour palette for the session |
| `appearance.tab_spacing` | positive integer | `4` | Editor tab stop width in spaces |
| `appearance.auto_format` | `true` / `false` | `false` | Whether the editor auto-formats methods on save |

The `appearance` section is preserved verbatim on every config save (it is not in the `known_keys`
set in `McpConfigurationStore.save()`), so adding a new key here never requires changes to the
save path — just a `load_*` reader method on `McpConfigurationStore`.

---

## Architectural constraints

### Event-driven: the `EventQueue` is the spine
UI components **react to published events** rather than calling each other directly. Publish a
typed event; subscribers (weak-ref callbacks, optionally `ui_context`-scoped) update themselves.
Derived views (browser columns, editor tabs, breakpoints) re-read from the image on the typed
change events; snapshot views (diagrams, inspector) opt into a generic `RefreshFromImage`. When
adding behaviour that several components care about, **add an event**, don't wire direct
cross-references. See `EventQueue` in `main.py` and `reference_mcp_ide_refresh_bridge`.

Breakpoints follow this rule concretely. A breakpoint binds to a `CompiledMethod`, which a
recompile replaces — so a recompile **re-applies** the method's breakpoints onto the new method
(remapping each to the step point nearest its stored source offset): an edit never silently
disarms a breakpoint the user can still see. Setting or clearing a breakpoint — whether from the
IDE context menu or via the MCP — publishes the one generic **`BreakpointsChanged`** event; every
view that shows breakpoints re-marks itself from it, so an open editor tab and the debugger never
disagree about where breakpoints are. (`BreakpointSet`/`BreakpointCleared` are still published, but
only as activity-log records, not as refresh triggers — subscribe to `BreakpointsChanged`.) Views
also re-read on the other typed events: the editor gutter and the **debugger frame pane** (the same
`CodePanel`, so it marks the displayed frame's method) on method display, and the **Breakpoints
pane** on `MethodsChanged`/`BreakpointsChanged`. A pane with **unsaved edits is skipped** when
re-marking: its stored offsets no longer match the edited text, and Tk is already tracking the live
marker tags as the user types.

**Step-point and breakpoint markers are visually independent.** The current step point (where
execution is paused) is shown as a character **background highlight** (`step_point_background`
theme role) **plus underline**. A breakpoint on the same character uses a distinct background
colour (`breakpoint_background`). Because both use `background`, the breakpoint's colour wins
when they coincide — but the **underline** comes from the step-point tag and is unaffected by
tag priority, so both are always visible simultaneously. Do not remove the underline from the
step-point tag; without it, landing on a breakpoint makes the step position invisible.
Breakpoint markers are applied once when source loads and tracked by Tk as the user edits; they
are **not** re-applied on every key event (`on_key_release` only re-runs syntax highlighting).
Set/Clear Breakpoint is available in **both** the regular editor context menu and the debugger
source-pane context menu — and in both, the commands are **greyed out while the editor is
read-only or has unsaved edits**. A breakpoint's source offset is captured from the live editor
text but resolved against the *compiled* method; while the buffer is dirty those two coordinate
systems have diverged, so a breakpoint set now would land at the wrong step point. The user must
save (recompile) or cancel first.

### One shared GemStone session; gem work off the UI thread
There is one `ide-session` and it runs **one GCI call at a time**. Long gem work runs on a
**worker thread** (never the Tk UI thread); results are marshalled back and all widget updates
happen on the UI thread. Gem-free UI events (e.g. announcing that an activity started) must
reach the UI **even while an MCP operation holds the session** — they bypass the
session-admission gate via `SESSION_SAFE_EVENT_NAMES`; gem-touching events still defer to avoid
a 2203 collision. Do not run IDE GCI from the event drain while the session is held.

**Gem-touching UI actions gate on `Swordfish.session_is_busy()`, not on `is_mcp_busy()` alone.**
The session runs one call at a time, so a menu command that launches gem work (a search like
Senders / Implementors / References, a Run/Debug Test, Run All Tests, a write) must be **greyed
while the session is busy with _any_ activity** — an in-flight MCP tool **or** an IDE foreground
job (a find, a test run, a debugger step). `session_is_busy()` is the superset (`current_session_activity is not None or is_mcp_busy()`); gating only on `is_mcp_busy()` leaves the
window where one IDE activity is running and a second would collide. This extends to gem work done
to *build* a menu: the class menu's **Variable References** cascade reads the gem when posted, so
`fetch_accessible_vars` returns nothing (a disabled cascade) while the session is busy rather than
issuing that read.

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
