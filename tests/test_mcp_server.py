from importlib.util import find_spec
from unittest.mock import patch

from reahl.tofu import NoException
from reahl.tofu import expected

from reahl.swordfish.mcp.server import create_server
from reahl.swordfish.mcp.server import McpDependencyNotInstalled
from reahl.swordfish.mcp.server import import_fast_mcp


def test_import_fast_mcp_matches_environment_dependency_state():
    expected_exception = (
        McpDependencyNotInstalled
        if find_spec('mcp.server.fastmcp') is None
        else NoException
    )
    with expected(expected_exception):
        import_fast_mcp()


def test_create_server_passes_policy_flags_to_tool_registration():
    class FakeServer:
        def __init__(self):
            self.name = None
            self.version = None

    def fake_fast_mcp(name, version):
        fake_server = FakeServer()
        fake_server.name = name
        fake_server.version = version
        return fake_server

    captured = {}

    def fake_register_tools(
        mcp_server,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
    ):
        captured['mcp_server'] = mcp_server
        captured['allow_eval'] = allow_eval
        captured['allow_compile'] = allow_compile
        captured['allow_commit'] = allow_commit
        captured['allow_tracing'] = allow_tracing
        captured['allow_commit_when_gui'] = allow_commit_when_gui
        captured['integrated_session_state'] = integrated_session_state
        captured['require_gemstone_ast'] = require_gemstone_ast

    with patch(
        'reahl.swordfish.mcp.server.import_fast_mcp',
        return_value=fake_fast_mcp,
    ):
        with patch(
            'reahl.swordfish.mcp.server.import_tool_registration',
            return_value=fake_register_tools,
        ):
            mcp_server = create_server(
                allow_eval=True,
                allow_compile=True,
                allow_commit=True,
                allow_tracing=True,
                allow_commit_when_gui=True,
                require_gemstone_ast=True,
            )

    assert mcp_server is captured['mcp_server']
    assert captured['allow_eval']
    assert captured['allow_compile']
    assert captured['allow_commit']
    assert captured['allow_tracing']
    assert captured['allow_commit_when_gui']
    assert captured['integrated_session_state'] is not None
    assert captured['require_gemstone_ast']


def test_create_server_supports_fast_mcp_without_version_argument():
    class FakeServer:
        def __init__(self):
            self.name = None

    def fake_fast_mcp(name):
        fake_server = FakeServer()
        fake_server.name = name
        return fake_server

    captured = {}

    def fake_register_tools(
        mcp_server,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
    ):
        captured['mcp_server'] = mcp_server
        captured['allow_eval'] = allow_eval
        captured['allow_compile'] = allow_compile
        captured['allow_commit'] = allow_commit
        captured['allow_tracing'] = allow_tracing
        captured['require_gemstone_ast'] = require_gemstone_ast

    with patch(
        'reahl.swordfish.mcp.server.import_fast_mcp',
        return_value=fake_fast_mcp,
    ):
        with patch(
            'reahl.swordfish.mcp.server.import_tool_registration',
            return_value=fake_register_tools,
        ):
            mcp_server = create_server(
                allow_eval=False,
                allow_compile=False,
                allow_commit=False,
                allow_tracing=False,
                require_gemstone_ast=False,
            )

    assert mcp_server is captured['mcp_server']
    assert mcp_server.name == 'SwordfishMCP'
    assert not captured['allow_commit']
    assert not captured['allow_tracing']
    assert not captured['require_gemstone_ast']


def test_create_server_allows_eval_without_extra_approval_configuration():
    with expected(NoException):
        create_server(
            allow_eval=True,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=False,
            require_gemstone_ast=False,
        )


def test_create_server_allows_commit_enabled_without_extra_approval_configuration():
    class FakeServer:
        pass

    def fake_fast_mcp(name, version):
        return FakeServer()

    def fake_register_tools(
        mcp_server,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
    ):
        pass

    with patch(
        'reahl.swordfish.mcp.server.import_fast_mcp',
        return_value=fake_fast_mcp,
    ):
        with patch(
            'reahl.swordfish.mcp.server.import_tool_registration',
            return_value=fake_register_tools,
        ):
            with expected(NoException):
                create_server(
                    allow_eval=False,
                    allow_compile=True,
                    allow_commit=True,
                    allow_tracing=False,
                    require_gemstone_ast=False,
                )


def test_create_server_passes_commit_policy_flags_in_confirmation_mode():
    class FakeServer:
        pass

    def fake_fast_mcp(name, version):
        return FakeServer()

    captured = {}

    def fake_register_tools(
        mcp_server,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
    ):
        captured['allow_commit'] = allow_commit
        captured['allow_compile'] = allow_compile

    with patch(
        'reahl.swordfish.mcp.server.import_fast_mcp',
        return_value=fake_fast_mcp,
    ):
        with patch(
            'reahl.swordfish.mcp.server.import_tool_registration',
            return_value=fake_register_tools,
        ):
            with expected(NoException):
                create_server(
                    allow_eval=False,
                    allow_compile=True,
                    allow_commit=True,
                    allow_tracing=False,
                    require_gemstone_ast=False,
                )

    assert captured['allow_commit']
    assert captured['allow_compile']


def test_create_server_passes_streamable_http_network_configuration():
    class FakeServer:
        pass

    captured = {}

    def fake_fast_mcp(
        name,
        version,
        host='127.0.0.1',
        port=8000,
        streamable_http_path='/mcp',
    ):
        fake_server = FakeServer()
        captured['name'] = name
        captured['version'] = version
        captured['host'] = host
        captured['port'] = port
        captured['streamable_http_path'] = streamable_http_path
        return fake_server

    def fake_register_tools(
        mcp_server,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
    ):
        pass

    with patch(
        'reahl.swordfish.mcp.server.import_fast_mcp',
        return_value=fake_fast_mcp,
    ):
        with patch(
            'reahl.swordfish.mcp.server.import_tool_registration',
            return_value=fake_register_tools,
        ):
            create_server(
                allow_eval=False,
                allow_compile=True,
                allow_commit=True,
                allow_tracing=False,
                mcp_host='127.0.0.1',
                mcp_port=9177,
                mcp_streamable_http_path='/running-ide',
                require_gemstone_ast=False,
            )

    assert captured['name'] == 'SwordfishMCP'
    assert captured['host'] == '127.0.0.1'
    assert captured['port'] == 9177
    assert captured['streamable_http_path'] == '/running-ide'
