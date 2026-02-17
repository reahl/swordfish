import os
import subprocess

from reahl.tofu import Fixture
from reahl.tofu import NoException
from reahl.tofu import expected
from reahl.tofu import scenario
from reahl.tofu import scope
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import uses
from reahl.tofu import with_fixtures

from reahl.ptongue.gemstonecontrol import Stone

from reahl.swordfish.mcp.session_registry import clear_connections
from reahl.swordfish.mcp.session_registry import get_session
from reahl.swordfish.mcp.session_registry import has_connection
from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


@scope('session')
class RunningStoneFixture(Fixture):
    @set_up
    def ensure_gemstone_environment(self):
        assert os.environ.get('GEMSTONE'), (
            'AI: GEMSTONE environment is required for live integration tests. '
            'Run tests from a shell that sourced ~/.profile.'
        )
        self.stone_started_by_fixture = False

    @set_up
    def ensure_stone_running(self):
        if not self.is_stone_running():
            with expected(NoException):
                Stone().start()
            self.stone_started_by_fixture = True
        assert self.is_stone_running()

    @tear_down
    def stop_stone_if_fixture_started_it(self):
        if self.stone_started_by_fixture:
            with expected(NoException):
                Stone().stop()

    def is_stone_running(self):
        command_result = subprocess.run(
            ['bash', '-lc', 'gslist'],
            capture_output=True,
            text=True,
            check=False,
        )
        assert command_result.returncode == 0, command_result.stderr
        return 'Stone       gs64stone' in command_result.stdout


@uses(running_stone=RunningStoneFixture)
class LiveMcpConnectionFixture(Fixture):
    @set_up
    def prepare_registry(self):
        self.active_connection_id = None
        clear_connections()

    @tear_down
    def close_connection_and_abort(self):
        if self.active_connection_id:
            assert has_connection(self.active_connection_id)
            with expected(NoException):
                get_session(self.active_connection_id).abort()
            disconnect_result = self.gs_disconnect(self.active_connection_id)
            assert disconnect_result['ok'], disconnect_result
        clear_connections()

    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(registrar)
        return registrar.registered_tools_by_name

    def new_connect_result(self):
        connect_result = self.gs_connect(
            'linked',
            'DataCurator',
            'swordfish',
            stone_name='gs64stone',
        )
        assert connect_result['ok'], connect_result
        self.active_connection_id = connect_result['connection_id']
        return connect_result

    def new_connection_id(self):
        return self.connect_result['connection_id']

    def new_gs_connect(self):
        return self.registered_mcp_tools['gs_connect']

    def new_gs_disconnect(self):
        return self.registered_mcp_tools['gs_disconnect']

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']


class LiveEvalScenarios(Fixture):
    @scenario
    def evaluate_small_integer_expression(self):
        """AI: Arithmetic evaluation returns a SmallInteger with convertible values."""
        self.source = '3 + 4'
        self.expected_class_name = 'SmallInteger'
        self.expected_class_name_suffix = None
        self.expected_python_value = 7
        self.expected_string_value = '7'
        self.has_expected_class_name_suffix = False
        self.has_expected_python_value = True
        self.has_expected_string_value = True

    @scenario
    def evaluate_domain_object_expression(self):
        """AI: Domain object evaluation reports class and a textual representation."""
        self.source = 'Date today'
        self.expected_class_name_suffix = 'Date'
        self.expected_python_value = None
        self.expected_string_value = None
        self.has_expected_python_value = False
        self.has_expected_string_value = False
        self.has_expected_class_name_suffix = True


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_connect_returns_session_summary(live_connection):
    session_summary = live_connection.connect_result['session']
    assert live_connection.connect_result['connection_mode'] == 'linked'
    assert session_summary['user_name'] == 'DataCurator'
    assert 'gs64stone' in session_summary['stone_name']
    assert session_summary['session_id'] > 0


@with_fixtures(LiveMcpConnectionFixture, LiveEvalScenarios)
def test_live_gs_eval_reports_expected_result_shape(live_connection, live_eval):
    eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        live_eval.source,
    )
    assert eval_result['ok'], eval_result
    result_payload = eval_result['output']['result']
    if live_eval.has_expected_class_name_suffix:
        assert result_payload['class_name'].endswith(
            live_eval.expected_class_name_suffix
        )
    else:
        assert result_payload['class_name'] == live_eval.expected_class_name

    if live_eval.has_expected_python_value:
        assert result_payload['python_value'] == live_eval.expected_python_value

    if live_eval.has_expected_string_value:
        assert result_payload['string_value'] == live_eval.expected_string_value
