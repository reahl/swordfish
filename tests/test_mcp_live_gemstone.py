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
            allow_commit=True,
            allow_tracing=True,
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

    def new_gs_transaction_status(self):
        return self.registered_mcp_tools['gs_transaction_status']

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']

    def new_gs_guidance(self):
        return self.registered_mcp_tools['gs_guidance']

    def new_gs_begin_if_needed(self):
        return self.registered_mcp_tools['gs_begin_if_needed']

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

    def new_gs_method_sends(self):
        return self.registered_mcp_tools['gs_method_sends']

    def new_gs_method_ast(self):
        return self.registered_mcp_tools['gs_method_ast']

    def new_gs_method_structure_summary(self):
        return self.registered_mcp_tools['gs_method_structure_summary']

    def new_gs_find_classes(self):
        return self.registered_mcp_tools['gs_find_classes']

    def new_gs_find_selectors(self):
        return self.registered_mcp_tools['gs_find_selectors']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def new_gs_find_senders(self):
        return self.registered_mcp_tools['gs_find_senders']

    def new_gs_tracer_status(self):
        return self.registered_mcp_tools['gs_tracer_status']

    def new_gs_tracer_install(self):
        return self.registered_mcp_tools['gs_tracer_install']

    def new_gs_tracer_enable(self):
        return self.registered_mcp_tools['gs_tracer_enable']

    def new_gs_tracer_disable(self):
        return self.registered_mcp_tools['gs_tracer_disable']

    def new_gs_tracer_uninstall(self):
        return self.registered_mcp_tools['gs_tracer_uninstall']

    def new_gs_tracer_trace_selector(self):
        return self.registered_mcp_tools['gs_tracer_trace_selector']

    def new_gs_tracer_untrace_selector(self):
        return self.registered_mcp_tools['gs_tracer_untrace_selector']

    def new_gs_tracer_clear_observed_senders(self):
        return self.registered_mcp_tools['gs_tracer_clear_observed_senders']

    def new_gs_tracer_find_observed_senders(self):
        return self.registered_mcp_tools['gs_tracer_find_observed_senders']

    def new_gs_plan_evidence_tests(self):
        return self.registered_mcp_tools['gs_plan_evidence_tests']

    def new_gs_collect_sender_evidence(self):
        return self.registered_mcp_tools['gs_collect_sender_evidence']

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

    def new_gs_preview_rename_method(self):
        return self.registered_mcp_tools['gs_preview_rename_method']

    def new_gs_apply_rename_method(self):
        return self.registered_mcp_tools['gs_apply_rename_method']

    def new_gs_preview_move_method(self):
        return self.registered_mcp_tools['gs_preview_move_method']

    def new_gs_apply_move_method(self):
        return self.registered_mcp_tools['gs_apply_move_method']

    def new_gs_preview_add_parameter(self):
        return self.registered_mcp_tools['gs_preview_add_parameter']

    def new_gs_apply_add_parameter(self):
        return self.registered_mcp_tools['gs_apply_add_parameter']

    def new_gs_preview_remove_parameter(self):
        return self.registered_mcp_tools['gs_preview_remove_parameter']

    def new_gs_apply_remove_parameter(self):
        return self.registered_mcp_tools['gs_apply_remove_parameter']

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
class LiveMcpConnectionWithoutCommitPermissionFixture(Fixture):
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
            allow_commit=False,
            allow_tracing=True,
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

    def new_gs_begin_if_needed(self):
        return self.registered_mcp_tools['gs_begin_if_needed']

    def new_gs_transaction_status(self):
        return self.registered_mcp_tools['gs_transaction_status']

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']

    def new_gs_commit(self):
        return self.registered_mcp_tools['gs_commit']

    def new_gs_abort(self):
        return self.registered_mcp_tools['gs_abort']


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


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_transaction_status_tracks_state(live_connection):
    initial_status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert initial_status_result['ok'], initial_status_result
    assert not initial_status_result['transaction_active']
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    active_status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert active_status_result['ok'], active_status_result
    assert active_status_result['transaction_active']
    commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert commit_result['ok'], commit_result
    committed_status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert committed_status_result['ok'], committed_status_result
    assert not committed_status_result['transaction_active']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_begin_if_needed_is_idempotent(live_connection):
    first_begin_result = live_connection.gs_begin_if_needed(
        live_connection.connection_id
    )
    assert first_begin_result['ok'], first_begin_result
    assert first_begin_result['began_transaction']
    second_begin_result = live_connection.gs_begin_if_needed(
        live_connection.connection_id
    )
    assert second_begin_result['ok'], second_begin_result
    assert not second_begin_result['began_transaction']
    assert second_begin_result['transaction_active']
    commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert commit_result['ok'], commit_result


@with_fixtures(LiveMcpConnectionWithoutCommitPermissionFixture)
def test_live_workflow_without_commit_permission_requires_abort(
    live_connection,
):
    capabilities_result = live_connection.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    assert not capabilities_result['policy']['allow_commit']
    begin_result = live_connection.gs_begin_if_needed(
        live_connection.connection_id
    )
    assert begin_result['ok'], begin_result
    assert begin_result['transaction_active']
    class_name = 'McpNoCommitWorkflow%s' % uuid.uuid4().hex[:8]
    create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_result['ok'], create_result
    compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'proofOfWrite ^42',
    )
    assert compile_result['ok'], compile_result
    commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert not commit_result['ok']
    assert commit_result['error']['message'] == (
        'gs_commit is disabled. '
        'Start swordfish-mcp with --allow-commit to enable.'
    )
    active_status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert active_status_result['ok'], active_status_result
    assert active_status_result['transaction_active']
    abort_result = live_connection.gs_abort(live_connection.connection_id)
    assert abort_result['ok'], abort_result
    aborted_status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert aborted_status_result['ok'], aborted_status_result
    assert not aborted_status_result['transaction_active']


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
def test_live_gs_tracer_lifecycle_tracks_manifest_and_hash(live_connection):
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    uninstall_before_install_result = live_connection.gs_tracer_uninstall(
        live_connection.connection_id
    )
    assert uninstall_before_install_result['ok'], uninstall_before_install_result
    status_before_install_result = live_connection.gs_tracer_status(
        live_connection.connection_id
    )
    assert status_before_install_result['ok'], status_before_install_result
    assert not status_before_install_result['tracer_installed']
    install_result = live_connection.gs_tracer_install(
        live_connection.connection_id
    )
    assert install_result['ok'], install_result
    assert install_result['tracer_installed']
    assert install_result['hashes_match']
    assert install_result['versions_match']
    assert install_result['manifest_matches']
    assert not install_result['tracer_enabled']
    enable_result = live_connection.gs_tracer_enable(
        live_connection.connection_id
    )
    assert enable_result['ok'], enable_result
    assert enable_result['tracer_enabled']
    disable_result = live_connection.gs_tracer_disable(
        live_connection.connection_id
    )
    assert disable_result['ok'], disable_result
    assert not disable_result['tracer_enabled']
    uninstall_result = live_connection.gs_tracer_uninstall(
        live_connection.connection_id
    )
    assert uninstall_result['ok'], uninstall_result
    assert not uninstall_result['tracer_installed']
    assert not uninstall_result['manifest_matches']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_tracer_observed_senders_report_runtime_callers(
    live_connection,
):
    class_name = 'McpTraceCallChainTest%s' % uuid.uuid4().hex[:8]
    target_selector = 'traceRuntimeDefault%s:' % uuid.uuid4().hex[:8]
    caller_selector = 'traceRuntimeCaller%s' % uuid.uuid4().hex[:8]
    test_method_selector = 'testTraceRuntimeCaller%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    uninstall_result = live_connection.gs_tracer_uninstall(
        live_connection.connection_id
    )
    assert uninstall_result['ok'], uninstall_result
    install_result = live_connection.gs_tracer_install(
        live_connection.connection_id
    )
    assert install_result['ok'], install_result
    enable_result = live_connection.gs_tracer_enable(
        live_connection.connection_id
    )
    assert enable_result['ok'], enable_result
    create_test_case_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_test_case_result['ok'], create_test_case_result
    target_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s value ^value + 1' % target_selector,
    )
    assert target_compile_result['ok'], target_compile_result
    caller_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s 41' % (caller_selector, target_selector),
    )
    assert caller_compile_result['ok'], caller_compile_result
    test_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    self assert: (self %s) equals: 42'
        )
        % (
            test_method_selector,
            caller_selector,
        ),
    )
    assert test_compile_result['ok'], test_compile_result
    trace_selector_result = live_connection.gs_tracer_trace_selector(
        live_connection.connection_id,
        target_selector,
    )
    assert trace_selector_result['ok'], trace_selector_result
    clear_observed_senders_result = (
        live_connection.gs_tracer_clear_observed_senders(
            live_connection.connection_id
        )
    )
    assert clear_observed_senders_result['ok'], clear_observed_senders_result
    run_test_result = live_connection.gs_run_test_method(
        live_connection.connection_id,
        class_name,
        test_method_selector,
    )
    assert run_test_result['ok'], run_test_result
    assert run_test_result['tests_passed']
    assert run_test_result['result']['run_count'] == 1
    assert run_test_result['result']['failure_count'] == 0
    assert run_test_result['result']['error_count'] == 0
    observed_senders_result = live_connection.gs_tracer_find_observed_senders(
        live_connection.connection_id,
        target_selector,
    )
    assert observed_senders_result['ok'], observed_senders_result
    assert observed_senders_result['total_count'] >= 1
    matching_observed_senders = [
        observed_sender
        for observed_sender in observed_senders_result['observed_senders']
        if observed_sender['caller_class_name'] == class_name
        and observed_sender['caller_show_instance_side']
        and observed_sender['caller_method_selector'] == caller_selector
    ]
    assert matching_observed_senders
    assert matching_observed_senders[0]['observed_count'] >= 1
    count_only_observed_senders_result = (
        live_connection.gs_tracer_find_observed_senders(
            live_connection.connection_id,
            target_selector,
            count_only=True,
        )
    )
    assert count_only_observed_senders_result['ok']
    assert count_only_observed_senders_result['returned_count'] == 0
    assert count_only_observed_senders_result['observed_senders'] == []
    assert count_only_observed_senders_result['total_count'] >= 1
    untrace_selector_result = live_connection.gs_tracer_untrace_selector(
        live_connection.connection_id,
        target_selector,
    )
    assert untrace_selector_result['ok'], untrace_selector_result
    assert untrace_selector_result['restored_sender_count'] >= 1


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_plan_evidence_tests_can_feed_collect_sender_evidence(
    live_connection,
):
    class_name = 'McpEvidencePlanTest%s' % uuid.uuid4().hex[:8]
    target_selector = 'evidenceTarget%s:' % uuid.uuid4().hex[:8]
    caller_selector = 'evidenceCaller%s' % uuid.uuid4().hex[:8]
    test_method_selector = 'testEvidenceCaller%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    uninstall_result = live_connection.gs_tracer_uninstall(
        live_connection.connection_id
    )
    assert uninstall_result['ok'], uninstall_result
    install_result = live_connection.gs_tracer_install(
        live_connection.connection_id
    )
    assert install_result['ok'], install_result
    enable_result = live_connection.gs_tracer_enable(
        live_connection.connection_id
    )
    assert enable_result['ok'], enable_result
    create_test_case_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_test_case_result['ok'], create_test_case_result
    target_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s value ^value + 1' % target_selector,
    )
    assert target_compile_result['ok'], target_compile_result
    caller_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s 41' % (caller_selector, target_selector),
    )
    assert caller_compile_result['ok'], caller_compile_result
    test_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    self assert: (self %s) equals: 42'
        )
        % (
            test_method_selector,
            caller_selector,
        ),
    )
    assert test_compile_result['ok'], test_compile_result
    plan_result = live_connection.gs_plan_evidence_tests(
        live_connection.connection_id,
        target_selector,
        max_depth=2,
        max_nodes=200,
        max_senders_per_selector=200,
        max_test_methods=50,
    )
    assert plan_result['ok'], plan_result
    assert plan_result['test_plan_id']
    assert plan_result['plan']['candidate_test_count'] >= 1
    collect_result = live_connection.gs_collect_sender_evidence(
        live_connection.connection_id,
        target_selector,
        test_plan_id=plan_result['test_plan_id'],
        max_planned_tests=10,
        stop_on_first_observed=True,
        count_only=True,
    )
    assert collect_result['ok'], collect_result
    assert collect_result['planned_test_count'] >= 1
    assert collect_result['observed']['total_count'] >= 1
    assert collect_result['evidence_run_id']
    assert collect_result['test_runs']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_find_implementors_and_senders_support_limits_and_counts(
    live_connection,
):
    class_name = 'McpFindSendersClass%s' % uuid.uuid4().hex[:8]
    target_selector = 'trackedSelector%s:' % uuid.uuid4().hex[:8]
    sender_selector = 'callsTracked%s' % uuid.uuid4().hex[:8]
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
        '%s value ^value' % target_selector,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s 1' % (sender_selector, target_selector),
    )
    assert sender_compile_result['ok'], sender_compile_result
    implementors_result = live_connection.gs_find_implementors(
        live_connection.connection_id,
        target_selector,
    )
    assert implementors_result['ok'], implementors_result
    assert implementors_result['total_count'] >= 1
    assert implementors_result['returned_count'] == len(
        implementors_result['implementors']
    )
    assert implementors_result['elapsed_ms'] >= 0
    assert {
        'class_name': class_name,
        'show_instance_side': True,
    } in implementors_result['implementors']
    limited_implementors_result = live_connection.gs_find_implementors(
        live_connection.connection_id,
        target_selector,
        max_results=1,
    )
    assert limited_implementors_result['ok'], limited_implementors_result
    assert limited_implementors_result['returned_count'] <= 1
    count_only_implementors_result = live_connection.gs_find_implementors(
        live_connection.connection_id,
        target_selector,
        count_only=True,
    )
    assert count_only_implementors_result['ok'], count_only_implementors_result
    assert count_only_implementors_result['returned_count'] == 0
    assert count_only_implementors_result['implementors'] == []
    senders_result = live_connection.gs_find_senders(
        live_connection.connection_id,
        target_selector,
    )
    assert senders_result['ok'], senders_result
    assert senders_result['total_count'] >= 1
    assert senders_result['returned_count'] == len(senders_result['senders'])
    assert senders_result['elapsed_ms'] >= 0
    assert {
        'class_name': class_name,
        'show_instance_side': True,
        'method_selector': sender_selector,
    } in senders_result['senders']
    limited_senders_result = live_connection.gs_find_senders(
        live_connection.connection_id,
        target_selector,
        max_results=1,
    )
    assert limited_senders_result['ok'], limited_senders_result
    assert limited_senders_result['returned_count'] <= 1
    count_only_senders_result = live_connection.gs_find_senders(
        live_connection.connection_id,
        target_selector,
        count_only=True,
    )
    assert count_only_senders_result['ok'], count_only_senders_result
    assert count_only_senders_result['returned_count'] == 0
    assert count_only_senders_result['senders'] == []


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_method_sends_reports_keyword_and_explicit_unary_sends(
    live_connection,
):
    """AI: Method send analysis should report both keyword sends and explicit self unary sends."""
    class_name = 'McpMethodSendsClass%s' % uuid.uuid4().hex[:8]
    analyzed_selector = 'analyzeMethod%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_default_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'default ^41',
    )
    assert compile_default_result['ok'], compile_default_result
    compile_keyword_target_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'oldSelector: value with: other ^value + other',
    )
    assert compile_keyword_target_result['ok'], compile_keyword_target_result
    compile_analyzed_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    | value |\n'
            '    value := self default.\n'
            '    self oldSelector: value with: 1.\n'
            '    ^value'
        )
        % analyzed_selector,
    )
    assert compile_analyzed_result['ok'], compile_analyzed_result
    sends_result = live_connection.gs_method_sends(
        live_connection.connection_id,
        class_name,
        analyzed_selector,
        True,
    )
    assert sends_result['ok'], sends_result
    assert sends_result['total_count'] >= 2
    selectors = [send_entry['selector'] for send_entry in sends_result['sends']]
    assert 'oldSelector:with:' in selectors
    assert 'default' in selectors


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_method_sends_reports_binary_and_cascade_unary_sends(
    live_connection,
):
    """AI: Send analysis should include common expression binary sends and implicit cascade unary sends."""
    class_name = 'McpMethodSendShapes%s' % uuid.uuid4().hex[:8]
    analyzed_selector = 'sendShapeMethod%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_default_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'default ^9',
    )
    assert compile_default_result['ok'], compile_default_result
    compile_analyzed_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    | total |\n'
            '    total := 1 + 2.\n'
            '    ^self\n'
            '        yourself;\n'
            '        default'
        )
        % analyzed_selector,
    )
    assert compile_analyzed_result['ok'], compile_analyzed_result
    sends_result = live_connection.gs_method_sends(
        live_connection.connection_id,
        class_name,
        analyzed_selector,
        True,
    )
    assert sends_result['ok'], sends_result
    plus_entries = [
        send_entry
        for send_entry in sends_result['sends']
        if send_entry['selector'] == '+'
    ]
    assert plus_entries
    default_entries = [
        send_entry
        for send_entry in sends_result['sends']
        if send_entry['selector'] == 'default'
    ]
    assert default_entries
    cascade_default_entries = [
        send_entry
        for send_entry in default_entries
        if send_entry['receiver_hint'] == 'cascade'
    ]
    assert cascade_default_entries


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_method_structure_summary_reports_basic_structure_counts(
    live_connection,
):
    """AI: Method structure summary should expose assignment, send, and block/cascade counts for navigation heuristics."""
    class_name = 'McpMethodSummaryClass%s' % uuid.uuid4().hex[:8]
    analyzed_selector = 'summarizeMethod%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_default_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'default ^5',
    )
    assert compile_default_result['ok'], compile_default_result
    compile_analyzed_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    | value |\n'
            '    value := self default.\n'
            '    value > 0 ifTrue: [ value := value + 1 ].\n'
            '    ^self\n'
            '        yourself;\n'
            '        default'
        )
        % analyzed_selector,
    )
    assert compile_analyzed_result['ok'], compile_analyzed_result
    summary_result = live_connection.gs_method_structure_summary(
        live_connection.connection_id,
        class_name,
        analyzed_selector,
        True,
    )
    assert summary_result['ok'], summary_result
    summary = summary_result['summary']
    assert summary['assignment_count'] >= 1
    assert summary['send_count'] >= 2
    assert summary['keyword_send_count'] >= 1
    assert summary['unary_send_count'] >= 1
    assert summary['block_open_count'] == 1
    assert summary['block_close_count'] == 1
    assert summary['cascade_count'] == 1


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_method_ast_reports_temporaries_statements_and_sends(
    live_connection,
):
    """AI: Method AST should expose temporaries, statement nodes, and detected sends for AI navigation."""
    class_name = 'McpMethodAstClass%s' % uuid.uuid4().hex[:8]
    analyzed_selector = 'astMethod%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_default_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'default ^10',
    )
    assert compile_default_result['ok'], compile_default_result
    compile_analyzed_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    | value total |\n'
            '    value := self default.\n'
            '    total := value + 1.\n'
            '    ^total'
        )
        % analyzed_selector,
    )
    assert compile_analyzed_result['ok'], compile_analyzed_result
    ast_result = live_connection.gs_method_ast(
        live_connection.connection_id,
        class_name,
        analyzed_selector,
        True,
    )
    assert ast_result['ok'], ast_result
    ast_payload = ast_result['ast']
    assert ast_payload['schema_version'] == 1
    assert ast_payload['node_type'] == 'method'
    assert ast_payload['selector'] == analyzed_selector
    assert ast_payload['temporaries'] == ['value', 'total']
    assert ast_payload['statement_count'] == len(ast_payload['statements'])
    assert ast_payload['statement_count'] >= 3
    statement_kinds = [
        statement['statement_kind']
        for statement in ast_payload['statements']
    ]
    assert 'assignment' in statement_kinds
    assert 'return' in statement_kinds
    selectors = [send_entry['selector'] for send_entry in ast_payload['sends']]
    assert 'default' in selectors


@with_fixtures(LiveMcpConnectionFixture)
def test_live_write_tools_require_gs_begin(live_connection):
    class_name = 'McpWriteWithoutBegin%s' % uuid.uuid4().hex[:8]
    create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


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
def test_live_gs_compile_method_accepts_false_string_for_class_side(
    live_connection,
):
    class_name = 'McpCompileClassSide%s' % uuid.uuid4().hex[:8]
    selector = 'mcpClassSide%s' % uuid.uuid4().hex[:8]
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
        'false',
    )
    assert compile_result['ok'], compile_result
    assert compile_result['show_instance_side'] is False
    class_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        selector,
        'false',
    )
    assert class_source_result['ok'], class_source_result
    assert selector in class_source_result['source']


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
def test_live_gs_preview_rename_method_reports_same_class_side_scope(
    live_connection,
):
    class_name = 'McpMethodRenamePreview%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldMethod%s' % uuid.uuid4().hex[:8]
    new_selector = 'newMethod%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsOldMethod%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_implementor_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^11' % old_selector,
        True,
    )
    assert compile_implementor_result['ok'], compile_implementor_result
    compile_sender_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s' % (sender_selector, old_selector),
        True,
    )
    assert compile_sender_result['ok'], compile_sender_result
    preview_result = live_connection.gs_preview_rename_method(
        live_connection.connection_id,
        class_name,
        old_selector,
        new_selector,
        True,
    )
    assert preview_result['ok'], preview_result
    preview = preview_result['preview']
    assert preview['class_name'] == class_name
    assert preview['show_instance_side'] is True
    assert preview['sender_scope'] == 'same_class_side_only'
    assert preview['implementor_count'] >= 1
    assert preview['sender_count'] >= 1
    assert preview['total_changes'] >= 2
    assert all(
        change['class_name'] == class_name
        and change['show_instance_side']
        for change in preview['changes']
    )


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_rename_method_updates_target_class_only(
    live_connection,
):
    target_class_name = 'McpMethodRenameTarget%s' % uuid.uuid4().hex[:8]
    other_class_name = 'McpMethodRenameOther%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldMethod%s' % uuid.uuid4().hex[:8]
    new_selector = 'newMethod%s' % uuid.uuid4().hex[:8]
    target_sender_selector = 'targetCallsOld%s' % uuid.uuid4().hex[:8]
    other_sender_selector = 'otherCallsOld%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    target_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        target_class_name,
    )
    assert target_create_result['ok'], target_create_result
    other_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        other_class_name,
    )
    assert other_create_result['ok'], other_create_result
    target_implementor_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        target_class_name,
        '%s ^101' % old_selector,
        True,
    )
    assert target_implementor_result['ok'], target_implementor_result
    other_implementor_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        other_class_name,
        '%s ^202' % old_selector,
        True,
    )
    assert other_implementor_result['ok'], other_implementor_result
    target_sender_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        target_class_name,
        '%s ^self %s' % (target_sender_selector, old_selector),
        True,
    )
    assert target_sender_result['ok'], target_sender_result
    other_sender_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        other_class_name,
        '%s ^self %s' % (other_sender_selector, old_selector),
        True,
    )
    assert other_sender_result['ok'], other_sender_result
    apply_result = live_connection.gs_apply_rename_method(
        live_connection.connection_id,
        target_class_name,
        old_selector,
        new_selector,
        True,
    )
    assert apply_result['ok'], apply_result
    target_selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        target_class_name,
        'all',
        True,
    )
    assert target_selectors_result['ok'], target_selectors_result
    assert old_selector not in target_selectors_result['selectors']
    assert new_selector in target_selectors_result['selectors']
    other_selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        other_class_name,
        'all',
        True,
    )
    assert other_selectors_result['ok'], other_selectors_result
    assert old_selector in other_selectors_result['selectors']
    assert new_selector not in other_selectors_result['selectors']
    target_sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        target_class_name,
        target_sender_selector,
        True,
    )
    assert target_sender_source_result['ok'], target_sender_source_result
    assert old_selector not in target_sender_source_result['source']
    assert new_selector in target_sender_source_result['source']
    other_sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        other_class_name,
        other_sender_selector,
        True,
    )
    assert other_sender_source_result['ok'], other_sender_source_result
    assert old_selector in other_sender_source_result['source']
    assert new_selector not in other_sender_source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_preview_move_method_reports_sender_risk(
    live_connection,
):
    source_class_name = 'McpMovePreviewSource%s' % uuid.uuid4().hex[:8]
    target_class_name = 'McpMovePreviewTarget%s' % uuid.uuid4().hex[:8]
    method_selector = 'moveMe%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsMoveMe%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    source_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        source_class_name,
    )
    assert source_create_result['ok'], source_create_result
    target_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        target_class_name,
    )
    assert target_create_result['ok'], target_create_result
    implementor_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        source_class_name,
        '%s ^77' % method_selector,
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        source_class_name,
        '%s ^self %s' % (sender_selector, method_selector),
        True,
    )
    assert sender_compile_result['ok'], sender_compile_result
    preview_result = live_connection.gs_preview_move_method(
        live_connection.connection_id,
        source_class_name,
        method_selector,
        target_class_name,
        True,
        True,
    )
    assert preview_result['ok'], preview_result
    preview = preview_result['preview']
    assert preview['source_class_name'] == source_class_name
    assert preview['target_class_name'] == target_class_name
    assert preview['method_selector'] == method_selector
    assert not preview['target_has_method']
    assert preview['source_sender_count'] >= 1
    assert preview['total_sender_count'] >= 1
    assert preview['warnings']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_move_method_moves_selector_between_classes(
    live_connection,
):
    source_class_name = 'McpMoveApplySource%s' % uuid.uuid4().hex[:8]
    target_class_name = 'McpMoveApplyTarget%s' % uuid.uuid4().hex[:8]
    method_selector = 'moveMe%s' % uuid.uuid4().hex[:8]
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    source_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        source_class_name,
    )
    assert source_create_result['ok'], source_create_result
    target_create_result = live_connection.gs_create_class(
        live_connection.connection_id,
        target_class_name,
    )
    assert target_create_result['ok'], target_create_result
    source_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        source_class_name,
        '%s ^88' % method_selector,
        True,
    )
    assert source_compile_result['ok'], source_compile_result
    apply_result = live_connection.gs_apply_move_method(
        live_connection.connection_id,
        source_class_name,
        method_selector,
        target_class_name,
        True,
        True,
        False,
        True,
    )
    assert apply_result['ok'], apply_result
    assert apply_result['result']['source_deleted']
    source_selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        source_class_name,
        'all',
        True,
    )
    assert source_selectors_result['ok'], source_selectors_result
    assert method_selector not in source_selectors_result['selectors']
    target_selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        target_class_name,
        'all',
        True,
    )
    assert target_selectors_result['ok'], target_selectors_result
    assert method_selector in target_selectors_result['selectors']
    moved_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        target_class_name,
        method_selector,
        True,
    )
    assert moved_source_result['ok'], moved_source_result
    assert '^88' in moved_source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_preview_add_parameter_reports_compatibility_wrapper(
    live_connection,
):
    class_name = 'McpAddParamPreview%s' % uuid.uuid4().hex[:8]
    method_selector = 'oldSelector:with:'
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
        'oldSelector: a with: b ^a + b',
        True,
    )
    assert compile_result['ok'], compile_result
    preview_result = live_connection.gs_preview_add_parameter(
        live_connection.connection_id,
        class_name,
        method_selector,
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert preview_result['ok'], preview_result
    preview = preview_result['preview']
    assert preview['old_selector'] == method_selector
    assert preview['new_selector'] == 'oldSelector:with:timeout:'
    assert preview['parameter_keyword'] == 'timeout:'
    assert preview['parameter_name'] == 'timeout'
    assert preview['compatibility_wrapper']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_add_parameter_keeps_old_selector_via_wrapper(
    live_connection,
):
    class_name = 'McpAddParamApply%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsOld%s' % uuid.uuid4().hex[:8]
    method_selector = 'oldSelector:with:'
    new_selector = 'oldSelector:with:timeout:'
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_implementor_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'oldSelector: a with: b ^a + b',
        True,
    )
    assert compile_implementor_result['ok'], compile_implementor_result
    compile_sender_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self oldSelector: 1 with: 2' % sender_selector,
        True,
    )
    assert compile_sender_result['ok'], compile_sender_result
    apply_result = live_connection.gs_apply_add_parameter(
        live_connection.connection_id,
        class_name,
        method_selector,
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert apply_result['ok'], apply_result
    selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        'all',
        True,
    )
    assert selectors_result['ok'], selectors_result
    assert method_selector in selectors_result['selectors']
    assert new_selector in selectors_result['selectors']
    sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        sender_selector,
        True,
    )
    assert sender_source_result['ok'], sender_source_result
    assert 'oldSelector: 1 with: 2' in sender_source_result['source']
    new_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        new_selector,
        True,
    )
    assert new_source_result['ok'], new_source_result
    assert 'timeout: timeout' in new_source_result['source']
    old_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        method_selector,
        True,
    )
    assert old_source_result['ok'], old_source_result
    assert 'timeout: 30' in old_source_result['source']
    sender_eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        '%s new %s' % (class_name, sender_selector),
        unsafe=True,
        reason='verify-add-parameter-wrapper',
    )
    assert sender_eval_result['ok'], sender_eval_result
    assert sender_eval_result['output']['result']['python_value'] == 3


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_preview_remove_parameter_reports_compatibility_wrapper(
    live_connection,
):
    class_name = 'McpRemoveParamPreview%s' % uuid.uuid4().hex[:8]
    method_selector = 'oldSelector:with:timeout:'
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
        'oldSelector: a with: b timeout: c ^a + b',
        True,
    )
    assert compile_result['ok'], compile_result
    preview_result = live_connection.gs_preview_remove_parameter(
        live_connection.connection_id,
        class_name,
        method_selector,
        'timeout:',
        True,
    )
    assert preview_result['ok'], preview_result
    preview = preview_result['preview']
    assert preview['old_selector'] == method_selector
    assert preview['new_selector'] == 'oldSelector:with:'
    assert preview['parameter_keyword'] == 'timeout:'
    assert preview['removed_argument_name'] == 'c'
    assert preview['compatibility_wrapper']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_remove_parameter_keeps_old_selector_via_wrapper(
    live_connection,
):
    class_name = 'McpRemoveParamApply%s' % uuid.uuid4().hex[:8]
    sender_selector = 'callsOldWithTimeout%s' % uuid.uuid4().hex[:8]
    method_selector = 'oldSelector:with:timeout:'
    new_selector = 'oldSelector:with:'
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_class_result = live_connection.gs_create_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_class_result['ok'], create_class_result
    compile_implementor_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'oldSelector: a with: b timeout: c ^a + b',
        True,
    )
    assert compile_implementor_result['ok'], compile_implementor_result
    compile_sender_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self oldSelector: 1 with: 2 timeout: 99' % sender_selector,
        True,
    )
    assert compile_sender_result['ok'], compile_sender_result
    apply_result = live_connection.gs_apply_remove_parameter(
        live_connection.connection_id,
        class_name,
        method_selector,
        'timeout:',
        True,
        False,
    )
    assert apply_result['ok'], apply_result
    selectors_result = live_connection.gs_list_methods(
        live_connection.connection_id,
        class_name,
        'all',
        True,
    )
    assert selectors_result['ok'], selectors_result
    assert method_selector in selectors_result['selectors']
    assert new_selector in selectors_result['selectors']
    new_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        new_selector,
        True,
    )
    assert new_source_result['ok'], new_source_result
    assert 'oldSelector: a with: b' in new_source_result['source']
    assert 'timeout:' not in new_source_result['source']
    old_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        method_selector,
        True,
    )
    assert old_source_result['ok'], old_source_result
    assert 'oldSelector: a with: b' in old_source_result['source']
    assert '^self oldSelector: a with: b' in old_source_result['source']
    sender_eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        '%s new %s' % (class_name, sender_selector),
        unsafe=True,
        reason='verify-remove-parameter-wrapper',
    )
    assert sender_eval_result['ok'], sender_eval_result
    assert sender_eval_result['output']['result']['python_value'] == 3
    direct_eval_result = live_connection.gs_eval(
        live_connection.connection_id,
        '%s new oldSelector: 1 with: 2' % class_name,
        unsafe=True,
        reason='verify-remove-parameter-new-selector',
    )
    assert direct_eval_result['ok'], direct_eval_result
    assert direct_eval_result['output']['result']['python_value'] == 3


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_selector_rename_for_keyword_selector(
    live_connection,
):
    class_name = 'McpRenameKeywordClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldSelector:with:'
    new_selector = 'newSelector:with:'
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
        'oldSelector: a with: b ^a + b',
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self oldSelector: 1 with: 2' % sender_selector,
        True,
    )
    assert sender_compile_result['ok'], sender_compile_result
    apply_result = live_connection.gs_apply_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert apply_result['ok'], apply_result
    sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        sender_selector,
        True,
    )
    assert sender_source_result['ok'], sender_source_result
    assert 'newSelector:' in sender_source_result['source']
    assert 'oldSelector:' not in sender_source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_gs_apply_selector_rename_for_multiline_keyword_send_in_cascade(
    live_connection,
):
    class_name = 'McpRenameCascadeClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldSelector:with:'
    new_selector = 'newSelector:and:'
    sender_selector = 'callsOldCascade%s' % uuid.uuid4().hex[:8]
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
        'oldSelector: a with: b ^a + b',
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    sender_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    | value |\n'
            '    value := self\n'
            '        oldSelector: 1\n'
            '        with: 2;\n'
            '        yourself.\n'
            '    ^value'
        )
        % sender_selector,
        True,
    )
    assert sender_compile_result['ok'], sender_compile_result
    apply_result = live_connection.gs_apply_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert apply_result['ok'], apply_result
    sender_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        sender_selector,
        True,
    )
    assert sender_source_result['ok'], sender_source_result
    assert 'newSelector: 1' in sender_source_result['source']
    assert 'and: 2;' in sender_source_result['source']
    assert 'oldSelector:' not in sender_source_result['source']
    assert 'yourself' in sender_source_result['source']


@with_fixtures(LiveMcpConnectionFixture)
def test_live_guided_refactor_workflow_runs_end_to_end(live_connection):
    class_name = 'McpGuidedWorkflowClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldSelector:with:'
    new_selector = 'newSelector:and:'
    caller_selector = 'calculateTotal%s' % uuid.uuid4().hex[:8]
    test_selector = 'testGuidedRename%s' % uuid.uuid4().hex[:8]
    capabilities_result = live_connection.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['allow_compile']
    guidance_result = live_connection.gs_guidance(
        'refactor',
        selector=old_selector,
        change_kind='rename_selector',
    )
    assert guidance_result['ok'], guidance_result
    assert guidance_result['guidance']['intent'] == 'refactor'
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_test_case_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_test_case_result['ok'], create_test_case_result
    implementor_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        'oldSelector: left with: right ^left + right',
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    caller_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self oldSelector: 1 with: 2' % caller_selector,
        True,
    )
    assert caller_compile_result['ok'], caller_compile_result
    test_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    self assert: (self %s) equals: 3'
        )
        % (
            test_selector,
            caller_selector,
        ),
        True,
    )
    assert test_compile_result['ok'], test_compile_result
    preview_result = live_connection.gs_preview_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert preview_result['ok'], preview_result
    assert preview_result['preview']['total_changes'] >= 2
    apply_result = live_connection.gs_apply_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert apply_result['ok'], apply_result
    caller_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        caller_selector,
        True,
    )
    assert caller_source_result['ok'], caller_source_result
    assert 'newSelector: 1 and: 2' in caller_source_result['source']
    run_test_result = live_connection.gs_run_test_method(
        live_connection.connection_id,
        class_name,
        test_selector,
    )
    assert run_test_result['ok'], run_test_result
    assert run_test_result['tests_passed']
    assert run_test_result['result']['run_count'] == 1
    assert run_test_result['result']['failure_count'] == 0
    assert run_test_result['result']['error_count'] == 0


@with_fixtures(LiveMcpConnectionFixture)
def test_live_evidence_guarded_selector_rename_workflow_runs_end_to_end(
    live_connection,
):
    class_name = 'McpEvidenceGuardClass%s' % uuid.uuid4().hex[:8]
    old_selector = 'oldEvidenceSelector%s:' % uuid.uuid4().hex[:8]
    new_selector = 'newEvidenceSelector%s:' % uuid.uuid4().hex[:8]
    caller_selector = 'callsEvidence%s' % uuid.uuid4().hex[:8]
    test_selector = 'testEvidenceGuardedRename%s' % uuid.uuid4().hex[:8]
    capabilities_result = live_connection.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['allow_tracing']
    guidance_result = live_connection.gs_guidance(
        'sender_analysis',
        selector=old_selector,
        change_kind='rename_selector',
    )
    assert guidance_result['ok'], guidance_result
    begin_result = live_connection.gs_begin(live_connection.connection_id)
    assert begin_result['ok'], begin_result
    create_test_case_result = live_connection.gs_create_test_case_class(
        live_connection.connection_id,
        class_name,
    )
    assert create_test_case_result['ok'], create_test_case_result
    implementor_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s value ^value + 1' % old_selector,
        True,
    )
    assert implementor_compile_result['ok'], implementor_compile_result
    caller_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        '%s ^self %s 1' % (caller_selector, old_selector),
        True,
    )
    assert caller_compile_result['ok'], caller_compile_result
    test_compile_result = live_connection.gs_compile_method(
        live_connection.connection_id,
        class_name,
        (
            '%s\n'
            '    self assert: (self %s) equals: 2'
        )
        % (
            test_selector,
            caller_selector,
        ),
        True,
    )
    assert test_compile_result['ok'], test_compile_result
    plan_result = live_connection.gs_plan_evidence_tests(
        live_connection.connection_id,
        old_selector,
        max_depth=2,
        max_nodes=300,
        max_senders_per_selector=300,
        max_test_methods=100,
    )
    assert plan_result['ok'], plan_result
    assert plan_result['test_plan_id']
    collect_result = live_connection.gs_collect_sender_evidence(
        live_connection.connection_id,
        old_selector,
        test_plan_id=plan_result['test_plan_id'],
        max_planned_tests=20,
        stop_on_first_observed=True,
    )
    assert collect_result['ok'], collect_result
    assert collect_result['evidence_run_id']
    assert collect_result['observed']['total_count'] >= 1
    preview_result = live_connection.gs_preview_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
    )
    assert preview_result['ok'], preview_result
    guarded_apply_result = live_connection.gs_apply_selector_rename(
        live_connection.connection_id,
        old_selector,
        new_selector,
        require_observed_sender_evidence=True,
        evidence_run_id=collect_result['evidence_run_id'],
    )
    assert guarded_apply_result['ok'], guarded_apply_result
    caller_source_result = live_connection.gs_get_method_source(
        live_connection.connection_id,
        class_name,
        caller_selector,
        True,
    )
    assert caller_source_result['ok'], caller_source_result
    assert new_selector in caller_source_result['source']
    assert old_selector not in caller_source_result['source']
    run_test_result = live_connection.gs_run_test_method(
        live_connection.connection_id,
        class_name,
        test_selector,
    )
    assert run_test_result['ok'], run_test_result
    assert run_test_result['tests_passed']
    commit_result = live_connection.gs_commit(live_connection.connection_id)
    assert commit_result['ok'], commit_result
    status_result = live_connection.gs_transaction_status(
        live_connection.connection_id
    )
    assert status_result['ok'], status_result
    assert not status_result['transaction_active']


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
def test_live_browser_finds_senders_with_method_selector(browser_fixture):
    class_name = 'BrowserFindSendersClass%s' % uuid.uuid4().hex[:8]
    target_selector = 'targetSelector%s:' % uuid.uuid4().hex[:8]
    sender_selector = 'callsTarget%s' % uuid.uuid4().hex[:8]
    browser_fixture.browser_session.create_class(
        class_name=class_name,
        superclass_name='Object',
    )
    browser_fixture.browser_session.compile_method(
        class_name,
        True,
        '%s value ^value' % target_selector,
    )
    browser_fixture.browser_session.compile_method(
        class_name,
        True,
        '%s ^self %s 1' % (sender_selector, target_selector),
    )
    senders = browser_fixture.browser_session.find_senders(target_selector)
    assert {
        'class_name': class_name,
        'show_instance_side': True,
        'method_selector': sender_selector,
    } in senders['senders']


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
