'''AI: Tests for the MCP tools that configure on-disk FileTree mirroring. The configuration
is a single shared setting (not per-connection), so these tools need no GemStone session.'''

import os

from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


def registered_sync_tools():
    registrar = McpToolRegistrar()
    register_tools(registrar)
    return registrar.registered_tools_by_name


def test_setting_the_root_enables_mirroring_and_status_reflects_it(tmp_path, monkeypatch):
    '''AI: Pointing the tools at a repository enables mirroring, counts its tracked packages,
    and is visible through gs_sync_status (the same shared setting the IDE reads).'''
    monkeypatch.setenv(
        'SWORDFISH_FILETREE_SYNC_CONFIG', os.path.join(str(tmp_path), 'config.json')
    )
    root = os.path.join(str(tmp_path), 'monticello')
    os.makedirs(os.path.join(root, 'Wonka-Amount-Core.package'))
    os.makedirs(os.path.join(root, 'Wonka-Entities-Core.package'))
    tools = registered_sync_tools()

    set_result = tools['gs_sync_set_root'](root)
    assert set_result['ok']
    assert set_result['active']
    assert set_result['root_path'] == root
    assert set_result['tracked_package_count'] == 2

    status = tools['gs_sync_status']()
    assert status['active']
    assert status['root_path'] == root


def test_disabling_keeps_the_root_but_stops_mirroring(tmp_path, monkeypatch):
    '''AI: Disabling turns mirroring off while remembering the configured repository.'''
    monkeypatch.setenv(
        'SWORDFISH_FILETREE_SYNC_CONFIG', os.path.join(str(tmp_path), 'config.json')
    )
    root = os.path.join(str(tmp_path), 'monticello')
    os.makedirs(os.path.join(root, 'Wonka-Amount-Core.package'))
    tools = registered_sync_tools()
    tools['gs_sync_set_root'](root)

    disabled = tools['gs_sync_disable']()
    assert disabled['ok']
    assert not disabled['active']
    assert not disabled['enabled']
    assert disabled['root_path'] == root


def test_setting_a_missing_directory_is_rejected(tmp_path, monkeypatch):
    '''AI: A root that is not an existing directory is refused, so mirroring never points at
    a path that cannot hold the repository.'''
    monkeypatch.setenv(
        'SWORDFISH_FILETREE_SYNC_CONFIG', os.path.join(str(tmp_path), 'config.json')
    )
    tools = registered_sync_tools()
    result = tools['gs_sync_set_root'](os.path.join(str(tmp_path), 'no-such-dir'))
    assert not result['ok']
    assert 'existing directory' in result['error']['message']
