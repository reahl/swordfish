import os
import subprocess
import sys
import uuid

from reahl.tofu import Fixture
from reahl.tofu import NoException
from reahl.tofu import expected
from reahl.tofu import scenario
from reahl.tofu import scope
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import uses
from reahl.tofu import with_fixtures

from reahl.ptongue import GemstoneError
from reahl.ptongue.gemstonecontrol import Stone

from reahl.swordfish.gemstone import DomainException
from reahl.swordfish.gemstone import GemstoneBrowserSession
from reahl.swordfish.gemstone import GemstoneDebugSession
from reahl.swordfish.gemstone import close_session
from reahl.swordfish.gemstone import create_linked_session
from reahl.swordfish.mcp.debug_registry import clear_debug_sessions
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
        clear_debug_sessions()
        clear_connections()

    @tear_down
    def close_connection_and_abort(self):
        if self.active_connection_id:
            assert has_connection(self.active_connection_id)
            with expected(NoException):
                get_session(self.active_connection_id).abort()
            disconnect_result = self.gs_disconnect(self.active_connection_id)
            assert disconnect_result['ok'], disconnect_result
        clear_debug_sessions()
        clear_connections()

    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
        )
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

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']

    def new_gs_get_class_definition(self):
        return self.registered_mcp_tools['gs_get_class_definition']

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_create_test_case_class(self):
        return self.registered_mcp_tools['gs_create_test_case_class']

    def new_gs_delete_class(self):
        return self.registered_mcp_tools['gs_delete_class']

    def new_gs_delete_method(self):
        return self.registered_mcp_tools['gs_delete_method']

    def new_gs_set_method_category(self):
        return self.registered_mcp_tools['gs_set_method_category']

    def new_gs_list_test_case_classes(self):
        return self.registered_mcp_tools['gs_list_test_case_classes']

    def new_gs_run_tests_in_package(self):
        return self.registered_mcp_tools['gs_run_tests_in_package']

    def new_gs_run_test_method(self):
        return self.registered_mcp_tools['gs_run_test_method']

    def new_gs_preview_selector_rename(self):
        return self.registered_mcp_tools['gs_preview_selector_rename']

    def new_gs_apply_selector_rename(self):
        return self.registered_mcp_tools['gs_apply_selector_rename']

    def new_gs_global_set(self):
        return self.registered_mcp_tools['gs_global_set']

    def new_gs_global_remove(self):
        return self.registered_mcp_tools['gs_global_remove']

    def new_gs_global_exists(self):
        return self.registered_mcp_tools['gs_global_exists']

    def new_gs_run_gemstone_tests(self):
        return self.registered_mcp_tools['gs_run_gemstone_tests']

    def new_gs_debug_eval(self):
        return self.registered_mcp_tools['gs_debug_eval']

    def new_gs_debug_stack(self):
        return self.registered_mcp_tools['gs_debug_stack']

    def new_gs_debug_continue(self):
        return self.registered_mcp_tools['gs_debug_continue']

    def new_gs_debug_step_over(self):
        return self.registered_mcp_tools['gs_debug_step_over']

    def new_gs_debug_step_into(self):
        return self.registered_mcp_tools['gs_debug_step_into']

    def new_gs_debug_step_through(self):
        return self.registered_mcp_tools['gs_debug_step_through']

    def new_gs_debug_stop(self):
        return self.registered_mcp_tools['gs_debug_stop']

    def evaluate_python_value(self, source):
        eval_result = self.gs_eval(
            self.connection_id,
            source,
            unsafe=True,
            reason='test-helper',
        )
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

    def new_halt_exception(self):
        try:
            self.gemstone_session.execute('true ifTrue: [ 0 halt. 1+1. 122+1 ]')
        except GemstoneError as error:
            return error
        raise AssertionError('AI: Expected a GemstoneError raised from halt.')


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_connect_returns_session_summary(live_connection):
    session_summary = live_connection.connect_result['session']
    assert live_connection.connect_result['connection_mode'] == 'linked'
    assert session_summary['user_name'] == 'DataCurator'
    assert 'gs64stone' in session_summary['stone_name']
    assert session_summary['session_id'] > 0


@with_fixtures(RunningStoneFixture)
def test_live_linked_session_lifecycle_does_not_emit_unexpected_stdout(
    running_stone,
):
    assert running_stone.is_stone_running()
    command_result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                "from reahl.swordfish.gemstone import close_session; "
                "from reahl.swordfish.gemstone import create_linked_session; "
                "session = create_linked_session("
                "'DataCurator', 'swordfish', 'gs64stone'"
                "); "
                "close_session(session); "
                "print('completed')"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert command_result.returncode == 0, command_result.stderr
    assert command_result.stdout.strip() == 'completed'


@with_fixtures(LiveMcpConnectionFixture, LiveEvalScenarios)
def test_live_gs_eval_reports_expected_result_shape(live_connection, live_eval):
    eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        live_eval.source,
        unsafe=True,
        reason='integration-test',
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
def test_live_gs_eval_error_includes_serialized_debug_stack(live_connection):
    eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        'true ifTrue: [ 0 halt. 1+1. 122+1 ]',
        unsafe=True,
        reason='integration-test',
    )
    assert not eval_result['ok']
    assert eval_result['debug']['stack_frames']
    top_frame = eval_result['debug']['stack_frames'][0]
    assert top_frame['level'] == 1
    assert top_frame['class_name']
    assert top_frame['method_name']
    assert top_frame['method_source']
    assert top_frame['step_point_offset'] > 0


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_eval_requires_unsafe_flag(live_connection):
    eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        '3 + 4',
    )
    assert not eval_result['ok']
    assert eval_result['error']['message'] == (
        'gs_eval requires unsafe=True. '
        'Prefer explicit gs_* tools when possible.'
    )


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_debug_eval_returns_debug_session_for_halt(live_connection):
    debug_eval_result = live_connection.gs_debug_eval(
        live_connection.connection_id,
        'true ifTrue: [ 0 halt. 1+1. 122+1 ]',
    )
    assert debug_eval_result['ok'], debug_eval_result
    assert not debug_eval_result['completed']
    assert debug_eval_result['debug_id']
    assert debug_eval_result['debug']['stack_frames']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_debug_stack_returns_stack_for_existing_debug_session(
    live_connection,
):
    debug_eval_result = live_connection.gs_debug_eval(
        live_connection.connection_id,
        'true ifTrue: [ 0 halt. 1+1. 122+1 ]',
    )
    assert debug_eval_result['ok'], debug_eval_result
    debug_id = debug_eval_result['debug_id']
    stack_result = live_connection.gs_debug_stack(
        live_connection.connection_id,
        debug_id,
    )
    assert stack_result['ok'], stack_result
    assert not stack_result['completed']
    assert stack_result['debug']['stack_frames']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_debug_step_over_then_continue_completes_debug_session(
    live_connection,
):
    debug_eval_result = live_connection.gs_debug_eval(
        live_connection.connection_id,
        'true ifTrue: [ 0 halt. 1+1. 122+1 ]',
    )
    assert debug_eval_result['ok'], debug_eval_result
    debug_id = debug_eval_result['debug_id']
    step_result = live_connection.gs_debug_step_over(
        live_connection.connection_id,
        debug_id,
        1,
    )
    assert step_result['ok'], step_result
    assert not step_result['completed']
    continue_result = live_connection.gs_debug_continue(
        live_connection.connection_id,
        debug_id,
    )
    assert continue_result['ok'], continue_result
    assert continue_result['completed']
    assert continue_result['output']['result']['python_value'] == 123
    stack_after_continue = live_connection.gs_debug_stack(
        live_connection.connection_id,
        debug_id,
    )
    assert not stack_after_continue['ok']
    assert stack_after_continue['error']['message'] == 'Unknown debug_id.'


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_debug_stop_clears_debug_session(live_connection):
    debug_eval_result = live_connection.gs_debug_eval(
        live_connection.connection_id,
        'true ifTrue: [ 0 halt. 1+1. 122+1 ]',
    )
    assert debug_eval_result['ok'], debug_eval_result
    debug_id = debug_eval_result['debug_id']
    stop_result = live_connection.gs_debug_stop(
        live_connection.connection_id,
        debug_id,
    )
    assert stop_result['ok'], stop_result
    assert stop_result['stopped']
    stack_after_stop = live_connection.gs_debug_stack(
        live_connection.connection_id,
        debug_id,
    )
    assert not stack_after_stop['ok']
    assert stack_after_stop['error']['message'] == 'Unknown debug_id.'


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_list_packages_returns_non_empty_result(live_connection):
    package_result = live_connection.gs_list_packages(live_connection.connection_id)
    assert package_result['ok'], package_result
    assert package_result['packages']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_compile_method_returns_ok(live_connection):
    class_name = 'McpCompileClass%s' % uuid.uuid4().hex[:8]
    selector = 'mcpCompile%s' % uuid.uuid4().hex[:8]
    source = '%s ^123' % selector
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
        superclass_name='Object',
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        source,
        True,
    )
    assert compile_result['ok'], compile_result
    source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        selector,
        True,
    )
    assert source_result['ok'], source_result
    assert selector in source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_get_class_definition_reports_expected_values(live_connection):
    class_name = 'McpDefinitionClass%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
        superclass_name='Object',
        inst_var_names=['exampleInstVar'],
        class_var_names=['ExampleClassVar'],
        class_inst_var_names=['exampleClassInstVar'],
    )
    assert create_class_result['ok'], create_class_result
    definition_result = live_connection.gs_get_class_definition(
        live_connection.connection_id,
        class_name,
    )
    assert definition_result['ok'], definition_result
    definition = definition_result['class_definition']
    assert definition['class_name'] == class_name
    assert definition['superclass_name'] == 'Object'
    assert definition['inst_var_names'] == ['exampleInstVar']
    assert definition['class_var_names'] == ['ExampleClassVar']
    assert definition['class_inst_var_names'] == ['exampleClassInstVar']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_delete_method_removes_selector(live_connection):
    class_name = 'McpDeleteMethodClass%s' % uuid.uuid4().hex[:8]
    selector = 'deleteSelector%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^123' % selector,
        True,
    )
    assert compile_result['ok'], compile_result
    delete_result = live_connection.gs_delete_method(
        live_connection.connection_id,
        class_name,
        selector,
        True,
    )
    assert delete_result['ok'], delete_result
    methods_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        'all',
        True,
    )
    assert methods_result['ok'], methods_result
    assert selector not in methods_result['selectors']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_set_method_category_moves_selector(live_connection):
    class_name = 'McpMethodCategoryClass%s' % uuid.uuid4().hex[:8]
    selector = 'moveSelector%s' % uuid.uuid4().hex[:8]
    target_category = 'examples'
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^321' % selector,
        True,
    )
    assert compile_result['ok'], compile_result
    move_result = live_connection.gs_set_method_category(
        live_connection.connection_id,
        class_name,
        selector,
        target_category,
        True,
    )
    assert move_result['ok'], move_result
    methods_in_target_category = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        target_category,
        True,
    )
    assert methods_in_target_category['ok'], methods_in_target_category
    assert selector in methods_in_target_category['selectors']
    methods_in_default_category = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        'as yet unclassified',
        True,
    )
    assert methods_in_default_category['ok'], methods_in_default_category
    assert selector not in methods_in_default_category['selectors']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_delete_class_removes_global_binding(live_connection):
    class_name = 'McpDeleteClass%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    delete_result = live_connection.gs_delete_class(
        live_connection.connection_id,
        class_name,
    )
    assert delete_result['ok'], delete_result
    assert not live_connection.evaluate_python_value(
        "UserGlobals includesKey: #'%s'" % class_name
    )


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_list_test_case_classes_includes_created_class(live_connection):
    class_name = 'McpPackageTestCase%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    class_result = live_connection.gs_list_test_case_classes(
        live_connection.connection_id,
    )
    assert class_result['ok'], class_result
    assert class_name in class_result['test_case_classes']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_run_tests_in_package_aggregates_results(live_connection):
    class_name = 'McpPackageRunTestCase%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'testPass ^self assert: true',
        True,
    )
    assert compile_result['ok'], compile_result
    definition_result = live_connection.gs_get_class_definition(
        live_connection.connection_id,
        class_name,
    )
    assert definition_result['ok'], definition_result
    package_name = definition_result['class_definition']['package_name']
    run_result = live_connection.gs_run_tests_in_package(
        live_connection.connection_id,
        package_name,
    )
    assert run_result['ok'], run_result
    assert class_name in run_result['result']['test_case_classes']
    assert run_result['result']['run_count'] >= 1


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_run_test_method_runs_only_selected_test(live_connection):
    class_name = 'McpSingleMethodRunTestCase%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    pass_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'testPass ^self assert: true',
        True,
    )
    assert pass_compile_result['ok'], pass_compile_result
    fail_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'testFail ^self assert: false',
        True,
    )
    assert fail_compile_result['ok'], fail_compile_result
    run_result = live_connection.gs_run_test_method(
        live_connection.connection_id,
        class_name,
        'testPass',
    )
    assert run_result['ok'], run_result
    assert run_result['test_method_selector'] == 'testPass'
    assert run_result['tests_passed']
    assert run_result['result']['run_count'] == 1
    assert run_result['result']['failure_count'] == 0
    assert run_result['result']['error_count'] == 0


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_global_set_exists_and_remove_manage_binding(live_connection):
    symbol_name = 'MCP_GLOBAL_%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    set_result = live_connection.gs_global_set(
        live_connection.connection_id,
        symbol_name,
        777,
    )
    assert set_result['ok'], set_result
    exists_after_set_result = live_connection.gs_global_exists(
        live_connection.connection_id,
        symbol_name,
    )
    assert exists_after_set_result['ok'], exists_after_set_result
    assert exists_after_set_result['exists']
    remove_result = live_connection.gs_global_remove(
        live_connection.connection_id,
        symbol_name,
    )
    assert remove_result['ok'], remove_result
    exists_after_remove_result = live_connection.gs_global_exists(
        live_connection.connection_id,
        symbol_name,
    )
    assert exists_after_remove_result['ok'], exists_after_remove_result
    assert not exists_after_remove_result['exists']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_preview_selector_rename_reports_changes(live_connection):
    class_name = 'McpRenamePreviewClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldSelector%s' % uuid.uuid4().hex[:8]
    new_selector = 'newSelector%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsOld%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    implementor_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^123' % old_selector,
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s' % (sender_selector, old_selector),
        True,
    )
    assert sender_compile_result['ok'], sender_compile_result
    preview_result = live_connection.gs_preview_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert preview_result['ok'], preview_result
    assert preview_result['preview']['implementor_count'] >= 1
    assert preview_result['preview']['sender_count'] >= 1
    assert preview_result['preview']['total_changes'] >= 2


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_selector_rename_updates_methods(live_connection):
    class_name = 'McpRenameApplyClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldSelector%s' % uuid.uuid4().hex[:8]
    new_selector = 'newSelector%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsOld%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    implementor_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^123' % old_selector,
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s' % (sender_selector, old_selector),
        True,
    )
    assert sender_compile_result['ok'], sender_compile_result
    apply_result = live_connection.gs_apply_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert apply_result['ok'], apply_result
    selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        'all',
        True,
    )
    assert selectors_result['ok'], selectors_result
    assert old_selector not in selectors_result['selectors']
    assert new_selector in selectors_result['selectors']
    sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        sender_selector,
        True,
    )
    assert sender_source_result['ok'], sender_source_result
    assert old_selector not in sender_source_result['source']
    assert new_selector in sender_source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_run_gemstone_tests_reports_passing_suite(live_connection):
    class_name = 'McpPassingTestCase%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'testPass ^self assert: true',
        True,
    )
    assert compile_result['ok'], compile_result
    run_result = live_connection.gs_run_gemstone_tests(
        live_connection.connection_id,
        class_name,
    )
    assert run_result['ok'], run_result
    assert run_result['tests_passed']
    assert run_result['result']['run_count'] == 1
    assert run_result['result']['failure_count'] == 0
    assert run_result['result']['error_count'] == 0


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_run_gemstone_tests_reports_failing_suite(live_connection):
    class_name = 'McpFailingTestCase%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'testFail ^self assert: false',
        True,
    )
    assert compile_result['ok'], compile_result
    run_result = live_connection.gs_run_gemstone_tests(
        live_connection.connection_id,
        class_name,
    )
    assert run_result['ok'], run_result
    assert not run_result['tests_passed']
    assert run_result['result']['run_count'] == 1
    assert run_result['result']['failure_count'] == 1
    assert run_result['result']['error_count'] == 0
    assert run_result['result']['failures']
    assert class_name in run_result['result']['failures'][0]


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


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_compile_method_adds_selector_in_current_transaction(
    browser_fixture,
):
    class_name = 'BrowserCompileClass%s' % uuid.uuid4().hex[:8]
    selector = 'browserCompile%s' % uuid.uuid4().hex[:8]
    source = '%s ^987' % selector
    browser_fixture.browser_session.create_class(
        class_name=class_name,
        superclass_name='Object',
    )
    browser_fixture.browser_session.compile_method(class_name, True, source)
    method_source = browser_fixture.browser_session.get_method_source(
        class_name,
        selector,
        True,
    )
    assert selector in method_source


@with_fixtures(LiveBrowserSessionFixture)
def test_live_browser_evaluate_source_returns_rendered_payload(browser_fixture):
    output = browser_fixture.browser_session.evaluate_source('3 + 4')
    assert output['result']['class_name'] == 'SmallInteger'
    assert output['result']['python_value'] == 7


@with_fixtures(LiveBrowserSessionFixture)
def test_live_debug_session_has_stack_frames_when_halted(browser_fixture):
    debug_session = GemstoneDebugSession(browser_fixture.halt_exception)
    stack_frames = debug_session.call_stack()
    assert stack_frames
    first_frame = stack_frames[1]
    assert first_frame.level == 1
    assert first_frame.class_name
    assert first_frame.method_name
    assert first_frame.method_source


@with_fixtures(LiveBrowserSessionFixture)
def test_live_debug_session_step_over_then_continue_returns_result(browser_fixture):
    debug_session = GemstoneDebugSession(browser_fixture.halt_exception)
    step_outcome = debug_session.step_over(1)
    assert not step_outcome.has_completed
    continue_outcome = debug_session.continue_running()
    assert continue_outcome.has_completed
    assert continue_outcome.result.to_py == 123
