from reahl.tofu import Fixture
from reahl.tofu import NoException
from reahl.tofu import expected
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import with_fixtures

from reahl.swordfish.mcp.session_registry import add_connection
from reahl.swordfish.mcp.session_registry import clear_connections
from reahl.swordfish.mcp.integration_state import IntegratedSessionState
from reahl.swordfish.mcp.tools import register_tools

class FakeGemstoneValue:
    def __init__(self, value):
        self.to_py = value


class FakeGemstoneUserProfile:
    def __init__(self, user_name):
        self.user_name = user_name

    def userId(self):
        return FakeGemstoneValue(self.user_name)


class FakeGemstoneSystem:
    def __init__(self, stone_name='gs64stone', host_name='localhost', user_name='DataCurator'):
        self.selected_stone_name = stone_name
        self.selected_host_name = host_name
        self.selected_user_name = user_name

    def stoneName(self):
        return FakeGemstoneValue(self.selected_stone_name)

    def hostname(self):
        return FakeGemstoneValue(self.selected_host_name)

    def myUserProfile(self):
        return FakeGemstoneUserProfile(self.selected_user_name)


class FakeGemstoneSession:
    def __init__(self):
        self.System = FakeGemstoneSystem()
        self.commit_count = 0
        self.abort_count = 0
        self.begin_count = 0

    def execute(self, source):
        if source == 'System session':
            return FakeGemstoneValue(1)
        return FakeGemstoneValue(None)

    def commit(self):
        self.commit_count = self.commit_count + 1

    def abort(self):
        self.abort_count = self.abort_count + 1

    def begin(self):
        self.begin_count = self.begin_count + 1


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


class RestrictedToolsFixture(Fixture):
    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(registrar)
        return registrar.registered_tools_by_name

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']

    def new_gs_transaction_status(self):
        return self.registered_mcp_tools['gs_transaction_status']

    def new_gs_begin_if_needed(self):
        return self.registered_mcp_tools['gs_begin_if_needed']

    def new_gs_commit(self):
        return self.registered_mcp_tools['gs_commit']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_create_class_in_package(self):
        return self.registered_mcp_tools['gs_create_class_in_package']

    def new_gs_create_package(self):
        return self.registered_mcp_tools['gs_create_package']

    def new_gs_install_package(self):
        return self.registered_mcp_tools['gs_install_package']

    def new_gs_create_test_case_class(self):
        return self.registered_mcp_tools['gs_create_test_case_class']

    def new_gs_get_class_definition(self):
        return self.registered_mcp_tools['gs_get_class_definition']

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

    def new_gs_preview_extract_method(self):
        return self.registered_mcp_tools['gs_preview_extract_method']

    def new_gs_apply_extract_method(self):
        return self.registered_mcp_tools['gs_apply_extract_method']

    def new_gs_preview_inline_method(self):
        return self.registered_mcp_tools['gs_preview_inline_method']

    def new_gs_apply_inline_method(self):
        return self.registered_mcp_tools['gs_apply_inline_method']

    def new_gs_global_set(self):
        return self.registered_mcp_tools['gs_global_set']

    def new_gs_global_remove(self):
        return self.registered_mcp_tools['gs_global_remove']

    def new_gs_global_exists(self):
        return self.registered_mcp_tools['gs_global_exists']

    def new_gs_debug_eval(self):
        return self.registered_mcp_tools['gs_debug_eval']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def new_gs_find_senders(self):
        return self.registered_mcp_tools['gs_find_senders']

    def new_gs_method_sends(self):
        return self.registered_mcp_tools['gs_method_sends']

    def new_gs_method_ast(self):
        return self.registered_mcp_tools['gs_method_ast']

    def new_gs_method_structure_summary(self):
        return self.registered_mcp_tools['gs_method_structure_summary']

    def new_gs_method_control_flow_summary(self):
        return self.registered_mcp_tools['gs_method_control_flow_summary']

    def new_gs_query_methods_by_ast_pattern(self):
        return self.registered_mcp_tools['gs_query_methods_by_ast_pattern']

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

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']

    def new_gs_guidance(self):
        return self.registered_mcp_tools['gs_guidance']


class AllowedToolsFixture(Fixture):
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

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']

    def new_gs_transaction_status(self):
        return self.registered_mcp_tools['gs_transaction_status']

    def new_gs_begin_if_needed(self):
        return self.registered_mcp_tools['gs_begin_if_needed']

    def new_gs_commit(self):
        return self.registered_mcp_tools['gs_commit']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_create_class_in_package(self):
        return self.registered_mcp_tools['gs_create_class_in_package']

    def new_gs_create_package(self):
        return self.registered_mcp_tools['gs_create_package']

    def new_gs_install_package(self):
        return self.registered_mcp_tools['gs_install_package']

    def new_gs_create_test_case_class(self):
        return self.registered_mcp_tools['gs_create_test_case_class']

    def new_gs_get_class_definition(self):
        return self.registered_mcp_tools['gs_get_class_definition']

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

    def new_gs_preview_extract_method(self):
        return self.registered_mcp_tools['gs_preview_extract_method']

    def new_gs_apply_extract_method(self):
        return self.registered_mcp_tools['gs_apply_extract_method']

    def new_gs_preview_inline_method(self):
        return self.registered_mcp_tools['gs_preview_inline_method']

    def new_gs_apply_inline_method(self):
        return self.registered_mcp_tools['gs_apply_inline_method']

    def new_gs_global_set(self):
        return self.registered_mcp_tools['gs_global_set']

    def new_gs_global_remove(self):
        return self.registered_mcp_tools['gs_global_remove']

    def new_gs_global_exists(self):
        return self.registered_mcp_tools['gs_global_exists']

    def new_gs_debug_eval(self):
        return self.registered_mcp_tools['gs_debug_eval']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def new_gs_find_senders(self):
        return self.registered_mcp_tools['gs_find_senders']

    def new_gs_method_sends(self):
        return self.registered_mcp_tools['gs_method_sends']

    def new_gs_method_ast(self):
        return self.registered_mcp_tools['gs_method_ast']

    def new_gs_method_structure_summary(self):
        return self.registered_mcp_tools['gs_method_structure_summary']

    def new_gs_method_control_flow_summary(self):
        return self.registered_mcp_tools['gs_method_control_flow_summary']

    def new_gs_query_methods_by_ast_pattern(self):
        return self.registered_mcp_tools['gs_query_methods_by_ast_pattern']

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

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']

    def new_gs_guidance(self):
        return self.registered_mcp_tools['gs_guidance']


class AllowedToolsWithCommitConfirmationFixture(Fixture):
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

    def new_gs_commit(self):
        return self.registered_mcp_tools['gs_commit']

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']


class AllowedToolsWithNoActiveTransactionFixture(Fixture):
    @set_up
    def prepare_registry(self):
        clear_connections()

    @tear_down
    def clear_registry(self):
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

    def new_connection_id(self):
        return add_connection(
            object(),
            {
                'connection_mode': 'linked',
                'transaction_active': False,
            },
        )

    def new_gs_eval(self):
        return self.registered_mcp_tools['gs_eval']

    def new_gs_debug_eval(self):
        return self.registered_mcp_tools['gs_debug_eval']

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_create_package(self):
        return self.registered_mcp_tools['gs_create_package']

    def new_gs_install_package(self):
        return self.registered_mcp_tools['gs_install_package']

    def new_gs_global_set(self):
        return self.registered_mcp_tools['gs_global_set']

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

    def new_gs_preview_extract_method(self):
        return self.registered_mcp_tools['gs_preview_extract_method']

    def new_gs_apply_extract_method(self):
        return self.registered_mcp_tools['gs_apply_extract_method']

    def new_gs_preview_inline_method(self):
        return self.registered_mcp_tools['gs_preview_inline_method']

    def new_gs_apply_inline_method(self):
        return self.registered_mcp_tools['gs_apply_inline_method']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def new_gs_find_senders(self):
        return self.registered_mcp_tools['gs_find_senders']

    def new_gs_method_sends(self):
        return self.registered_mcp_tools['gs_method_sends']

    def new_gs_method_ast(self):
        return self.registered_mcp_tools['gs_method_ast']

    def new_gs_method_structure_summary(self):
        return self.registered_mcp_tools['gs_method_structure_summary']

    def new_gs_method_control_flow_summary(self):
        return self.registered_mcp_tools['gs_method_control_flow_summary']

    def new_gs_query_methods_by_ast_pattern(self):
        return self.registered_mcp_tools['gs_query_methods_by_ast_pattern']

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


class AllowedToolsWithNoActiveTransactionAndStrictAstFixture(Fixture):
    @set_up
    def prepare_registry(self):
        clear_connections()

    @tear_down
    def clear_registry(self):
        clear_connections()

    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=True,
            require_gemstone_ast=True,
        )
        return registrar.registered_tools_by_name

    def new_connection_id(self):
        return add_connection(
            object(),
            {
                'connection_mode': 'linked',
                'transaction_active': False,
            },
        )

    def new_gs_capabilities(self):
        return self.registered_mcp_tools['gs_capabilities']

    def new_gs_preview_extract_method(self):
        return self.registered_mcp_tools['gs_preview_extract_method']


class AllowedToolsWithActiveTransactionFixture(Fixture):
    @set_up
    def prepare_registry(self):
        clear_connections()

    @tear_down
    def clear_registry(self):
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

    def new_connection_id(self):
        return add_connection(
            object(),
            {
                'connection_mode': 'linked',
                'transaction_active': True,
            },
        )

    def new_gs_tracer_enable(self):
        return self.registered_mcp_tools['gs_tracer_enable']

    def new_gs_tracer_trace_selector(self):
        return self.registered_mcp_tools['gs_tracer_trace_selector']

    def new_gs_collect_sender_evidence(self):
        return self.registered_mcp_tools['gs_collect_sender_evidence']

    def new_gs_list_methods(self):
        return self.registered_mcp_tools['gs_list_methods']

    def new_gs_compile_method(self):
        return self.registered_mcp_tools['gs_compile_method']

    def new_gs_apply_selector_rename(self):
        return self.registered_mcp_tools['gs_apply_selector_rename']

    def new_gs_apply_rename_method(self):
        return self.registered_mcp_tools['gs_apply_rename_method']

    def new_gs_apply_move_method(self):
        return self.registered_mcp_tools['gs_apply_move_method']

    def new_gs_apply_add_parameter(self):
        return self.registered_mcp_tools['gs_apply_add_parameter']

    def new_gs_apply_remove_parameter(self):
        return self.registered_mcp_tools['gs_apply_remove_parameter']

    def new_gs_apply_extract_method(self):
        return self.registered_mcp_tools['gs_apply_extract_method']

    def new_gs_apply_inline_method(self):
        return self.registered_mcp_tools['gs_apply_inline_method']


class AllowedToolsWithTracingDisabledFixture(Fixture):
    def new_registered_mcp_tools(self):
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=False,
        )
        return registrar.registered_tools_by_name

    def new_gs_tracer_install(self):
        return self.registered_mcp_tools['gs_tracer_install']

    def new_gs_tracer_find_observed_senders(self):
        return self.registered_mcp_tools['gs_tracer_find_observed_senders']

    def new_gs_plan_evidence_tests(self):
        return self.registered_mcp_tools['gs_plan_evidence_tests']

    def new_gs_collect_sender_evidence(self):
        return self.registered_mcp_tools['gs_collect_sender_evidence']


@with_fixtures(RestrictedToolsFixture)
def test_gs_eval_is_disabled_by_default(tools_fixture):
    eval_result = tools_fixture.gs_eval('missing-connection-id', '3 + 4')
    assert not eval_result['ok']
    assert eval_result['error']['message'] == (
        'gs_eval is disabled. '
        'Start swordfish --headless-mcp with --allow-eval to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_commit_is_disabled_by_default(tools_fixture):
    commit_result = tools_fixture.gs_commit('missing-connection-id')
    assert not commit_result['ok']
    assert commit_result['error']['message'] == (
        'gs_commit is disabled. '
        'Start swordfish --headless-mcp with --allow-commit to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_capabilities_reports_restricted_policy_flags(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    policy = capabilities_result['policy']
    assert policy['allow_eval'] is False
    assert policy['allow_eval_write'] is False
    assert policy['eval_mode'] == 'disabled'
    assert policy['commit_approval_mode'] == 'disabled'
    assert not policy['eval_requires_human_approval']
    assert not policy['commit_requires_human_approval']
    assert policy['allow_compile'] is False
    assert policy['allow_commit'] is False
    assert policy['allow_tracing'] is False
    assert policy['require_gemstone_ast'] is False
    assert capabilities_result['ast_backend']['active_backend'] == 'source_heuristic'
    assert not capabilities_result['ast_backend']['real_gemstone_ast_available']
    assert capabilities_result['ast_support']['expected_version']
    assert capabilities_result['ast_support']['expected_source_hash']
    assert capabilities_result['ast_support']['tools'] == [
        'gs_ast_status',
        'gs_ast_install',
    ]
    assert capabilities_result['recommended_bootstrap'] == [
        'gs_capabilities',
        'gs_guidance',
        'gs_connect',
        'gs_transaction_status',
    ]


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_reports_enabled_policy_flags(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    policy = capabilities_result['policy']
    assert policy['allow_eval'] is True
    assert policy['allow_eval_write'] is False
    assert policy['eval_mode'] == 'approval_required'
    assert policy['commit_approval_mode'] == 'explicit_confirmation'
    assert policy['eval_requires_human_approval']
    assert policy['commit_requires_human_approval']
    assert policy['allow_compile'] is True
    assert policy['allow_commit'] is True
    assert policy['allow_tracing'] is True
    assert policy['require_gemstone_ast'] is False


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_safe_write_includes_package_tools(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    safe_write_tools = capabilities_result['tool_groups']['safe_write']
    assert 'gs_create_package' in safe_write_tools
    assert 'gs_install_package' in safe_write_tools
    assert 'gs_create_class_in_package' in safe_write_tools
    assert 'gs_create_test_case_class' in safe_write_tools


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_navigation_includes_method_semantic_tools(
    tools_fixture,
):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    navigation_tools = capabilities_result['tool_groups']['navigation']
    assert 'gs_ast_status' in navigation_tools
    assert 'gs_method_ast' in navigation_tools
    assert 'gs_method_sends' in navigation_tools
    assert 'gs_method_structure_summary' in navigation_tools
    assert 'gs_method_control_flow_summary' in navigation_tools
    assert 'gs_query_methods_by_ast_pattern' in navigation_tools


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_refactor_includes_move_method_tools(
    tools_fixture,
):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    refactor_tools = capabilities_result['tool_groups']['refactor']
    assert 'gs_preview_move_method' in refactor_tools
    assert 'gs_apply_move_method' in refactor_tools
    assert 'gs_preview_add_parameter' in refactor_tools
    assert 'gs_apply_add_parameter' in refactor_tools
    assert 'gs_preview_remove_parameter' in refactor_tools
    assert 'gs_apply_remove_parameter' in refactor_tools
    assert 'gs_preview_extract_method' in refactor_tools
    assert 'gs_apply_extract_method' in refactor_tools
    assert 'gs_preview_inline_method' in refactor_tools
    assert 'gs_apply_inline_method' in refactor_tools


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_exposes_ast_support_tool_group(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    ast_support_tools = capabilities_result['tool_groups']['ast_support']
    assert ast_support_tools == ['gs_ast_status', 'gs_ast_install']


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_validates_intent(tools_fixture):
    guidance_result = tools_fixture.gs_guidance('unknown_intent')
    assert not guidance_result['ok']
    assert guidance_result['error']['message'] == (
        'intent must be one of: general, navigation, sender_analysis, '
        'refactor, runtime_evidence.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_sender_analysis_recommends_evidence_workflow(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'sender_analysis',
        selector='default',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_find_senders']
    assert workflow[1]['tools'] == ['gs_plan_evidence_tests']
    assert workflow[2]['tools'] == ['gs_collect_sender_evidence']


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_navigation_recommends_method_ast(tools_fixture):
    guidance_result = tools_fixture.gs_guidance('navigation')
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert 'gs_method_ast' in workflow[2]['tools']
    assert 'gs_query_methods_by_ast_pattern' in workflow[2]['tools']


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_rename_method_recommends_method_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='rename_method',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_rename_method']
    assert workflow[2]['tools'][0] == 'gs_apply_rename_method'


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_move_method_recommends_move_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='move_method',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_move_method']
    assert workflow[2]['tools'][0] == 'gs_apply_move_method'


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_add_parameter_recommends_parameter_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='add_parameter',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_add_parameter']
    assert workflow[2]['tools'][0] == 'gs_apply_add_parameter'


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_remove_parameter_recommends_parameter_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='remove_parameter',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_remove_parameter']
    assert workflow[2]['tools'][0] == 'gs_apply_remove_parameter'


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_extract_method_recommends_extract_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='extract_method',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_extract_method']
    assert workflow[2]['tools'][0] == 'gs_apply_extract_method'


@with_fixtures(AllowedToolsFixture)
def test_gs_guidance_refactor_inline_method_recommends_inline_tools(
    tools_fixture,
):
    guidance_result = tools_fixture.gs_guidance(
        'refactor',
        change_kind='inline_method',
    )
    assert guidance_result['ok'], guidance_result
    workflow = guidance_result['guidance']['workflow']
    assert workflow[0]['tools'] == ['gs_preview_inline_method']
    assert workflow[2]['tools'][0] == 'gs_apply_inline_method'


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_install_is_disabled_by_default(tools_fixture):
    tracer_install_result = tools_fixture.gs_tracer_install(
        'missing-connection-id'
    )
    assert not tracer_install_result['ok']
    assert tracer_install_result['error']['message'] == (
        'gs_tracer_install is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_ast_install_is_disabled_by_default(tools_fixture):
    ast_install = tools_fixture.registered_mcp_tools['gs_ast_install']
    ast_install_result = ast_install('missing-connection-id')
    assert not ast_install_result['ok']
    assert ast_install_result['error']['message'] == (
        'gs_ast_install is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_enable_is_disabled_by_default(tools_fixture):
    tracer_enable_result = tools_fixture.gs_tracer_enable(
        'missing-connection-id'
    )
    assert not tracer_enable_result['ok']
    assert tracer_enable_result['error']['message'] == (
        'gs_tracer_enable is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_disable_is_disabled_by_default(tools_fixture):
    tracer_disable_result = tools_fixture.gs_tracer_disable(
        'missing-connection-id'
    )
    assert not tracer_disable_result['ok']
    assert tracer_disable_result['error']['message'] == (
        'gs_tracer_disable is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_uninstall_is_disabled_by_default(tools_fixture):
    tracer_uninstall_result = tools_fixture.gs_tracer_uninstall(
        'missing-connection-id'
    )
    assert not tracer_uninstall_result['ok']
    assert tracer_uninstall_result['error']['message'] == (
        'gs_tracer_uninstall is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_trace_selector_is_disabled_by_default(tools_fixture):
    tracer_trace_selector_result = tools_fixture.gs_tracer_trace_selector(
        'missing-connection-id',
        'yourself',
    )
    assert not tracer_trace_selector_result['ok']
    assert tracer_trace_selector_result['error']['message'] == (
        'gs_tracer_trace_selector is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_untrace_selector_is_disabled_by_default(tools_fixture):
    tracer_untrace_selector_result = tools_fixture.gs_tracer_untrace_selector(
        'missing-connection-id',
        'yourself',
    )
    assert not tracer_untrace_selector_result['ok']
    assert tracer_untrace_selector_result['error']['message'] == (
        'gs_tracer_untrace_selector is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_clear_observed_senders_is_disabled_by_default(
    tools_fixture,
):
    tracer_clear_observed_senders_result = (
        tools_fixture.gs_tracer_clear_observed_senders(
            'missing-connection-id'
        )
    )
    assert not tracer_clear_observed_senders_result['ok']
    assert tracer_clear_observed_senders_result['error']['message'] == (
        'gs_tracer_clear_observed_senders is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(AllowedToolsWithTracingDisabledFixture)
def test_gs_tracer_install_is_disabled_when_tracing_flag_is_off(
    tools_fixture,
):
    tracer_install_result = tools_fixture.gs_tracer_install(
        'missing-connection-id'
    )
    assert not tracer_install_result['ok']
    assert tracer_install_result['error']['message'] == (
        'gs_tracer_install is disabled. '
        'Start swordfish --headless-mcp with --allow-tracing to enable.'
    )


@with_fixtures(AllowedToolsWithTracingDisabledFixture)
def test_gs_tracer_find_observed_senders_is_disabled_when_tracing_flag_is_off(
    tools_fixture,
):
    observed_senders_result = tools_fixture.gs_tracer_find_observed_senders(
        'missing-connection-id',
        'yourself',
    )
    assert not observed_senders_result['ok']
    assert observed_senders_result['error']['message'] == (
        'gs_tracer_find_observed_senders is disabled. '
        'Start swordfish --headless-mcp with --allow-tracing to enable.'
    )


@with_fixtures(AllowedToolsWithTracingDisabledFixture)
def test_gs_plan_evidence_tests_is_disabled_when_tracing_flag_is_off(
    tools_fixture,
):
    plan_result = tools_fixture.gs_plan_evidence_tests(
        'missing-connection-id',
        'yourself',
    )
    assert not plan_result['ok']
    assert plan_result['error']['message'] == (
        'gs_plan_evidence_tests is disabled. '
        'Start swordfish --headless-mcp with --allow-tracing to enable.'
    )


@with_fixtures(AllowedToolsWithTracingDisabledFixture)
def test_gs_collect_sender_evidence_is_disabled_when_tracing_flag_is_off(
    tools_fixture,
):
    collect_result = tools_fixture.gs_collect_sender_evidence(
        'missing-connection-id',
        'yourself',
    )
    assert not collect_result['ok']
    assert collect_result['error']['message'] == (
        'gs_collect_sender_evidence is disabled. '
        'Start swordfish --headless-mcp with --allow-tracing to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_compile_method_is_disabled_by_default(tools_fixture):
    compile_result = tools_fixture.gs_compile_method(
        'missing-connection-id',
        'Object',
        'foo ^1',
        True,
    )
    assert not compile_result['ok']
    assert compile_result['error']['message'] == (
        'gs_compile_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_create_class_is_disabled_by_default(tools_fixture):
    create_result = tools_fixture.gs_create_class(
        'missing-connection-id',
        'ExampleClass',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'gs_create_class is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_create_class_in_package_is_disabled_by_default(tools_fixture):
    create_result = tools_fixture.gs_create_class_in_package(
        'missing-connection-id',
        'ExampleClass',
        'ExamplePackage',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'gs_create_class is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_create_package_is_disabled_by_default(tools_fixture):
    create_result = tools_fixture.gs_create_package(
        'missing-connection-id',
        'ExamplePackage',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'gs_create_package is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_install_package_is_disabled_by_default(tools_fixture):
    install_result = tools_fixture.gs_install_package(
        'missing-connection-id',
        'ExamplePackage',
    )
    assert not install_result['ok']
    assert install_result['error']['message'] == (
        'gs_install_package is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_create_test_case_class_is_disabled_by_default(tools_fixture):
    create_result = tools_fixture.gs_create_test_case_class(
        'missing-connection-id',
        'ExampleTestCase',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'gs_create_test_case_class is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_delete_class_is_disabled_by_default(tools_fixture):
    delete_result = tools_fixture.gs_delete_class(
        'missing-connection-id',
        'ExampleClass',
    )
    assert not delete_result['ok']
    assert delete_result['error']['message'] == (
        'gs_delete_class is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_delete_method_is_disabled_by_default(tools_fixture):
    delete_result = tools_fixture.gs_delete_method(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not delete_result['ok']
    assert delete_result['error']['message'] == (
        'gs_delete_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_set_method_category_is_disabled_by_default(tools_fixture):
    set_result = tools_fixture.gs_set_method_category(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
        'examples',
    )
    assert not set_result['ok']
    assert set_result['error']['message'] == (
        'gs_set_method_category is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_global_set_is_disabled_by_default(tools_fixture):
    set_result = tools_fixture.gs_global_set(
        'missing-connection-id',
        'EXAMPLE_GLOBAL',
        1,
    )
    assert not set_result['ok']
    assert set_result['error']['message'] == (
        'gs_global_set is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_global_remove_is_disabled_by_default(tools_fixture):
    remove_result = tools_fixture.gs_global_remove(
        'missing-connection-id',
        'EXAMPLE_GLOBAL',
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == (
        'gs_global_remove is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_selector_rename_is_disabled_by_default(tools_fixture):
    rename_result = tools_fixture.gs_apply_selector_rename(
        'missing-connection-id',
        'oldSelector',
        'newSelector',
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'gs_apply_selector_rename is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_rename_method_is_disabled_by_default(tools_fixture):
    rename_result = tools_fixture.gs_apply_rename_method(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector',
        'newSelector',
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'gs_apply_rename_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_move_method_is_disabled_by_default(tools_fixture):
    move_result = tools_fixture.gs_apply_move_method(
        'missing-connection-id',
        'SourceClass',
        'someSelector',
        'TargetClass',
    )
    assert not move_result['ok']
    assert move_result['error']['message'] == (
        'gs_apply_move_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_add_parameter_is_disabled_by_default(tools_fixture):
    add_result = tools_fixture.gs_apply_add_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:',
        'timeout:',
        'timeout',
        '30',
    )
    assert not add_result['ok']
    assert add_result['error']['message'] == (
        'gs_apply_add_parameter is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_remove_parameter_is_disabled_by_default(tools_fixture):
    remove_result = tools_fixture.gs_apply_remove_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == (
        'gs_apply_remove_parameter is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_extract_method_is_disabled_by_default(tools_fixture):
    extract_result = tools_fixture.gs_apply_extract_method(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
        'extractedLogic',
        [1],
    )
    assert not extract_result['ok']
    assert extract_result['error']['message'] == (
        'gs_apply_extract_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_apply_inline_method_is_disabled_by_default(tools_fixture):
    inline_result = tools_fixture.gs_apply_inline_method(
        'missing-connection-id',
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
    )
    assert not inline_result['ok']
    assert inline_result['error']['message'] == (
        'gs_apply_inline_method is disabled. '
        'Start swordfish --headless-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_debug_eval_is_disabled_by_default(tools_fixture):
    debug_eval_result = tools_fixture.gs_debug_eval(
        'missing-connection-id',
        '3 + 4',
    )
    assert not debug_eval_result['ok']
    assert debug_eval_result['error']['message'] == (
        'gs_debug_eval is disabled. '
        'Start swordfish --headless-mcp with --allow-eval to enable.'
    )


def test_register_tools_allows_eval_without_extra_approval_configuration():
    registrar = McpToolRegistrar()
    with expected(NoException):
        register_tools(
            registrar,
            allow_eval=True,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=False,
        )


def test_register_tools_allows_commit_with_explicit_confirmation_policy():
    registrar = McpToolRegistrar()
    with expected(NoException):
        register_tools(
            registrar,
            allow_eval=False,
            allow_compile=True,
            allow_commit=True,
            allow_tracing=False,
        )


@with_fixtures(AllowedToolsFixture)
def test_gs_eval_requires_unsafe_flag_when_allowed(tools_fixture):
    eval_result = tools_fixture.gs_eval(
        'missing-connection-id',
        '3 + 4',
        approved_by_user=True,
        reason='connection check',
    )
    assert not eval_result['ok']
    assert eval_result['error']['message'] == (
        'gs_eval requires unsafe=True. '
        'Prefer explicit gs_* tools when possible.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_eval_checks_connection_when_allowed(tools_fixture):
    eval_result = tools_fixture.gs_eval(
        'missing-connection-id',
        '3 + 4',
        unsafe=True,
        approved_by_user=True,
        reason='connection check',
    )
    assert not eval_result['ok']
    assert eval_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_eval_requires_non_empty_reason_when_approved(tools_fixture):
    eval_result = tools_fixture.gs_eval(
        tools_fixture.connection_id,
        '3 + 4',
        unsafe=True,
        approved_by_user=True,
        reason='',
    )
    assert not eval_result['ok']
    assert eval_result['error']['message'] == 'reason cannot be empty.'


@with_fixtures(AllowedToolsFixture)
def test_gs_capabilities_reports_eval_approval_mode(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    policy = capabilities_result['policy']
    assert policy['allow_eval']
    assert not policy['allow_eval_write']
    assert policy['eval_mode'] == 'approval_required'
    assert policy['require_gemstone_ast'] is False


@with_fixtures(AllowedToolsWithNoActiveTransactionAndStrictAstFixture)
def test_strict_ast_mode_blocks_heuristic_extract_preview(tools_fixture):
    preview_result = tools_fixture.gs_preview_extract_method(
        tools_fixture.connection_id,
        'SomeClass',
        'someMethod',
        'newMethod',
        [1],
        True,
    )
    assert not preview_result['ok']
    assert 'requires real GemStone AST' in preview_result['error']['message']


@with_fixtures(AllowedToolsWithNoActiveTransactionAndStrictAstFixture)
def test_gs_capabilities_reports_strict_ast_mode_policy(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['require_gemstone_ast']
    assert capabilities_result['ast_backend']['active_backend'] == 'source_heuristic'
    assert not capabilities_result['ast_backend']['real_gemstone_ast_available']


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_eval_requires_explicit_confirmation(tools_fixture):
    eval_result = tools_fixture.gs_eval(
        tools_fixture.connection_id,
        'System commit',
        unsafe=True,
        reason='policy-check',
    )
    assert not eval_result['ok']
    assert (
        'gs_eval requires human approval for eval bypass.'
        in eval_result['error']['message']
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_debug_eval_requires_explicit_confirmation(tools_fixture):
    eval_result = tools_fixture.gs_debug_eval(
        tools_fixture.connection_id,
        'System commit',
        reason='policy-check',
    )
    assert not eval_result['ok']
    assert (
        'gs_debug_eval requires human approval for eval bypass.'
        in eval_result['error']['message']
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_transaction_status_checks_connection_when_allowed(tools_fixture):
    status_result = tools_fixture.gs_transaction_status('missing-connection-id')
    assert not status_result['ok']
    assert status_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_begin_if_needed_checks_connection_when_allowed(tools_fixture):
    begin_result = tools_fixture.gs_begin_if_needed('missing-connection-id')
    assert not begin_result['ok']
    assert begin_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_commit_checks_connection_when_allowed(tools_fixture):
    commit_result = tools_fixture.gs_commit(
        'missing-connection-id',
        approved_by_user=True,
        approval_note='User explicitly approved this commit.',
    )
    assert not commit_result['ok']
    assert commit_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_commit_requires_explicit_confirmation(tools_fixture):
    commit_result = tools_fixture.gs_commit('missing-connection-id')
    assert not commit_result['ok']
    assert (
        'gs_commit requires human approval for commit.'
        in commit_result['error']['message']
    )


@with_fixtures(AllowedToolsWithCommitConfirmationFixture)
def test_gs_commit_reports_explicit_confirmation_mode(
    tools_fixture,
):
    commit_result = tools_fixture.gs_commit('missing-connection-id')
    assert not commit_result['ok']
    assert (
        'gs_commit requires human approval for commit.'
        in commit_result['error']['message']
    )
    assert (
        commit_result['error']['approval']['mode']
        == 'explicit_confirmation'
    )


@with_fixtures(AllowedToolsWithCommitConfirmationFixture)
def test_gs_commit_requires_approval_note_in_confirmation_mode(
    tools_fixture,
):
    commit_result = tools_fixture.gs_commit(
        'missing-connection-id',
        approved_by_user=True,
        approval_note='',
    )
    assert not commit_result['ok']
    assert commit_result['error']['message'] == 'approval_note cannot be empty.'


@with_fixtures(AllowedToolsWithCommitConfirmationFixture)
def test_gs_commit_checks_connection_with_explicit_confirmation(
    tools_fixture,
):
    commit_result = tools_fixture.gs_commit(
        'missing-connection-id',
        approved_by_user=True,
        approval_note='User explicitly approved this commit.',
    )
    assert not commit_result['ok']
    assert commit_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsWithCommitConfirmationFixture)
def test_gs_capabilities_reports_commit_confirmation_mode(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['commit_requires_human_approval']
    assert (
        capabilities_result['policy']['commit_approval_mode']
        == 'explicit_confirmation'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_compile_method_checks_connection_when_allowed(tools_fixture):
    compile_result = tools_fixture.gs_compile_method(
        'missing-connection-id',
        'Object',
        'foo ^1',
        True,
    )
    assert not compile_result['ok']
    assert compile_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_create_class_checks_connection_when_allowed(tools_fixture):
    create_result = tools_fixture.gs_create_class(
        'missing-connection-id',
        'ExampleClass',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_create_class_in_package_checks_connection_when_allowed(
    tools_fixture,
):
    create_result = tools_fixture.gs_create_class_in_package(
        'missing-connection-id',
        'ExampleClass',
        'ExamplePackage',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_create_test_case_class_checks_connection_when_allowed(
    tools_fixture,
):
    create_result = tools_fixture.gs_create_test_case_class(
        'missing-connection-id',
        'ExampleTestCase',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_get_class_definition_checks_connection(tools_fixture):
    class_result = tools_fixture.gs_get_class_definition(
        'missing-connection-id',
        'ExampleClass',
    )
    assert not class_result['ok']
    assert class_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_delete_class_checks_connection_when_allowed(tools_fixture):
    delete_result = tools_fixture.gs_delete_class(
        'missing-connection-id',
        'ExampleClass',
    )
    assert not delete_result['ok']
    assert delete_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_delete_method_checks_connection_when_allowed(tools_fixture):
    delete_result = tools_fixture.gs_delete_method(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not delete_result['ok']
    assert delete_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_set_method_category_checks_connection_when_allowed(tools_fixture):
    set_result = tools_fixture.gs_set_method_category(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
        'examples',
    )
    assert not set_result['ok']
    assert set_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_list_test_case_classes_checks_connection(tools_fixture):
    class_result = tools_fixture.gs_list_test_case_classes(
        'missing-connection-id',
    )
    assert not class_result['ok']
    assert class_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_run_tests_in_package_checks_connection(tools_fixture):
    run_result = tools_fixture.gs_run_tests_in_package(
        'missing-connection-id',
        'Kernel-Objects',
    )
    assert not run_result['ok']
    assert run_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_run_test_method_checks_connection(tools_fixture):
    run_result = tools_fixture.gs_run_test_method(
        'missing-connection-id',
        'ExampleTestCase',
        'testPass',
    )
    assert not run_result['ok']
    assert run_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_selector_rename_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_selector_rename(
        'missing-connection-id',
        'oldSelector',
        'newSelector',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_rename_method_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_rename_method(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector',
        'newSelector',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_move_method_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_move_method(
        'missing-connection-id',
        'SourceClass',
        'someSelector',
        'TargetClass',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_add_parameter_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_add_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:',
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_remove_parameter_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_remove_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_extract_method_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_extract_method(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
        'extractedLogic',
        [1],
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_preview_inline_method_checks_connection(tools_fixture):
    preview_result = tools_fixture.gs_preview_inline_method(
        'missing-connection-id',
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_find_implementors_checks_connection(tools_fixture):
    implementors_result = tools_fixture.gs_find_implementors(
        'missing-connection-id',
        'yourself',
    )
    assert not implementors_result['ok']
    assert implementors_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_find_senders_checks_connection(tools_fixture):
    senders_result = tools_fixture.gs_find_senders(
        'missing-connection-id',
        'yourself',
    )
    assert not senders_result['ok']
    assert senders_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_method_sends_checks_connection(tools_fixture):
    sends_result = tools_fixture.gs_method_sends(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not sends_result['ok']
    assert sends_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_method_structure_summary_checks_connection(tools_fixture):
    summary_result = tools_fixture.gs_method_structure_summary(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not summary_result['ok']
    assert summary_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_method_ast_checks_connection(tools_fixture):
    ast_result = tools_fixture.gs_method_ast(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not ast_result['ok']
    assert ast_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_ast_status_checks_connection(tools_fixture):
    ast_status = tools_fixture.registered_mcp_tools['gs_ast_status']
    ast_status_result = ast_status('missing-connection-id')
    assert not ast_status_result['ok']
    assert ast_status_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_ast_install_checks_connection(tools_fixture):
    ast_install = tools_fixture.registered_mcp_tools['gs_ast_install']
    ast_install_result = ast_install('missing-connection-id')
    assert not ast_install_result['ok']
    assert ast_install_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_method_control_flow_summary_checks_connection(tools_fixture):
    summary_result = tools_fixture.gs_method_control_flow_summary(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
    )
    assert not summary_result['ok']
    assert summary_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_query_methods_by_ast_pattern_checks_connection(tools_fixture):
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        'missing-connection-id',
        {'min_send_count': 1},
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_status_checks_connection(tools_fixture):
    tracer_status_result = tools_fixture.gs_tracer_status(
        'missing-connection-id'
    )
    assert not tracer_status_result['ok']
    assert tracer_status_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_install_checks_connection(tools_fixture):
    tracer_install_result = tools_fixture.gs_tracer_install(
        'missing-connection-id'
    )
    assert not tracer_install_result['ok']
    assert tracer_install_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_enable_checks_connection(tools_fixture):
    tracer_enable_result = tools_fixture.gs_tracer_enable(
        'missing-connection-id'
    )
    assert not tracer_enable_result['ok']
    assert tracer_enable_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_disable_checks_connection(tools_fixture):
    tracer_disable_result = tools_fixture.gs_tracer_disable(
        'missing-connection-id'
    )
    assert not tracer_disable_result['ok']
    assert tracer_disable_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_uninstall_checks_connection(tools_fixture):
    tracer_uninstall_result = tools_fixture.gs_tracer_uninstall(
        'missing-connection-id'
    )
    assert not tracer_uninstall_result['ok']
    assert tracer_uninstall_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_trace_selector_checks_connection(tools_fixture):
    tracer_trace_selector_result = tools_fixture.gs_tracer_trace_selector(
        'missing-connection-id',
        'yourself',
    )
    assert not tracer_trace_selector_result['ok']
    assert tracer_trace_selector_result['error']['message'] == (
        'Unknown connection_id.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_untrace_selector_checks_connection(tools_fixture):
    tracer_untrace_selector_result = tools_fixture.gs_tracer_untrace_selector(
        'missing-connection-id',
        'yourself',
    )
    assert not tracer_untrace_selector_result['ok']
    assert tracer_untrace_selector_result['error']['message'] == (
        'Unknown connection_id.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_clear_observed_senders_checks_connection(tools_fixture):
    tracer_clear_observed_senders_result = (
        tools_fixture.gs_tracer_clear_observed_senders(
            'missing-connection-id'
        )
    )
    assert not tracer_clear_observed_senders_result['ok']
    assert tracer_clear_observed_senders_result['error']['message'] == (
        'Unknown connection_id.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_tracer_find_observed_senders_checks_connection(tools_fixture):
    tracer_find_observed_senders_result = (
        tools_fixture.gs_tracer_find_observed_senders(
            'missing-connection-id',
            'yourself',
        )
    )
    assert not tracer_find_observed_senders_result['ok']
    assert tracer_find_observed_senders_result['error']['message'] == (
        'Unknown connection_id.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_plan_evidence_tests_checks_connection(tools_fixture):
    plan_result = tools_fixture.gs_plan_evidence_tests(
        'missing-connection-id',
        'yourself',
    )
    assert not plan_result['ok']
    assert plan_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_collect_sender_evidence_checks_connection(tools_fixture):
    collect_result = tools_fixture.gs_collect_sender_evidence(
        'missing-connection-id',
        'yourself',
    )
    assert not collect_result['ok']
    assert collect_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_selector_rename_checks_connection(tools_fixture):
    rename_result = tools_fixture.gs_apply_selector_rename(
        'missing-connection-id',
        'oldSelector',
        'newSelector',
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_rename_method_checks_connection(tools_fixture):
    rename_result = tools_fixture.gs_apply_rename_method(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector',
        'newSelector',
        True,
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_move_method_checks_connection(tools_fixture):
    move_result = tools_fixture.gs_apply_move_method(
        'missing-connection-id',
        'SourceClass',
        'someSelector',
        'TargetClass',
    )
    assert not move_result['ok']
    assert move_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_add_parameter_checks_connection(tools_fixture):
    add_result = tools_fixture.gs_apply_add_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:',
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert not add_result['ok']
    assert add_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_remove_parameter_checks_connection(tools_fixture):
    remove_result = tools_fixture.gs_apply_remove_parameter(
        'missing-connection-id',
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_extract_method_checks_connection(tools_fixture):
    extract_result = tools_fixture.gs_apply_extract_method(
        'missing-connection-id',
        'ExampleClass',
        'exampleMethod',
        'extractedLogic',
        [1],
        True,
    )
    assert not extract_result['ok']
    assert extract_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_apply_inline_method_checks_connection(tools_fixture):
    inline_result = tools_fixture.gs_apply_inline_method(
        'missing-connection-id',
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
        True,
    )
    assert not inline_result['ok']
    assert inline_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_global_set_checks_connection(tools_fixture):
    set_result = tools_fixture.gs_global_set(
        'missing-connection-id',
        'EXAMPLE_GLOBAL',
        1,
    )
    assert not set_result['ok']
    assert set_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_global_remove_checks_connection(tools_fixture):
    remove_result = tools_fixture.gs_global_remove(
        'missing-connection-id',
        'EXAMPLE_GLOBAL',
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_global_exists_checks_connection(tools_fixture):
    exists_result = tools_fixture.gs_global_exists(
        'missing-connection-id',
        'EXAMPLE_GLOBAL',
    )
    assert not exists_result['ok']
    assert exists_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsFixture)
def test_gs_debug_eval_checks_connection_when_allowed(tools_fixture):
    debug_eval_result = tools_fixture.gs_debug_eval(
        'missing-connection-id',
        '3 + 4',
        approved_by_user=True,
        reason='connection check',
    )
    assert not debug_eval_result['ok']
    assert debug_eval_result['error']['message'] == 'Unknown connection_id.'


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_find_implementors_validates_max_results(tools_fixture):
    implementors_result = tools_fixture.gs_find_implementors(
        tools_fixture.connection_id,
        'yourself',
        max_results=-1,
    )
    assert not implementors_result['ok']
    assert implementors_result['error']['message'] == (
        'max_results cannot be negative.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_find_senders_validates_method_name(tools_fixture):
    senders_result = tools_fixture.gs_find_senders(
        tools_fixture.connection_id,
        '',
    )
    assert not senders_result['ok']
    assert senders_result['error']['message'] == 'method_name cannot be empty.'


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_find_senders_validates_count_only_flag(tools_fixture):
    senders_result = tools_fixture.gs_find_senders(
        tools_fixture.connection_id,
        'yourself',
        count_only='true',
    )
    assert not senders_result['ok']
    assert senders_result['error']['message'] == 'count_only must be a boolean.'


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_list_methods_validates_show_instance_side_flag(tools_fixture):
    methods_result = tools_fixture.gs_list_methods(
        tools_fixture.connection_id,
        'ExampleClass',
        'all',
        'neither',
    )
    assert not methods_result['ok']
    assert methods_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_compile_method_validates_show_instance_side_flag(tools_fixture):
    compile_result = tools_fixture.gs_compile_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleSelector ^1',
        'neither',
    )
    assert not compile_result['ok']
    assert compile_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_method_sends_validates_show_instance_side_flag(tools_fixture):
    sends_result = tools_fixture.gs_method_sends(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'neither',
    )
    assert not sends_result['ok']
    assert sends_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_method_structure_summary_validates_show_instance_side_flag(
    tools_fixture,
):
    summary_result = tools_fixture.gs_method_structure_summary(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'neither',
    )
    assert not summary_result['ok']
    assert summary_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_method_ast_validates_show_instance_side_flag(
    tools_fixture,
):
    ast_result = tools_fixture.gs_method_ast(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'neither',
    )
    assert not ast_result['ok']
    assert ast_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_method_control_flow_summary_validates_show_instance_side_flag(
    tools_fixture,
):
    summary_result = tools_fixture.gs_method_control_flow_summary(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'neither',
    )
    assert not summary_result['ok']
    assert summary_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_query_methods_by_ast_pattern_validates_pattern_and_filters(
    tools_fixture,
):
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        'not-a-dictionary',
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'ast_pattern must be a dictionary.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'unknown_field': 1},
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'Unsupported ast_pattern field: unknown_field.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'min_send_count': 2, 'max_send_count': 1},
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'ast_pattern.min_send_count cannot be greater than '
        'ast_pattern.max_send_count.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'min_send_count': 1},
        show_instance_side='neither',
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'min_send_count': 1},
        max_results=-1,
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'max_results cannot be negative.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'min_send_count': 1},
        sort_by='not_supported',
    )
    assert not query_result['ok']
    assert query_result['error']['message'].startswith(
        'sort_by must be one of:'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'min_send_count': 1},
        sort_descending='neither',
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'sort_descending must be a boolean.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'required_send_types': ['ternary']},
    )
    assert not query_result['ok']
    assert query_result['error']['message'] == (
        'ast_pattern.required_send_types entries must be one of: '
        'binary, keyword, unary.'
    )
    query_result = tools_fixture.gs_query_methods_by_ast_pattern(
        tools_fixture.connection_id,
        {'method_selector_regex': '['},
    )
    assert not query_result['ok']
    assert query_result['error']['message'].startswith(
        'ast_pattern.method_selector_regex is not valid regex:'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_rename_method_validates_show_instance_side_flag(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_rename_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector',
        'newSelector',
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_move_method_validates_show_instance_side_flags(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_move_method(
        tools_fixture.connection_id,
        'SourceClass',
        'someSelector',
        'TargetClass',
        'neither',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'source_show_instance_side must be a boolean.'
    )
    preview_result = tools_fixture.gs_preview_move_method(
        tools_fixture.connection_id,
        'SourceClass',
        'someSelector',
        'TargetClass',
        True,
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'target_show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_apply_move_method_validates_boolean_flags(
    tools_fixture,
):
    move_result = tools_fixture.gs_apply_move_method(
        tools_fixture.connection_id,
        'SourceClass',
        'someSelector',
        'TargetClass',
        True,
        True,
        'neither',
        True,
    )
    assert not move_result['ok']
    assert move_result['error']['message'] == (
        'overwrite_target_method must be a boolean.'
    )
    move_result = tools_fixture.gs_apply_move_method(
        tools_fixture.connection_id,
        'SourceClass',
        'someSelector',
        'TargetClass',
        True,
        True,
        True,
        'neither',
    )
    assert not move_result['ok']
    assert move_result['error']['message'] == (
        'delete_source_method must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_add_parameter_validates_keyword_and_side(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_add_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector',
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'method_selector must be a keyword selector.'
    )
    preview_result = tools_fixture.gs_preview_add_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:',
        'timeout',
        'timeout',
        '30',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'parameter_keyword must be a keyword token ending in : '
        '(example: timeout:).'
    )
    preview_result = tools_fixture.gs_preview_add_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:',
        'timeout:',
        'timeout',
        '30',
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_remove_parameter_validates_keyword_and_side(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector',
        'timeout:',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'method_selector must be a keyword selector.'
    )
    preview_result = tools_fixture.gs_preview_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'parameter_keyword must be a keyword token ending in : '
        '(example: timeout:).'
    )
    preview_result = tools_fixture.gs_preview_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )
    preview_result = tools_fixture.gs_preview_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'rewrite_source_senders must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_apply_remove_parameter_validates_boolean_flags(tools_fixture):
    remove_result = tools_fixture.gs_apply_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
        'neither',
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == (
        'overwrite_new_method must be a boolean.'
    )
    remove_result = tools_fixture.gs_apply_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
        False,
        'neither',
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == (
        'rewrite_source_senders must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_extract_method_validates_statement_indexes_and_selector(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'newSelector:',
        [1],
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'new_selector must be a unary selector.'
    )
    preview_result = tools_fixture.gs_preview_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'newSelector',
        'not-a-list',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'statement_indexes must be a non-empty list of integers.'
    )
    preview_result = tools_fixture.gs_preview_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'newSelector',
        [0],
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'statement_indexes must contain positive integers only.'
    )
    preview_result = tools_fixture.gs_preview_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'newSelector',
        [1],
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_preview_inline_method_validates_selector_and_side(
    tools_fixture,
):
    preview_result = tools_fixture.gs_preview_inline_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'callerSelector',
        'inlineSelector:',
        True,
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'inline_selector must be a unary selector.'
    )
    preview_result = tools_fixture.gs_preview_inline_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
        'neither',
    )
    assert not preview_result['ok']
    assert preview_result['error']['message'] == (
        'show_instance_side must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_apply_extract_and_inline_validate_boolean_flags(
    tools_fixture,
):
    extract_result = tools_fixture.gs_apply_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'extractedLogic',
        [1],
        True,
        'neither',
    )
    assert not extract_result['ok']
    assert extract_result['error']['message'] == (
        'overwrite_new_method must be a boolean.'
    )
    inline_result = tools_fixture.gs_apply_inline_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
        True,
        'neither',
    )
    assert not inline_result['ok']
    assert inline_result['error']['message'] == (
        'delete_inlined_method must be a boolean.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_tracer_find_observed_senders_validates_method_name(tools_fixture):
    tracer_find_observed_senders_result = (
        tools_fixture.gs_tracer_find_observed_senders(
            tools_fixture.connection_id,
            'not a selector',
        )
    )
    assert not tracer_find_observed_senders_result['ok']
    assert tracer_find_observed_senders_result['error']['message'] == (
        'method_name must be a unary selector (exampleSelector) '
        'or keyword selector (example:with:).'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_tracer_find_observed_senders_validates_count_only_flag(
    tools_fixture,
):
    tracer_find_observed_senders_result = (
        tools_fixture.gs_tracer_find_observed_senders(
            tools_fixture.connection_id,
            'yourself',
            count_only='true',
        )
    )
    assert not tracer_find_observed_senders_result['ok']
    assert tracer_find_observed_senders_result['error']['message'] == (
        'count_only must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_tracer_trace_selector_validates_method_name(tools_fixture):
    tracer_trace_selector_result = tools_fixture.gs_tracer_trace_selector(
        tools_fixture.connection_id,
        'not a selector',
    )
    assert not tracer_trace_selector_result['ok']
    assert tracer_trace_selector_result['error']['message'] == (
        'method_name must be a unary selector (exampleSelector) '
        'or keyword selector (example:with:).'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_tracer_trace_selector_validates_max_results(tools_fixture):
    tracer_trace_selector_result = tools_fixture.gs_tracer_trace_selector(
        tools_fixture.connection_id,
        'yourself',
        max_results=-1,
    )
    assert not tracer_trace_selector_result['ok']
    assert tracer_trace_selector_result['error']['message'] == (
        'max_results cannot be negative.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_plan_evidence_tests_validates_max_nodes(tools_fixture):
    plan_result = tools_fixture.gs_plan_evidence_tests(
        tools_fixture.connection_id,
        'yourself',
        max_nodes=0,
    )
    assert not plan_result['ok']
    assert plan_result['error']['message'] == (
        'max_nodes must be greater than zero.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_collect_sender_evidence_validates_test_method_dependency(
    tools_fixture,
):
    collect_result = tools_fixture.gs_collect_sender_evidence(
        tools_fixture.connection_id,
        'yourself',
        test_method_selector='testExample',
    )
    assert not collect_result['ok']
    assert collect_result['error']['message'] == (
        'test_case_class_name is required when test_method_selector is provided.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_apply_selector_rename_validates_evidence_flag(tools_fixture):
    rename_result = tools_fixture.gs_apply_selector_rename(
        tools_fixture.connection_id,
        'oldSelector',
        'newSelector',
        require_observed_sender_evidence='true',
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'require_observed_sender_evidence must be a boolean.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_apply_selector_rename_requires_evidence_run_id_when_requested(
    tools_fixture,
):
    rename_result = tools_fixture.gs_apply_selector_rename(
        tools_fixture.connection_id,
        'oldSelector',
        'newSelector',
        require_observed_sender_evidence=True,
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'evidence_run_id is required when require_observed_sender_evidence is true.'
    )


@with_fixtures(AllowedToolsWithActiveTransactionFixture)
def test_gs_tracer_enable_validates_force_flag(tools_fixture):
    tracer_enable_result = tools_fixture.gs_tracer_enable(
        tools_fixture.connection_id,
        force='true',
    )
    assert not tracer_enable_result['ok']
    assert tracer_enable_result['error']['message'] == 'force must be a boolean.'


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_gs_tracer_write_tools_require_active_transaction(tools_fixture):
    tracer_install_result = tools_fixture.gs_tracer_install(
        tools_fixture.connection_id
    )
    assert not tracer_install_result['ok']
    assert tracer_install_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_enable_result = tools_fixture.gs_tracer_enable(
        tools_fixture.connection_id
    )
    assert not tracer_enable_result['ok']
    assert tracer_enable_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_disable_result = tools_fixture.gs_tracer_disable(
        tools_fixture.connection_id
    )
    assert not tracer_disable_result['ok']
    assert tracer_disable_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_uninstall_result = tools_fixture.gs_tracer_uninstall(
        tools_fixture.connection_id
    )
    assert not tracer_uninstall_result['ok']
    assert tracer_uninstall_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_trace_selector_result = tools_fixture.gs_tracer_trace_selector(
        tools_fixture.connection_id,
        'yourself',
    )
    assert not tracer_trace_selector_result['ok']
    assert tracer_trace_selector_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_untrace_selector_result = tools_fixture.gs_tracer_untrace_selector(
        tools_fixture.connection_id,
        'yourself',
    )
    assert not tracer_untrace_selector_result['ok']
    assert tracer_untrace_selector_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    tracer_clear_observed_senders_result = (
        tools_fixture.gs_tracer_clear_observed_senders(
            tools_fixture.connection_id
        )
    )
    assert not tracer_clear_observed_senders_result['ok']
    assert tracer_clear_observed_senders_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )
    collect_result = tools_fixture.gs_collect_sender_evidence(
        tools_fixture.connection_id,
        'yourself',
    )
    assert not collect_result['ok']
    assert collect_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_create_class(
    tools_fixture,
):
    create_result = tools_fixture.gs_create_class(
        tools_fixture.connection_id,
        'ExampleClass',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_create_package(
    tools_fixture,
):
    create_result = tools_fixture.gs_create_package(
        tools_fixture.connection_id,
        'ExamplePackage',
    )
    assert not create_result['ok']
    assert create_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_install_package(
    tools_fixture,
):
    install_result = tools_fixture.gs_install_package(
        tools_fixture.connection_id,
        'ExamplePackage',
    )
    assert not install_result['ok']
    assert install_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_global_set(tools_fixture):
    set_result = tools_fixture.gs_global_set(
        tools_fixture.connection_id,
        'EXAMPLE_GLOBAL',
        1,
    )
    assert not set_result['ok']
    assert set_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_selector_rename(
    tools_fixture,
):
    rename_result = tools_fixture.gs_apply_selector_rename(
        tools_fixture.connection_id,
        'oldSelector',
        'newSelector',
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_method_rename(
    tools_fixture,
):
    rename_result = tools_fixture.gs_apply_rename_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector',
        'newSelector',
        True,
    )
    assert not rename_result['ok']
    assert rename_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_method_move(
    tools_fixture,
):
    move_result = tools_fixture.gs_apply_move_method(
        tools_fixture.connection_id,
        'SourceClass',
        'someSelector',
        'TargetClass',
    )
    assert not move_result['ok']
    assert move_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_add_parameter(
    tools_fixture,
):
    add_result = tools_fixture.gs_apply_add_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:',
        'timeout:',
        'timeout',
        '30',
        True,
    )
    assert not add_result['ok']
    assert add_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_remove_parameter(
    tools_fixture,
):
    remove_result = tools_fixture.gs_apply_remove_parameter(
        tools_fixture.connection_id,
        'ExampleClass',
        'oldSelector:with:timeout:',
        'timeout:',
        True,
    )
    assert not remove_result['ok']
    assert remove_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_extract_method(
    tools_fixture,
):
    extract_result = tools_fixture.gs_apply_extract_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'exampleMethod',
        'extractedLogic',
        [1],
        True,
    )
    assert not extract_result['ok']
    assert extract_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


@with_fixtures(AllowedToolsWithNoActiveTransactionFixture)
def test_write_tools_require_active_transaction_for_inline_method(
    tools_fixture,
):
    inline_result = tools_fixture.gs_apply_inline_method(
        tools_fixture.connection_id,
        'ExampleClass',
        'callerSelector',
        'inlineSelector',
        True,
    )
    assert not inline_result['ok']
    assert inline_result['error']['message'] == (
        'No active transaction. '
        'Call gs_begin before write operations.'
    )


def test_gs_connect_attaches_to_active_ide_session():
    registrar = McpToolRegistrar()
    shared_state = IntegratedSessionState()
    shared_state.attach_ide_session(FakeGemstoneSession())
    register_tools(
        registrar,
        allow_eval=True,
        allow_compile=True,
        allow_commit=True,
        allow_tracing=True,
        integrated_session_state=shared_state,
    )
    connect_result = registrar.registered_tools_by_name['gs_connect'](
        'linked',
        '',
        '',
    )
    assert connect_result['ok'], connect_result
    assert connect_result['connection_mode'] == 'ide_attached'
    assert connect_result['connection_id'] == shared_state.ide_connection_id()
    capabilities_result = registrar.registered_tools_by_name['gs_capabilities']()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['gui_session_active']
    assert not capabilities_result['policy']['mcp_can_connect_sessions']
    assert not capabilities_result['policy']['mcp_can_disconnect_sessions']


def test_gs_connect_is_blocked_when_gui_is_active_without_login():
    registrar = McpToolRegistrar()
    shared_state = IntegratedSessionState()
    shared_state.attach_ide_gui()
    register_tools(
        registrar,
        allow_eval=True,
        allow_compile=True,
        allow_commit=True,
        allow_tracing=True,
        integrated_session_state=shared_state,
    )
    connect_result = registrar.registered_tools_by_name['gs_connect'](
        'linked',
        '',
        '',
    )
    assert not connect_result['ok']
    assert connect_result['error']['message'] == (
        'gs_connect is disabled while the IDE is active without a logged-in '
        'session. Log in from the IDE first, then attach using gs_connect.'
    )
    capabilities_result = registrar.registered_tools_by_name['gs_capabilities']()
    assert capabilities_result['ok'], capabilities_result
    assert capabilities_result['policy']['gui_session_active']
    assert not capabilities_result['policy']['mcp_can_connect_sessions']
    assert not capabilities_result['policy']['mcp_can_disconnect_sessions']


def test_gs_disconnect_is_blocked_for_ide_owned_session():
    registrar = McpToolRegistrar()
    shared_state = IntegratedSessionState()
    shared_state.attach_ide_session(FakeGemstoneSession())
    register_tools(
        registrar,
        allow_eval=True,
        allow_compile=True,
        allow_commit=True,
        allow_tracing=True,
        integrated_session_state=shared_state,
    )
    disconnect_result = registrar.registered_tools_by_name['gs_disconnect'](
        shared_state.ide_connection_id()
    )
    assert not disconnect_result['ok']
    assert disconnect_result['error']['message'] == (
        'gs_disconnect is disabled while the IDE owns the active session.'
    )


def test_gs_commit_is_disabled_by_default_when_ide_owns_session():
    registrar = McpToolRegistrar()
    shared_state = IntegratedSessionState()
    shared_state.attach_ide_session(FakeGemstoneSession())
    register_tools(
        registrar,
        allow_eval=True,
        allow_compile=True,
        allow_commit=True,
        allow_tracing=True,
        integrated_session_state=shared_state,
    )
    commit_result = registrar.registered_tools_by_name['gs_commit'](
        shared_state.ide_connection_id(),
        approved_by_user=True,
        approval_note='User explicitly approved this commit.',
    )
    assert not commit_result['ok']
    assert commit_result['error']['message'] == (
        'gs_commit is disabled while the IDE owns the session. '
        'Use the IDE commit action or start swordfish --headless-mcp with '
        '--allow-mcp-commit-when-gui.'
    )


def test_gs_commit_can_be_enabled_when_ide_owns_session():
    registrar = McpToolRegistrar()
    shared_state = IntegratedSessionState()
    fake_session = FakeGemstoneSession()
    shared_state.attach_ide_session(fake_session)
    register_tools(
        registrar,
        allow_eval=True,
        allow_compile=True,
        allow_commit=True,
        allow_commit_when_gui=True,
        allow_tracing=True,
        integrated_session_state=shared_state,
    )
    commit_result = registrar.registered_tools_by_name['gs_commit'](
        shared_state.ide_connection_id(),
        approved_by_user=True,
        approval_note='User explicitly approved this commit.',
    )
    assert commit_result['ok'], commit_result
    assert fake_session.commit_count == 1
