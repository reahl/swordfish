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

    def fake_register_tools(mcp_server, allow_eval=False, allow_compile=False):
        captured['mcp_server'] = mcp_server
        captured['allow_eval'] = allow_eval
        captured['allow_compile'] = allow_compile

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
            )

    assert mcp_server is captured['mcp_server']
    assert captured['allow_eval']
    assert captured['allow_compile']
