from reahl.tofu import Fixture
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.debugging import GemstoneDebugActionOutcome
from reahl.swordfish.mcp.debug_registry import add_debug_session
from reahl.swordfish.mcp.debug_registry import clear_debug_sessions
from reahl.swordfish.mcp.debug_registry import has_debug_session
from reahl.swordfish.mcp.session_registry import add_connection
from reahl.swordfish.mcp.session_registry import clear_connections
from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


class FakeRestartableDebugSession:
    def __init__(self):
        self.restart_levels = []
        self.exception = type(
            'FakeGemstoneError',
            (),
            {
                '__str__': lambda self: 'debug suspended',
                'number': 6000,
                'is_fatal': False,
                'reason': 'halt',
            },
        )()

    def restart_frame(self, level):
        self.restart_levels.append(level)
        return GemstoneDebugActionOutcome(False)

    def call_stack(self):
        return [
            type(
                'FakeFrame',
                (),
                {
                    'level': 1,
                    'class_name': 'OrderLine',
                    'method_name': 'alpha',
                    'method_source': 'alpha\n    self beta',
                    'step_point_offset': 1,
                },
            )()
        ]

    def rendered_result_payload(self, result):
        return {'result': result}


class McpDebugToolsFixture(Fixture):
    @set_up
    def clear_registries_before_test(self):
        clear_connections()
        clear_debug_sessions()

    @tear_down
    def clear_registries_after_test(self):
        clear_debug_sessions()
        clear_connections()

    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=True,
        )
        return registrar.registered_tools_by_name

    def new_connection_id(self):
        return add_connection(
            object(),
            {
                'connection_mode': 'linked',
                'transaction_active': True,
            },
        )

    def new_gs_debug_restart_frame(self):
        return self.registered_mcp_tools['gs_debug_restart_frame']

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']


@with_fixtures(McpDebugToolsFixture)
def test_gs_debug_restart_frame_restarts_selected_level_without_finishing(
    tools_fixture,
):
    """AI: Restart-frame tool should keep debug session active and return refreshed stack payload."""
    debug_session = FakeRestartableDebugSession()
    debug_id = add_debug_session(
        tools_fixture.connection_id,
        debug_session,
    )

    restart_result = tools_fixture.gs_debug_restart_frame(
        tools_fixture.connection_id,
        debug_id,
        level=4,
    )

    assert restart_result['ok'], restart_result
    assert not restart_result['completed']
    assert restart_result['debug']['stack_frames'][0]['level'] == 1
    assert debug_session.restart_levels == [4]
    assert has_debug_session(debug_id)


@with_fixtures(McpDebugToolsFixture)
def test_gs_capabilities_debugging_group_includes_restart_frame_tool(
    tools_fixture,
):
    """AI: Capability discovery should advertise restart-frame as a debugger stack-control action."""
    capabilities_result = tools_fixture.gs_capabilities()

    assert capabilities_result['ok'], capabilities_result
    debugging_tools = capabilities_result['tool_groups']['debugging']
    assert 'gs_debug_restart_frame' in debugging_tools
