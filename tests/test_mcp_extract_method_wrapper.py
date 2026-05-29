from reahl.tofu import Fixture, set_up, tear_down, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.mcp.session_registry import (
    add_connection,
    clear_connections,
)
from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


class FakeGemstoneSession:
    """AI: Minimal stand-in for a real GemStone session — never read; only
    needs to live in the registry so get_browser_session() resolves."""


class McpExtractWrapperFixture(Fixture):
    """AI: Drives gs_preview_extract_method end-to-end through the MCP
    wrapper, stubbing GemstoneBrowserSession.method_extract_preview to
    record what the wrapper actually passes down. This isolates the MCP
    layer's validation and translation from the browser implementation."""

    @set_up
    def install_recording_browser_method(self):
        clear_connections()
        self.recorded_extract_call = None
        self.original_method_extract_preview = (
            GemstoneBrowserSession.method_extract_preview
        )

        def recording_method_extract_preview(
            browser_session,
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        ):
            self.recorded_extract_call = {
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'new_selector': new_selector,
                'statement_indexes': statement_indexes,
            }
            return {'preview_ok': True}

        GemstoneBrowserSession.method_extract_preview = (
            recording_method_extract_preview
        )
        self.connection_id = add_connection(
            FakeGemstoneSession(),
            {'connection_mode': 'linked'},
        )
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_source_read=True,
            allow_source_write=True,
            experimental=True,
        )
        self.registered_mcp_tools = registrar.registered_tools_by_name

    @tear_down
    def restore_browser_method(self):
        GemstoneBrowserSession.method_extract_preview = (
            self.original_method_extract_preview
        )
        clear_connections()

    def new_gs_preview_extract_method(self):
        return self.registered_mcp_tools['gs_preview_extract_method']


@with_fixtures(McpExtractWrapperFixture)
def test_preview_extract_at_mcp_layer_accepts_keyword_selector(fixture):
    """AI: The underlying method_extract_plan already supports keyword
    selectors for captured caller variables. The MCP wrapper used to
    short-circuit any selector containing ':' with 'must be a unary
    selector', which contradicted its own advice on the captured-variable
    path. The wrapper should hand keyword selectors through to the browser."""
    result = fixture.gs_preview_extract_method(
        fixture.connection_id,
        'OrderLine',
        'buildFrom:',
        'extractedComputeTmp:',
        [1],
    )

    assert result['ok'], result
    assert (
        fixture.recorded_extract_call['new_selector']
        == 'extractedComputeTmp:'
    )


@with_fixtures(McpExtractWrapperFixture)
def test_preview_extract_at_mcp_layer_accepts_zero_based_statement_indexes(
    fixture,
):
    """AI: gs_method_ast advertises node_offsets_origin='zero_based' and
    emits 'statements[0]', 'statements[1]'. The extract MCP wrapper must
    accept the same origin so a caller can pipe AST output straight back
    without an off-by-one. Internally the browser layer keeps its
    1-based statement_index, so the wrapper translates."""
    result = fixture.gs_preview_extract_method(
        fixture.connection_id,
        'OrderLine',
        'exampleMethod',
        'extractedFirstStep',
        [0, 1],
    )

    assert result['ok'], result
    # AI: The browser layer keeps a one-based statement_index, so the
    # wrapper translates on the way down.
    assert fixture.recorded_extract_call['statement_indexes'] == [1, 2]
    # AI: But the wrapper's response echoes the zero-based contract the
    # caller passed in.
    assert result['statement_indexes'] == [0, 1]
