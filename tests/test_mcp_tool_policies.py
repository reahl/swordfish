from reahl.tofu import Fixture
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import with_fixtures

from reahl.swordfish.mcp.session_registry import add_connection
from reahl.swordfish.mcp.session_registry import clear_connections
from reahl.swordfish.mcp.tools import register_tools


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

    def new_gs_create_class(self):
        return self.registered_mcp_tools['gs_create_class']

    def new_gs_global_set(self):
        return self.registered_mcp_tools['gs_global_set']

    def new_gs_apply_selector_rename(self):
        return self.registered_mcp_tools['gs_apply_selector_rename']

    def new_gs_find_implementors(self):
        return self.registered_mcp_tools['gs_find_implementors']

    def new_gs_find_senders(self):
        return self.registered_mcp_tools['gs_find_senders']

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
        'Start swordfish-mcp with --allow-eval to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_commit_is_disabled_by_default(tools_fixture):
    commit_result = tools_fixture.gs_commit('missing-connection-id')
    assert not commit_result['ok']
    assert commit_result['error']['message'] == (
        'gs_commit is disabled. '
        'Start swordfish-mcp with --allow-commit to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_capabilities_reports_restricted_policy_flags(tools_fixture):
    capabilities_result = tools_fixture.gs_capabilities()
    assert capabilities_result['ok'], capabilities_result
    policy = capabilities_result['policy']
    assert policy['allow_eval'] is False
    assert policy['allow_compile'] is False
    assert policy['allow_commit'] is False
    assert policy['allow_tracing'] is False
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
    assert policy['allow_compile'] is True
    assert policy['allow_commit'] is True
    assert policy['allow_tracing'] is True


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


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_install_is_disabled_by_default(tools_fixture):
    tracer_install_result = tools_fixture.gs_tracer_install(
        'missing-connection-id'
    )
    assert not tracer_install_result['ok']
    assert tracer_install_result['error']['message'] == (
        'gs_tracer_install is disabled. '
        'Start swordfish-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_enable_is_disabled_by_default(tools_fixture):
    tracer_enable_result = tools_fixture.gs_tracer_enable(
        'missing-connection-id'
    )
    assert not tracer_enable_result['ok']
    assert tracer_enable_result['error']['message'] == (
        'gs_tracer_enable is disabled. '
        'Start swordfish-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_disable_is_disabled_by_default(tools_fixture):
    tracer_disable_result = tools_fixture.gs_tracer_disable(
        'missing-connection-id'
    )
    assert not tracer_disable_result['ok']
    assert tracer_disable_result['error']['message'] == (
        'gs_tracer_disable is disabled. '
        'Start swordfish-mcp with --allow-compile to enable.'
    )


@with_fixtures(RestrictedToolsFixture)
def test_gs_tracer_uninstall_is_disabled_by_default(tools_fixture):
    tracer_uninstall_result = tools_fixture.gs_tracer_uninstall(
        'missing-connection-id'
    )
    assert not tracer_uninstall_result['ok']
    assert tracer_uninstall_result['error']['message'] == (
        'gs_tracer_uninstall is disabled. '
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-tracing to enable.'
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
        'Start swordfish-mcp with --allow-tracing to enable.'
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
        'Start swordfish-mcp with --allow-tracing to enable.'
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
        'Start swordfish-mcp with --allow-tracing to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-compile to enable.'
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
        'Start swordfish-mcp with --allow-eval to enable.'
    )


@with_fixtures(AllowedToolsFixture)
def test_gs_eval_requires_unsafe_flag_when_allowed(tools_fixture):
    eval_result = tools_fixture.gs_eval('missing-connection-id', '3 + 4')
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
    )
    assert not eval_result['ok']
    assert eval_result['error']['message'] == 'Unknown connection_id.'


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
    commit_result = tools_fixture.gs_commit('missing-connection-id')
    assert not commit_result['ok']
    assert commit_result['error']['message'] == 'Unknown connection_id.'


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
