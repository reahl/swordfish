import inspect

from reahl.swordfish import __version__


class McpDependencyNotInstalled(Exception):
    pass


def import_fast_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as module_not_found_error:
        raise McpDependencyNotInstalled(
            'SwordfishMCP requires the mcp package. '
            'Install with: pip install reahl-swordfish'
        ) from module_not_found_error
    return FastMCP


def create_server(
    allow_eval=False,
    allow_compile=False,
    allow_commit=False,
    allow_tracing=False,
    eval_approval_code='',
    require_gemstone_ast=False,
):
    if allow_eval and not eval_approval_code.strip():
        raise ValueError('allow_eval requires eval_approval_code.')
    fast_mcp = import_fast_mcp()
    register_tools = import_tool_registration()
    try:
        constructor_signature = inspect.signature(fast_mcp)
    except (TypeError, ValueError):
        constructor_signature = None
    supports_keyword_arguments = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in (
            constructor_signature.parameters.values()
            if constructor_signature
            else []
        )
    )
    server_arguments = {'name': 'SwordfishMCP'}
    if (
        supports_keyword_arguments
        or (
            constructor_signature
            and 'version' in constructor_signature.parameters
        )
    ):
        server_arguments['version'] = __version__
    mcp_server = fast_mcp(**server_arguments)
    register_tools(
        mcp_server,
        allow_eval=allow_eval,
        allow_compile=allow_compile,
        allow_commit=allow_commit,
        allow_tracing=allow_tracing,
        eval_approval_code=eval_approval_code,
        require_gemstone_ast=require_gemstone_ast,
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
