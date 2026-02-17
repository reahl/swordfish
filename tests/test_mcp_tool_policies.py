from reahl.tofu import Fixture
from reahl.tofu import with_fixtures

from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


class RestrictedToolsFixture(Fixture):
    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(registrar)
        return registrar.registered_tools_by_name

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']


class AllowedToolsFixture(Fixture):
    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
        )
        return registrar.registered_tools_by_name

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']


@with_fixtures(RestrictedToolsFixture)
def test_gs_eval_is_disabled_by_default(tools_fixture):
    eval_result = tools_fixture.gs_eval('missing-connection-id', '3 + 4')
    assert not eval_result['ok']
    assert eval_result['error']['message'] == (
        'gs_eval is disabled. '
        'Start swordfish-mcp with --allow-eval to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_compile_method_is_disabled_by_default(tools_fixture):
    compile_result = tools_fixture.gs_compile_method(
        'missing-connection-id',
        'Object',
        'foo ^1',
        True,
    )
    assert not compile_result['ok']
    assert compile_result['error']['message'] == (
        'gs_compile_method is disabled. '
        'Start swordfish-mcp with --allow-compile to enable.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_eval_checks_connection_when_allowed(tools_fixture):
    eval_result = tools_fixture.gs_eval('missing-connection-id', '3 + 4')
    assert not eval_result['ok']
    assert eval_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_compile_method_checks_connection_when_allowed(tools_fixture):
    compile_result = tools_fixture.gs_compile_method(
        'missing-connection-id',
        'Object',
        'foo ^1',
        True,
    )
    assert not compile_result['ok']
    assert compile_result['error']['message'] == 'Unknown connection_id.'
