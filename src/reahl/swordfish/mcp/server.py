from reahl.swordfish import __version__


class McpDependencyNotInstalled(Exception):
    pass


def import_fast_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as module_not_found_error:
        raise McpDependencyNotInstalled(
            'SwordfishMCP requires the mcp package. '
            "Install with: pip install 'reahl-swordfish[mcp]'"
        ) from module_not_found_error
    return FastMCP


def create_server(
    allow_eval=False,
    allow_compile=False,
):
    fast_mcp = import_fast_mcp()
    register_tools = import_tool_registration()
    mcp_server = fast_mcp(name='SwordfishMCP', version=__version__)
    register_tools(
        mcp_server,
        allow_eval=allow_eval,
        allow_compile=allow_compile,
    )
    return mcp_server


def import_tool_registration():
    try:
        from reahl.swordfish.mcp.tools import register_tools
    except ModuleNotFoundError as module_not_found_error:
        if module_not_found_error.name == 'reahl.ptongue':
            raise McpDependencyNotInstalled(
                'SwordfishMCP requires reahl-parseltongue. '
                'Install project dependencies first.'
            ) from module_not_found_error
        raise
    return register_tools
