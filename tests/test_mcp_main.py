from unittest.mock import patch

from reahl.swordfish.mcp.main import run_application


def test_run_application_delegates_to_unified_swordfish_cli():
    """AI: Legacy MCP module entry delegates to swordfish CLI with mcp-headless as default mode."""
    with patch(
        'reahl.swordfish.mcp.main.run_swordfish_application'
    ) as run_swordfish_application:
        run_application()
    run_swordfish_application.assert_called_once_with(
        default_mode='mcp-headless'
    )
