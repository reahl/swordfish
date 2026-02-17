from importlib.util import find_spec

from reahl.tofu import NoException
from reahl.tofu import expected

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
