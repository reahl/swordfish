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

from reahl.swordfish.gemstone import DomainException
from reahl.swordfish.gemstone import GemstoneBrowserSession
from reahl.swordfish.gemstone import close_session
from reahl.swordfish.gemstone import create_linked_session
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

    def new_gs_begin(self):
        return self.registered_mcp_tools['gs_begin']

    def new_gs_commit(self):
        return self.registered_mcp_tools['gs_commit']

    def new_gs_abort(self):
        return self.registered_mcp_tools['gs_abort']

    def new_gs_list_packages(self):
        return self.registered_mcp_tools['gs_list_packages']

    def new_gs_list_classes(self):
        return self.registered_mcp_tools['gs_list_classes']

    def new_gs_list_method_categories(self):
        return self.registered_mcp_tools['gs_list_method_categories']

    def new_gs_list_methods(self):
        return self.registered_mcp_tools['gs_list_methods']

    def new_gs_get_method_source(self):
        return self.registered_mcp_tools['gs_get_method_source']

    def new_gs_find_classes(self):
        return self.registered_mcp_tools['gs_find_classes']

    def new_gs_find_selectors(self):
        return self.registered_mcp_tools['gs_find_selectors']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def evaluate_python_value(self, source):
        eval_result = self.gs_eval(self.connection_id, source)
        assert eval_result['ok'], eval_result
        return eval_result['output']['result']['python_value']


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


@uses(running_stone=RunningStoneFixture)
class LiveBrowserSessionFixture(Fixture):
    @set_up
    def prepare_session_slot(self):
        self.gemstone_session = None

    @set_up
    def open_linked_session(self):
        self.gemstone_session = create_linked_session(
            'DataCurator',
            'swordfish',
            'gs64stone',
        )

    @set_up
    def begin_transaction(self):
        with expected(NoException):
            self.gemstone_session.begin()

    @set_up
    def new_browser_session(self):
        return GemstoneBrowserSession(self.gemstone_session)

    @tear_down
    def abort_transaction(self):
        if self.gemstone_session is not None:
            with expected(NoException):
                self.gemstone_session.abort()

    @tear_down
    def close_linked_session(self):
        if self.gemstone_session is not None:
            with expected(NoException):
                close_session(self.gemstone_session)

    def new_known_package_name(self):
        return self.gemstone_session.resolve_symbol('Object').category().to_py


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


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_list_packages_returns_non_empty_result(live_connection):
    package_result = live_connection.gs_list_packages(live_connection.connection_id)
    assert package_result['ok'], package_result
    assert package_result['packages']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_abort_discards_uncommitted_changes(live_connection):
    symbol_name = 'MCP_TEST_ABORT_%s' % live_connection.connection_id.split('-')[0]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    live_connection.evaluate_python_value(
        "UserGlobals at: #'%s' put: 123" % symbol_name
    )
    assert live_connection.evaluate_python_value(
        "UserGlobals includesKey: #'%s'" % symbol_name
    )
    abort_result = live_connection.gs_abort(live_connection.connection_id)
    assert abort_result['ok'], abort_result
    assert not live_connection.evaluate_python_value(
        "UserGlobals includesKey: #'%s'" % symbol_name
    )


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_commit_persists_changes_until_removed(live_connection):
    symbol_name = 'MCP_TEST_COMMIT_%s' % live_connection.connection_id.split('-')[0]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    live_connection.evaluate_python_value(
        "UserGlobals at: #'%s' put: 321" % symbol_name
    )
    commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert commit_result['ok'], commit_result
    assert live_connection.evaluate_python_value(
        "UserGlobals includesKey: #'%s'" % symbol_name
    )
    begin_cleanup_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_cleanup_result['ok'], begin_cleanup_result
    live_connection.evaluate_python_value(
        "UserGlobals removeKey: #'%s' ifAbsent: []" % symbol_name
    )
    cleanup_commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert cleanup_commit_result['ok'], cleanup_commit_result


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_lists_classes_for_a_known_package(browser_fixture):
    classes = browser_fixture.browser_session.list_classes(
        browser_fixture.known_package_name
    )
    assert classes


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_lists_method_categories_with_all_first(browser_fixture):
    categories = browser_fixture.browser_session.list_method_categories(
        'Object',
        True,
    )
    assert categories[0] == 'all'


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_lists_methods_for_all_category(browser_fixture):
    selectors = browser_fixture.browser_session.list_methods(
        'Object',
        'all',
        True,
    )
    assert selectors
    assert 'yourself' in selectors


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_reads_method_source(browser_fixture):
    source = browser_fixture.browser_session.get_method_source(
        'Object',
        'yourself',
        True,
    )
    assert 'yourself' in source


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_finds_matching_class_names(browser_fixture):
    class_names = browser_fixture.browser_session.find_classes('Date')
    assert class_names


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_rejects_invalid_class_search_regex(browser_fixture):
    with expected(DomainException):
        browser_fixture.browser_session.find_classes('[')


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_finds_matching_selectors(browser_fixture):
    selectors = browser_fixture.browser_session.find_selectors('yourself')
    assert 'yourself' in selectors


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_finds_implementors_with_class_side_information(browser_fixture):
    implementors = browser_fixture.browser_session.find_implementors('yourself')
    assert {
        'class_name': 'Object',
        'show_instance_side': True,
    } in implementors
