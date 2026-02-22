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
        help='Enable gs_eval in read-only mode (disabled by default).',
    )
    parser.add_argument(
        '--allow-eval-write',
        action='store_true',
        help=(
            'Enable write-capable eval/debug-eval (requires '
            '--allow-eval and --allow-commit).'
        ),
    )
    parser.add_argument(
        '--allow-compile',
        action='store_true',
        help='Enable gs_compile_method tool (disabled by default).',
    )
    parser.add_argument(
        '--allow-commit',
        action='store_true',
        help='Enable gs_commit tool (disabled by default).',
    )
    parser.add_argument(
        '--allow-tracing',
        action='store_true',
        help='Enable gs_tracer_* and evidence tools (disabled by default).',
    )
    parser.add_argument(
        '--require-gemstone-ast',
        action='store_true',
        help=(
            'Require real GemStone AST backend for refactoring tools. '
            'When enabled, heuristic refactorings are blocked.'
        ),
    )
    arguments = parser.parse_args()
    if arguments.allow_eval_write and not arguments.allow_commit:
        parser.error('--allow-eval-write requires --allow-commit.')
    allow_eval = arguments.allow_eval or arguments.allow_eval_write
    mcp_server = create_server(
        allow_eval=allow_eval,
        allow_eval_write=arguments.allow_eval_write,
        allow_compile=arguments.allow_compile,
        allow_commit=arguments.allow_commit,
        allow_tracing=arguments.allow_tracing,
        require_gemstone_ast=arguments.require_gemstone_ast,
    )
    mcp_server.run(transport=arguments.transport)


if __name__ == '__main__':
    run_application()
