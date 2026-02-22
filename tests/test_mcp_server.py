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
        allow_eval_write=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        require_gemstone_ast=False,
    ):
        captured['mcp_server'] = mcp_server
        captured['allow_eval'] = allow_eval
        captured['allow_eval_write'] = allow_eval_write
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
                allow_eval=True,
                allow_eval_write=True,
                allow_compile=True,
                allow_commit=True,
                allow_tracing=True,
                require_gemstone_ast=True,
            )

    assert mcp_server is captured['mcp_server']
    assert captured['allow_eval']
    assert captured['allow_eval_write']
    assert captured['allow_compile']
    assert captured['allow_commit']
    assert captured['allow_tracing']
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
        allow_eval_write=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        require_gemstone_ast=False,
    ):
        captured['mcp_server'] = mcp_server
        captured['allow_eval'] = allow_eval
        captured['allow_eval_write'] = allow_eval_write
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
                allow_eval_write=False,
                allow_compile=False,
                allow_commit=False,
                allow_tracing=False,
                require_gemstone_ast=False,
            )

    assert mcp_server is captured['mcp_server']
    assert mcp_server.name == 'SwordfishMCP'
    assert not captured['allow_commit']
    assert not captured['allow_eval_write']
    assert not captured['allow_tracing']
    assert not captured['require_gemstone_ast']


def test_create_server_rejects_eval_write_without_commit_permission():
    with expected(ValueError):
        create_server(
            allow_eval=True,
            allow_eval_write=True,
            allow_compile=True,
            allow_commit=False,
            allow_tracing=False,
            require_gemstone_ast=False,
        )
