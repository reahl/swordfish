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
    arguments = parser.parse_args()
    mcp_server = create_server()
    mcp_server.run(transport=arguments.transport)


if __name__ == '__main__':
    run_application()
