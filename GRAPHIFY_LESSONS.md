# What Swordfish can learn from graphify

Comparison of [github.com/safishamsi/graphify](https://github.com/safishamsi/graphify)
against the Swordfish MCP server, 2026-06-11.

## The two projects in one paragraph

Graphify statically parses a project with tree-sitter, builds a NetworkX
knowledge graph, clusters it, and writes pre-digested artifacts to disk
(`graph.html`, `GRAPH_REPORT.md`, `graph.json`), served by a deliberately small
MCP surface of ~8 query-shaped tools. Swordfish gives an agent a live,
reflective, transactional window into a running GemStone image through ~110
operation-shaped tools. Graphify's extraction layer is worthless for Smalltalk;
its *query vocabulary, response discipline, and artifact strategy* are the
transferable parts. Swordfish is already ahead on discoverability
(`gs_capabilities`/`gs_guidance`), write safety (preview/apply, explicit
transactions, approval gates), and data freshness — none of which graphify
attempts.

## Recommendations, ranked

### 1. A uniform token budget at one serialization chokepoint

*(best effort-to-value)*

Graphify routes every response through a single function enforcing a
caller-tunable budget (~4 chars/token, default 2000) with a visible
`... (truncated to ~N token budget)` marker. Swordfish has solved this
reactively, tool by tool — `gs_senders_overview` exists because
`gs_find_senders` blew the token limit on hot selectors. One shared
`response_budget` parameter enforced at the serialization layer in
`mcp/tools.py` hardens all 110 tools at once, and the explicit marker lets the
agent know to re-ask narrower rather than reason from silently partial data.

### 2. Conditional tool registration where policy allows

All 110 tools are currently registered unconditionally and gated at call time
(the `require_*_enabled` guards in `mcp/tools.py`). In headless mode the
policy flags are fixed at startup, so gated groups can simply be omitted from
advertisement — roughly half the surface disappears in a default read-only
session, a 10–15k-token saving per conversation in clients without deferred
tool loading. Two preservation rules:

- Keep the call-time guards as the real enforcement boundary; registration
  omission is advertising, not security.
- Add a `disabled_tool_groups` field to `gs_capabilities` (group → enabling
  flag) so omitted capabilities remain discoverable: the agent can still tell
  the user "Swordfish has a tracer, but you'd need `--allow-tracing`".

Integrated-IDE mode is harder because permissions are runtime-mutable
(`Swordfish.current_permissions`); that needs MCP `tools/list_changed`
notifications (client support varies) or simply retains today's behavior there.

### 3. A shared confidence vocabulary for derived results

Graphify tags every relationship `EXTRACTED` / `INFERRED` / `AMBIGUOUS`. The
pending senders-classification work already has this shape
(`direct_send`/`reflective_send`/`reference_only`); generalizing to one fixed
vocabulary across tools gives agents a single trust rule: act on extracted,
verify inferred. This matters more, not less, given the tracer's state — see
recommendation 7.

### 4. Graph query vocabulary over live-image ground truth

Graphify's most-used tools are "what neighbors this?" (`get_neighbors`) and
"how are these two related?" (`shortest_path`). Swordfish has all the raw
edges — hierarchy, `ClassOrganizer >> referencesTo:`, senders/implementors —
but no graph abstraction over them, so a relatedness question costs an agent
five or six calls plus manual joining. A `gs_class_neighborhood` (classes
within N hops, edges typed inherits/references/sends-to) and a
`gs_relationship_path` would serve agents and could auto-populate the existing
UML tab instead of one-class-at-a-time `gs_ide_*_uml` calls.

**Cheap variant worth prototyping first:** export Swordfish's edges as
graphify's documented `graph.json` format and reuse graphify's language-blind
presentation layer (interactive `graph.html` viewer, report generation, Leiden
community clustering) for free, over `EXTRACTED`-quality data its own
extractor could never produce for Smalltalk.

### 5. Generated orientation artifacts on disk

Graphify's `GRAPH_REPORT.md` (god nodes, surprising cross-module connections,
suggested questions) is its cheapest, highest-value feature for a newcomer:
orientation in one cheap file read instead of a dozen listing calls. A
Swordfish package/image "tour" written into the FileTree-sync repo would do
the same — particularly valuable for legacy-image archaeology, where category
organization lies and reference clustering tells the truth. Scope rule:
orientation material only, where slight staleness is fine; anything an agent
acts on (senders before a rename, source before an edit) stays a live query.

### 6. Change-impact before commit — an honest heuristic

The change set between `gs_begin` and `gs_commit` is already explicit, so a
senders-traversal blast radius ("these classes and test classes are reachable
from your changed selectors") is feasible today and slots into the
preview/apply philosophy as a "preview" for the commit itself. But because
test-coverage discovery is acknowledged to be dodgy, this must be advertised
as what it is: an *inferred* suggestion that prioritizes tests, never a
substitute for the full suite. Framed that way it still shortens the edit-test
loop; framed as coverage it would invite agents to skip tests that matter.
Recommendation 3's vocabulary is exactly the honest label for it.

### 7. Tracer-confirmed (`OBSERVED`) call edges — deferred

Runtime confirmation of reflective sends would be a confidence tier no static
tool can reach: graphify's ceiling (`EXTRACTED`) is Swordfish's floor, and
observed-at-runtime sits above both. The premise does not hold yet: the tracer
is experimental, instruments **one method at a time**, and there is no
reliable way to select tests that exercise a method under trace. So this
inverts from "feature to build" into "the tracer's business case":
package- or image-wide instrumentation is the prerequisite, and dynamic edge
confirmation is the payoff if the tracer ever matures. Until then, lead with
static/reflective answers tagged honestly per recommendation 3.

## On using graphify alongside Swordfish

**Not over Smalltalk source.** No tree-sitter Smalltalk grammar exists, so
`.st` files (e.g. the FileTree-synced Cypress repo) would miss graphify's
local-AST path and fall into its non-code fallback — which **uploads content
to the configured LLM backend**. That inverts graphify's "code stays local"
privacy promise precisely on the proprietary code, returns LLM-guessed
relationships in a language where even real parsers cannot resolve dynamic
sends, and goes stale at the first recompile. Inferior, older, and leakier
than asking the image.

**Fine for the non-Smalltalk halo.** Design docs, PDFs, the Python side of the
stack, infra config — graphify's home turf, Swordfish's blind spot. The two
are non-overlapping there. If the `graph.json` exporter from recommendation 4
is built, the doc-halo graph and the image graph can even join into one.

## Suggested order

Recommendations 1 (token budget) and 2 (headless conditional registration +
capabilities field) are small, independent hardening wins. Then the
`graph.json` exporter as a low-commitment experiment to test whether
graph-shaped views of the image are actually useful, before investing in
native neighborhood/path tools. Change-impact (6) when the senders
classification lands, since it depends on honest edge labels. Tracer work (7)
only if and when the dynamic-confirmation payoff justifies building
multi-method instrumentation.
