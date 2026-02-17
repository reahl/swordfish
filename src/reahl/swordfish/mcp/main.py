import argparse

from reahl.swordfish.mcp.server import create_server


def run_application():
    parser = argparse.ArgumentParser(
        description='Run SwordfishMCP server.'
    )
    parser.add_argument(
        '--transport',
        default='stdio',
        choices=['stdio'],
        help='MCP transport type.',
    )
    parser.add_argument(
        '--allow-eval',
        action='store_true',
        help='Enable gs_eval tool (disabled by default).',
    )
    parser.add_argument(
        '--allow-compile',
        action='store_true',
        help='Enable gs_compile_method tool (disabled by default).',
    )
    arguments = parser.parse_args()
    mcp_server = create_server(
        allow_eval=arguments.allow_eval,
        allow_compile=arguments.allow_compile,
    )
    mcp_server.run(transport=arguments.transport)


if __name__ == '__main__':
    run_application()
