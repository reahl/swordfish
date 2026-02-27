import functools
import re
import time
import uuid

from reahl.ptongue import GemstoneApiError
from reahl.ptongue import GemstoneError

from reahl.swordfish.gemstone import abort_transaction
from reahl.swordfish.gemstone import begin_transaction
from reahl.swordfish.gemstone import commit_transaction
from reahl.swordfish.gemstone import DomainException
from reahl.swordfish.gemstone import GemstoneBrowserSession
from reahl.swordfish.gemstone import GemstoneDebugSession
from reahl.swordfish.gemstone import close_session
from reahl.swordfish.gemstone import create_linked_session
from reahl.swordfish.gemstone import create_rpc_session
from reahl.swordfish.gemstone import gemstone_error_payload
from reahl.swordfish.gemstone import session_summary
from reahl.swordfish.mcp.debug_registry import add_debug_session
from reahl.swordfish.mcp.debug_registry import get_debug_metadata
from reahl.swordfish.mcp.debug_registry import get_debug_session
from reahl.swordfish.mcp.debug_registry import has_debug_session
from reahl.swordfish.mcp.debug_registry import remove_debug_session
from reahl.swordfish.mcp.debug_registry import remove_debug_sessions_for_connection
from reahl.swordfish.mcp.session_registry import add_connection
from reahl.swordfish.mcp.session_registry import get_metadata
from reahl.swordfish.mcp.session_registry import get_session
from reahl.swordfish.mcp.session_registry import has_connection
from reahl.swordfish.mcp.session_registry import remove_connection
from reahl.swordfish.mcp.integration_state import IntegratedSessionState
from reahl.swordfish.mcp.ast_assets import ast_support_source
from reahl.swordfish.mcp.ast_assets import ast_support_source_hash
from reahl.swordfish.mcp.ast_assets import AST_SUPPORT_VERSION
from reahl.swordfish.mcp.tracer_assets import tracer_source
from reahl.swordfish.mcp.tracer_assets import tracer_source_hash
from reahl.swordfish.mcp.tracer_assets import TRACER_VERSION


def register_tools(
    mcp_server,
    allow_eval=False,
    allow_compile=False,
    allow_commit=False,
    allow_tracing=False,
    allow_commit_when_gui=False,
    integrated_session_state=None,
    require_gemstone_ast=False,
):
    if not isinstance(allow_commit_when_gui, bool):
        raise ValueError('allow_commit_when_gui must be a boolean.')
    if integrated_session_state is None:
        integrated_session_state = IntegratedSessionState()

    identifier_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    unary_selector_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    keyword_selector_pattern = re.compile('^([A-Za-z][A-Za-z0-9_]*:)+$')
    keyword_token_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*:$')
    tracer_alias_selector_prefix = 'swordfishMcpTracerOriginal__'
    collected_sender_evidence = {}
    planned_sender_tests = {}

    def tool_name_writes_model(tool_name):
        if tool_name in {
            'gs_begin',
            'gs_begin_if_needed',
            'gs_commit',
            'gs_abort',
            'gs_eval',
            'gs_debug_eval',
            'gs_set_method_category',
            'gs_delete_method',
            'gs_delete_class',
            'gs_global_set',
            'gs_global_remove',
            'gs_ast_install',
            'gs_tracer_install',
            'gs_tracer_uninstall',
            'gs_tracer_enable',
            'gs_tracer_disable',
            'gs_tracer_trace_selector',
            'gs_tracer_untrace_selector',
            'gs_tracer_clear_observed_senders',
        }:
            return True
        for write_prefix in (
            'gs_create_',
            'gs_install_',
            'gs_compile_',
            'gs_apply_',
        ):
            if tool_name.startswith(write_prefix):
                return True
        return False

    def should_refresh_model(tool_name, tool_result):
        if not isinstance(tool_result, dict):
            return False
        if not tool_result.get('ok'):
            return False
        return tool_name_writes_model(tool_name)

    original_tool_decorator_factory = mcp_server.tool

    def coordinated_tool_decorator_factory(*decorator_arguments, **decorator_keywords):
        tool_decorator = original_tool_decorator_factory(
            *decorator_arguments,
            **decorator_keywords,
        )

        def coordinated_tool_decorator(function):
            @functools.wraps(function)
            def coordinated_tool(*function_arguments, **function_keywords):
                integrated_session_state.begin_mcp_operation(function.__name__)
                try:
                    tool_result = function(*function_arguments, **function_keywords)
                    if should_refresh_model(function.__name__, tool_result):
                        integrated_session_state.request_model_refresh(
                            'transaction'
                        )
                    return tool_result
                finally:
                    integrated_session_state.end_mcp_operation()

            return tool_decorator(coordinated_tool)

        return coordinated_tool_decorator

    try:
        mcp_server.tool = coordinated_tool_decorator_factory
    except AttributeError:
        pass

    def gui_session_is_active():
        return integrated_session_state.is_ide_gui_active()

    def metadata_for_connection_id(connection_id):
        if integrated_session_state.is_ide_connection_id(connection_id):
            metadata = integrated_session_state.ide_metadata_for_mcp()
            if metadata is None:
                return None
            return metadata
        if not has_connection(connection_id):
            return None
        return get_metadata(connection_id)

    def get_active_session(connection_id):
        if integrated_session_state.is_ide_connection_id(connection_id):
            gemstone_session = integrated_session_state.ide_session_for_mcp()
            if gemstone_session is None:
                return None, {
                    'ok': False,
                    'error': {
                        'message': 'Unknown connection_id.',
                    },
                }
            return gemstone_session, None
        if not has_connection(connection_id):
            return None, {
                'ok': False,
                'error': {
                    'message': 'Unknown connection_id.',
                },
            }
        return get_session(connection_id), None

    def require_active_transaction(connection_id):
        metadata = metadata_for_connection_id(connection_id)
        if metadata is None:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {
                    'message': 'Unknown connection_id.',
                },
            }
        if metadata.get('transaction_active'):
            return None
        return {
            'ok': False,
            'connection_id': connection_id,
            'error': {
                'message': (
                    'No active transaction. '
                    'Call gs_begin before write operations.'
                ),
            },
        }

    def get_browser_session(connection_id):
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return None, error_response
        return browser_session_for_policy(gemstone_session), None

    def browser_session_for_policy(gemstone_session):
        return GemstoneBrowserSession(
            gemstone_session,
            require_gemstone_ast=require_gemstone_ast,
        )

    def get_active_debug_session(connection_id, debug_id):
        if not has_debug_session(debug_id):
            return None, {
                'ok': False,
                'connection_id': connection_id,
                'debug_id': debug_id,
                'error': {'message': 'Unknown debug_id.'},
            }
        debug_metadata = get_debug_metadata(debug_id)
        if debug_metadata['connection_id'] != connection_id:
            return None, {
                'ok': False,
                'connection_id': connection_id,
                'debug_id': debug_id,
                'error': {
                    'message': 'debug_id is not associated with connection_id.'
                },
            }
        return get_debug_session(debug_id), None

    def disabled_tool_response(connection_id, message):
        return {
            'ok': False,
            'connection_id': connection_id,
            'error': {'message': message},
        }

    def tracing_disabled_tool_response(connection_id, tool_name):
        return disabled_tool_response(
            connection_id,
            (
                '%s is disabled. '
                'Start swordfish --mode mcp-headless with --allow-tracing to enable.'
            )
            % tool_name,
        )

    def require_tracing_enabled(connection_id, tool_name):
        if allow_tracing:
            return None
        return tracing_disabled_tool_response(connection_id, tool_name)

    def approval_required_tool_response(
        connection_id,
        tool_name,
        action_name,
        approval_mode='explicit_confirmation',
        resolution_hint='',
    ):
        message = '%s requires human approval for %s.' % (
            tool_name,
            action_name,
        )
        message = (
            message
            + ' Retry with approved_by_user=true and '
            + 'a non-empty approval_note.'
        )
        retry_arguments = {
            'approved_by_user': True,
            'approval_note': '<human-approval-note>',
        }
        if resolution_hint:
            message = message + ' ' + resolution_hint
        response = disabled_tool_response(
            connection_id,
            message,
        )
        response['error']['approval'] = {
            'required': True,
            'tool_name': tool_name,
            'action_name': action_name,
            'mode': approval_mode,
            'retry_arguments': retry_arguments,
        }
        return response

    def require_explicit_user_confirmation(
        connection_id,
        tool_name,
        action_name,
        approved_by_user,
        approval_note,
    ):
        try:
            approved_by_user = validated_boolean_like(
                approved_by_user,
                'approved_by_user',
            )
        except DomainException as error:
            return disabled_tool_response(connection_id, str(error))
        if not approved_by_user:
            return approval_required_tool_response(
                connection_id,
                tool_name,
                action_name,
            )
        try:
            validated_non_empty_string_stripped(
                approval_note,
                'approval_note',
            )
        except DomainException as error:
            return disabled_tool_response(connection_id, str(error))
        return None

    def validated_identifier(input_value, argument_name):
        if not isinstance(input_value, str):
            raise DomainException('%s must be a string.' % argument_name)
        if not input_value:
            raise DomainException('%s cannot be empty.' % argument_name)
        if not identifier_pattern.match(input_value):
            raise DomainException(
                (
                    '%s must contain only letters, digits, and underscores '
                    'and start with a letter.'
                )
                % argument_name
            )
        return input_value

    def validated_identifier_names(input_values, argument_name):
        if input_values is None:
            return []
        if not isinstance(input_values, list):
            raise DomainException('%s must be a list of strings.' % argument_name)
        validated_values = []
        for index, input_value in enumerate(input_values):
            validated_values.append(
                validated_identifier(
                    input_value,
                    '%s[%s]' % (argument_name, index),
                )
            )
        return validated_values

    def validated_non_empty_string(input_value, argument_name):
        if not isinstance(input_value, str):
            raise DomainException('%s must be a string.' % argument_name)
        if not input_value:
            raise DomainException('%s cannot be empty.' % argument_name)
        return input_value

    def validated_non_empty_string_stripped(input_value, argument_name):
        normalized_input_value = validated_non_empty_string(
            input_value,
            argument_name,
        ).strip()
        if not normalized_input_value:
            raise DomainException('%s cannot be blank.' % argument_name)
        return normalized_input_value

    def validated_optional_package_name(package_name):
        if package_name is None:
            return ''
        if not isinstance(package_name, str):
            raise DomainException('package_name must be a string.')
        return package_name.strip()

    def validated_existing_package_name(browser_session, package_name):
        package_name = validated_non_empty_string_stripped(
            package_name,
            'package_name',
        )
        if not browser_session.package_exists(package_name):
            raise DomainException(
                (
                    'Unknown package_name. '
                    'Create/install package first.'
                )
            )
        return package_name

    def resolved_class_creation_target(
        browser_session,
        in_dictionary,
        package_name,
    ):
        in_dictionary = validated_non_empty_string_stripped(
            in_dictionary,
            'in_dictionary',
        )
        package_name = validated_optional_package_name(package_name)
        if package_name:
            package_name = validated_existing_package_name(
                browser_session,
                package_name,
            )
            if (
                in_dictionary != 'UserGlobals'
                and in_dictionary != package_name
            ):
                raise DomainException(
                    (
                        'Provide either in_dictionary or package_name, '
                        'not both with different values.'
                    )
                )
            return package_name, package_name
        return in_dictionary, None

    def validated_non_negative_integer_or_none(input_value, argument_name):
        if input_value is None:
            return None
        if not isinstance(input_value, int):
            raise DomainException('%s must be an integer or None.' % argument_name)
        if input_value < 0:
            raise DomainException('%s cannot be negative.' % argument_name)
        return input_value

    def validated_positive_integer(input_value, argument_name):
        if not isinstance(input_value, int):
            raise DomainException('%s must be an integer.' % argument_name)
        if input_value <= 0:
            raise DomainException('%s must be greater than zero.' % argument_name)
        return input_value

    def validated_boolean(input_value, argument_name):
        if not isinstance(input_value, bool):
            raise DomainException('%s must be a boolean.' % argument_name)
        return input_value

    def validated_boolean_like(input_value, argument_name):
        if isinstance(input_value, bool):
            return input_value
        if isinstance(input_value, str):
            normalized_input_value = input_value.strip().lower()
            if normalized_input_value == 'true':
                return True
            if normalized_input_value == 'false':
                return False
        raise DomainException('%s must be a boolean.' % argument_name)

    def current_eval_mode():
        if not allow_eval:
            return 'disabled'
        return 'approval_required'

    def commit_allowed_for_current_mode():
        if not allow_commit:
            return False
        if gui_session_is_active() and not allow_commit_when_gui:
            return False
        return True

    def current_commit_approval_mode():
        if not commit_allowed_for_current_mode():
            return 'disabled'
        return 'explicit_confirmation'

    def policy_flags():
        gui_active = gui_session_is_active()
        return {
            'allow_eval': allow_eval,
            'allow_eval_write': False,
            'allow_compile': allow_compile,
            'allow_commit': commit_allowed_for_current_mode(),
            'allow_tracing': allow_tracing,
            'require_gemstone_ast': require_gemstone_ast,
            'gui_session_active': gui_active,
            'gui_controls_session': gui_active,
            'mcp_can_connect_sessions': not gui_active,
            'mcp_can_disconnect_sessions': not gui_active,
            'mcp_commit_allowed_when_gui': allow_commit_when_gui,
            'eval_mode': current_eval_mode(),
            'commit_approval_mode': current_commit_approval_mode(),
            'eval_requires_unsafe': True,
            'eval_requires_human_approval': allow_eval,
            'commit_requires_human_approval': commit_allowed_for_current_mode(),
            'writes_require_active_transaction': True,
        }

    def source_code_character_map_for_eval(source):
        code_character_map = [True for _ in source]
        index = 0
        state = 'code'
        while index < len(source):
            character = source[index]
            if state == 'code':
                if character == "'":
                    code_character_map[index] = False
                    state = 'string'
                elif character == '"':
                    code_character_map[index] = False
                    state = 'comment'
            elif state == 'string':
                code_character_map[index] = False
                if character == "'":
                    has_escaped_quote = (
                        index + 1 < len(source)
                        and source[index + 1] == "'"
                    )
                    if has_escaped_quote:
                        code_character_map[index + 1] = False
                        index = index + 1
                    else:
                        state = 'code'
            elif state == 'comment':
                code_character_map[index] = False
                if character == '"':
                    state = 'code'
            index = index + 1
        return code_character_map

    def code_only_source_for_eval(source):
        code_character_map = source_code_character_map_for_eval(source)
        fragments = []
        for index in range(len(source)):
            fragments.append(source[index] if code_character_map[index] else ' ')
        return ''.join(fragments)

    def write_reason_for_eval_source(source):
        code_only_source = code_only_source_for_eval(source)
        if re.search(
            r'\bSystem\s+(commit|abort|abortTransaction|begin|beginTransaction)\b',
            code_only_source,
        ):
            return 'transaction_control'
        if re.search(
            r'\b(commit|abort|abortTransaction|begin|beginTransaction)\b',
            code_only_source,
        ):
            return 'transaction_control'
        if re.search(
            r'\b(compileMethod:|compile:|subclass:)\b',
            code_only_source,
        ):
            return 'code_definition'
        if re.search(
            r'\b(removeSelector:|removeClass:|deleteClass)\b',
            code_only_source,
        ):
            return 'code_removal'
        if re.search(
            r'\bat:\s*[^.;\n]*\bput:',
            code_only_source,
        ):
            return 'global_mutation'
        if re.search(
            r'\b(category:|classify:)\b',
            code_only_source,
        ):
            return 'method_category_mutation'
        return None

    def transaction_state_effect_for_eval_source(source):
        code_only_source = code_only_source_for_eval(source)
        if re.search(
            r'\b(System\s+)?(commit|abort|abortTransaction)\b',
            code_only_source,
        ):
            return 'inactive'
        if re.search(
            r'\b(System\s+)?(begin|beginTransaction)\b',
            code_only_source,
        ):
            return 'active'
        return 'unknown'

    def guidance_intents():
        return [
            'general',
            'navigation',
            'sender_analysis',
            'refactor',
            'runtime_evidence',
        ]

    def guidance_for_intent(intent, selector, change_kind=None):
        selector_is_common_hotspot = selector in {
            'ifTrue:',
            'ifFalse:',
            'ifTrue:ifFalse:',
            'value',
            'default',
            'yourself',
        }
        decision_rules = [
            {
                'when': 'You can use an explicit gs_* tool.',
                'prefer_tools': ['gs_* explicit tool'],
                'avoid_tools': ['gs_eval'],
                'reason': (
                    'Explicit tools are safer, easier to validate, '
                    'and less likely to produce ambiguous failures.'
                ),
            },
            {
                'when': 'You are changing code.',
                'prefer_tools': ['gs_begin', 'write tool', 'gs_commit or gs_abort'],
                'avoid_tools': ['implicit transaction assumptions'],
                'reason': 'Write operations require explicit transaction flow.',
            },
        ]
        cautions = []
        workflow = []
        if allow_eval:
            decision_rules.append(
                {
                    'when': 'You are using gs_eval or gs_debug_eval.',
                    'prefer_tools': [
                        'human-approved eval bypass for motivated cases only'
                    ],
                    'avoid_tools': ['routine writes via gs_eval'],
                    'reason': (
                        'Eval is powerful and should be exceptional. '
                        'Use structured tools first; use eval bypass only when '
                        'a human explicitly approves and the reason is clear.'
                    ),
                }
            )
            cautions.append(
                (
                    'gs_eval and gs_debug_eval require approved_by_user=true '
                    'with a non-empty approval_note and reason. '
                    'Prefer structured tools for routine work.'
                )
            )
        if commit_allowed_for_current_mode():
            cautions.append(
                (
                    'gs_commit requires explicit confirmation: '
                    'approved_by_user=true and non-empty approval_note.'
                )
            )
        elif allow_commit and gui_session_is_active():
            cautions.append(
                (
                    'gs_commit is disabled while the IDE owns the active '
                    'session unless the server is started with '
                    '--allow-mcp-commit-when-gui.'
                )
            )
        if intent == 'general':
            workflow = [
                {
                    'step': 1,
                    'action': 'Inspect server capabilities and policy switches.',
                    'tools': ['gs_capabilities'],
                },
                {
                    'step': 2,
                    'action': 'Load workflow guidance for your task.',
                    'tools': ['gs_guidance'],
                },
                {
                    'step': 3,
                    'action': 'Verify AST support status when strict AST mode is on.',
                    'tools': ['gs_ast_status', 'gs_ast_install'],
                },
                {
                    'step': 4,
                    'action': 'Connect and check transaction state.',
                    'tools': ['gs_connect', 'gs_transaction_status'],
                },
                {
                    'step': 5,
                    'action': 'For new module scaffolding, use explicit package tools.',
                    'tools': [
                        'gs_create_package',
                        'gs_install_package',
                        'gs_create_class_in_package',
                        'gs_create_test_case_class_in_package',
                    ],
                },
            ]
        if intent == 'navigation':
            workflow = [
                {
                    'step': 1,
                    'action': 'Find candidate classes/selectors.',
                    'tools': ['gs_find_classes', 'gs_find_selectors'],
                },
                {
                    'step': 2,
                    'action': 'Find implementors and static senders.',
                    'tools': ['gs_find_implementors', 'gs_find_senders'],
                },
                {
                    'step': 3,
                    'action': 'Inspect source for shortlisted methods.',
                    'tools': [
                        'gs_get_method_source',
                        'gs_method_ast',
                        'gs_method_sends',
                        'gs_method_structure_summary',
                        'gs_method_control_flow_summary',
                        'gs_query_methods_by_ast_pattern',
                    ],
                },
            ]
        if intent == 'sender_analysis':
            workflow = [
                {
                    'step': 1,
                    'action': 'Start with static senders.',
                    'tools': ['gs_find_senders'],
                },
                {
                    'step': 2,
                    'action': 'If sender set is broad, build candidate tests.',
                    'tools': ['gs_plan_evidence_tests'],
                },
                {
                    'step': 3,
                    'action': 'Collect runtime sender evidence from tests.',
                    'tools': ['gs_collect_sender_evidence'],
                },
            ]
        if intent == 'refactor':
            preview_tools = ['gs_preview_selector_rename']
            apply_tools = ['gs_apply_selector_rename']
            if change_kind == 'rename_method':
                preview_tools = ['gs_preview_rename_method']
                apply_tools = ['gs_apply_rename_method']
            if change_kind == 'move_method':
                preview_tools = ['gs_preview_move_method']
                apply_tools = ['gs_apply_move_method']
            if change_kind == 'add_parameter':
                preview_tools = ['gs_preview_add_parameter']
                apply_tools = ['gs_apply_add_parameter']
            if change_kind == 'remove_parameter':
                preview_tools = ['gs_preview_remove_parameter']
                apply_tools = ['gs_apply_remove_parameter']
            if change_kind == 'extract_method':
                preview_tools = ['gs_preview_extract_method']
                apply_tools = ['gs_apply_extract_method']
            if change_kind == 'inline_method':
                preview_tools = ['gs_preview_inline_method']
                apply_tools = ['gs_apply_inline_method']
            if change_kind is None:
                preview_tools = [
                    'gs_preview_selector_rename',
                    'gs_preview_rename_method',
                    'gs_preview_move_method',
                    'gs_preview_add_parameter',
                    'gs_preview_remove_parameter',
                    'gs_preview_extract_method',
                    'gs_preview_inline_method',
                ]
                apply_tools = [
                    'gs_apply_selector_rename',
                    'gs_apply_rename_method',
                    'gs_apply_move_method',
                    'gs_apply_add_parameter',
                    'gs_apply_remove_parameter',
                    'gs_apply_extract_method',
                    'gs_apply_inline_method',
                ]
            workflow = [
                {
                    'step': 1,
                    'action': 'Preview refactor impact before changing code.',
                    'tools': preview_tools,
                },
                {
                    'step': 2,
                    'action': 'Collect evidence for ambiguous selectors.',
                    'tools': [
                        'gs_find_senders',
                        'gs_plan_evidence_tests',
                        'gs_collect_sender_evidence',
                    ],
                },
                {
                    'step': 3,
                    'action': 'Apply change, then run tests.',
                    'tools': apply_tools + [
                        'gs_run_gemstone_tests',
                        'gs_run_tests_in_package',
                        'gs_run_test_method',
                    ],
                },
            ]
            if change_kind == 'remove_parameter':
                decision_rules.append(
                    {
                        'when': 'You remove a parameter and want to reduce wrapper reliance.',
                        'prefer_tools': [
                            'gs_preview_remove_parameter(rewrite_source_senders=true)',
                            'gs_apply_remove_parameter(rewrite_source_senders=true)',
                        ],
                        'avoid_tools': [
                            'leaving all local callers on compatibility wrapper',
                        ],
                        'reason': (
                            'Optional same-class caller rewrites move local senders '
                            'to the new selector while preserving old entrypoint compatibility.'
                        ),
                    }
                )
        if intent == 'runtime_evidence':
            workflow = [
                {
                    'step': 1,
                    'action': 'Install and enable tracer once per image/session.',
                    'tools': [
                        'gs_tracer_install',
                        'gs_tracer_status',
                        'gs_tracer_enable',
                    ],
                },
                {
                    'step': 2,
                    'action': 'Trace a selector and run relevant tests.',
                    'tools': [
                        'gs_tracer_trace_selector',
                        'gs_run_test_method or gs_run_tests_in_package',
                    ],
                },
                {
                    'step': 3,
                    'action': 'Read observed senders and untrace when done.',
                    'tools': [
                        'gs_tracer_find_observed_senders',
                        'gs_tracer_untrace_selector',
                    ],
                },
            ]
        if selector_is_common_hotspot:
            cautions.append(
                (
                    'Selector %s is often high-fanout. '
                    'Static senders may contain many unrelated call sites.'
                )
                % selector
            )
        if selector_is_common_hotspot and not allow_tracing:
            cautions.append(
                (
                    'Runtime evidence tools are disabled. '
                    'Start swordfish --mode mcp-headless with --allow-tracing '
                    'for observed caller evidence.'
                )
            )
        if selector_is_common_hotspot and allow_tracing:
            decision_rules.append(
                {
                    'when': 'Selector fanout is high or ambiguous.',
                    'prefer_tools': [
                        'gs_plan_evidence_tests',
                        'gs_collect_sender_evidence',
                    ],
                    'avoid_tools': ['static sender list as sole proof'],
                    'reason': (
                        'Observed sender evidence narrows the static superset '
                        'to callers actually exercised by tests.'
                    ),
                }
            )
        if require_gemstone_ast:
            cautions.append(
                (
                    'Strict AST mode is active. Install AST support with '
                    'gs_ast_install and verify with gs_ast_status.'
                )
            )
        return {
            'intent': intent,
            'selector': selector,
            'workflow': workflow,
            'decision_rules': decision_rules,
            'cautions': cautions,
        }

    def ast_status_for_browser_session(browser_session):
        expected_source_hash = ast_support_source_hash()
        expected_version = AST_SUPPORT_VERSION
        support_class_exists = browser_session.run_code(
            (
                '| swordfishDictionary |\n'
                'swordfishDictionary := System myUserProfile symbolList '
                'objectNamed: #Swordfish.\n'
                'swordfishDictionary notNil and: [\n'
                '    swordfishDictionary includesKey: #SwordfishMcpAstSupport\n'
                ']'
            )
        ).to_py
        manifest_exists = browser_session.run_code(
            'UserGlobals includesKey: #SwordfishMcpAstManifest'
        ).to_py
        installed_source_hash = ''
        installed_version = ''
        installed_at = ''
        if manifest_exists:
            installed_source_hash = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpAstManifest) '
                    "at: #sourceHash ifAbsent: ['']"
                )
            ).to_py
            installed_version = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpAstManifest) '
                    "at: #version ifAbsent: ['']"
                )
            ).to_py
            installed_at = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpAstManifest) '
                    "at: #installedAt ifAbsent: ['']"
                )
            ).to_py
        hashes_match = manifest_exists and (
            installed_source_hash == expected_source_hash
        )
        versions_match = manifest_exists and (
            installed_version == expected_version
        )
        manifest_matches = hashes_match and versions_match
        return {
            'ast_support_installed': support_class_exists,
            'ast_manifest_installed': manifest_exists,
            'expected_version': expected_version,
            'installed_version': installed_version,
            'versions_match': versions_match,
            'expected_source_hash': expected_source_hash,
            'installed_source_hash': installed_source_hash,
            'hashes_match': hashes_match,
            'manifest_matches': manifest_matches,
            'installed_at': installed_at,
        }

    def ast_manifest_install_script(browser_session):
        expected_source_hash = ast_support_source_hash()
        expected_version = AST_SUPPORT_VERSION
        expected_version_literal = browser_session.smalltalk_string_literal(
            expected_version
        )
        expected_hash_literal = browser_session.smalltalk_string_literal(
            expected_source_hash
        )
        installed_by_literal = browser_session.smalltalk_string_literal(
            'swordfish'
        )
        return (
            '| manifest |\n'
            'manifest := Dictionary new.\n'
            'manifest at: #version put: %s.\n'
            'manifest at: #sourceHash put: %s.\n'
            'manifest at: #installedBy put: %s.\n'
            'manifest at: #installedAt put: DateAndTime now printString.\n'
            'UserGlobals at: #SwordfishMcpAstManifest put: manifest.\n'
            'true'
        ) % (
            expected_version_literal,
            expected_hash_literal,
            installed_by_literal,
        )

    def install_ast_support_in_browser_session(browser_session):
        if not browser_session.package_exists('Swordfish'):
            browser_session.create_and_install_package('Swordfish')
        browser_session.run_code(ast_support_source())
        browser_session.run_code(
            ast_manifest_install_script(browser_session)
        )

    def tracer_status_for_browser_session(browser_session):
        return browser_session.tracer_status()

    def tracer_manifest_install_script(browser_session):
        expected_source_hash = tracer_source_hash()
        expected_version = TRACER_VERSION
        expected_version_literal = browser_session.smalltalk_string_literal(
            expected_version
        )
        expected_hash_literal = browser_session.smalltalk_string_literal(
            expected_source_hash
        )
        installed_by_literal = browser_session.smalltalk_string_literal(
            'swordfish'
        )
        return (
            '| manifest |\n'
            'manifest := Dictionary new.\n'
            'manifest at: #version put: %s.\n'
            'manifest at: #sourceHash put: %s.\n'
            'manifest at: #installedBy put: %s.\n'
            'manifest at: #installedAt put: DateAndTime now printString.\n'
            'UserGlobals at: #SwordfishMcpTracerManifest put: manifest.\n'
            'UserGlobals at: #SwordfishMcpTracerEnabled put: false.\n'
            'true'
        ) % (
            expected_version_literal,
            expected_hash_literal,
            installed_by_literal,
        )

    def tracer_alias_selector(method_name):
        return tracer_alias_selector_prefix + method_name

    def selector_tokens_for_browser_session(browser_session, method_name):
        return (
            browser_session.selector_keyword_tokens(method_name)
            if ':' in method_name
            else [method_name]
        )

    def source_with_rewritten_method_header(
        browser_session,
        source,
        old_selector,
        new_selector,
    ):
        old_tokens = selector_tokens_for_browser_session(
            browser_session,
            old_selector,
        )
        new_tokens = selector_tokens_for_browser_session(
            browser_session,
            new_selector,
        )
        if len(old_tokens) != len(new_tokens):
            raise DomainException(
                'old_selector and new_selector must have the same arity.'
            )
        selector_token_ranges = browser_session.selector_token_ranges_in_source(
            source,
            old_tokens,
        )
        if not selector_token_ranges:
            raise DomainException(
                'Could not locate selector tokens in method source.'
            )
        replacement_plan = (
            browser_session.replacement_plan_for_selector_tokens(
                [selector_token_ranges[0]],
                new_tokens,
            )
        )
        return browser_session.source_with_replaced_selector_tokens(
            source,
            replacement_plan,
        )

    def tracer_sender_wrapper_source(
        browser_session,
        sender_method_selector,
        alias_selector,
        target_method_name,
        caller_class_name,
        caller_show_instance_side,
    ):
        target_selector_literal = browser_session.selector_reference_expression(
            target_method_name
        )
        caller_class_name_literal = browser_session.smalltalk_string_literal(
            caller_class_name
        )
        caller_method_selector_literal = (
            browser_session.selector_reference_expression(sender_method_selector)
        )
        caller_show_instance_side_literal = (
            'true' if caller_show_instance_side else 'false'
        )
        if ':' in sender_method_selector:
            method_tokens = browser_session.selector_keyword_tokens(
                sender_method_selector
            )
            alias_tokens = browser_session.selector_keyword_tokens(alias_selector)
            argument_names = [
                'argument%s' % (index + 1)
                for index in range(len(method_tokens))
            ]
            method_header_tokens = [
                '%s %s' % (method_tokens[index], argument_names[index])
                for index in range(len(method_tokens))
            ]
            alias_send_tokens = [
                '%s %s' % (alias_tokens[index], argument_names[index])
                for index in range(len(alias_tokens))
            ]
            method_header = ' '.join(method_header_tokens)
            alias_send = ' '.join(alias_send_tokens)
        else:
            method_header = sender_method_selector
            alias_send = alias_selector
        return (
            '%s\n'
            '    SwordfishMcpTracer\n'
            '        recordSenderExecutionForTarget: %s\n'
            '        callerClassName: %s\n'
            '        callerMethodSelector: %s\n'
            '        callerShowInstanceSide: %s.\n'
            '    ^self %s'
        ) % (
            method_header,
            target_selector_literal,
            caller_class_name_literal,
            caller_method_selector_literal,
            caller_show_instance_side_literal,
            alias_send,
        )

    def tracer_class_method_sources():
        return [
            (
                'edgeCounts\n'
                '    ^UserGlobals\n'
                '        at: #SwordfishMcpTracerEdgeCounts\n'
                '        ifAbsentPut: [ Dictionary new ]'
            ),
            (
                'clearEdgeCounts\n'
                '    UserGlobals at: #SwordfishMcpTracerEdgeCounts put: Dictionary new.\n'
                '    true'
            ),
            (
                'instrumentation\n'
                '    ^UserGlobals\n'
                '        at: #SwordfishMcpTracerInstrumentation\n'
                '        ifAbsentPut: [ Dictionary new ]'
            ),
            (
                'instrumentationEntriesForTarget: aTargetSelector\n'
                '    ^self instrumentation\n'
                '        at: aTargetSelector asString\n'
                '        ifAbsent: [ OrderedCollection new ]'
            ),
            (
                'instrumentationReportForTarget: aTargetSelector\n'
                '    | instrumentationEntries stream |\n'
                '    instrumentationEntries := self instrumentationEntriesForTarget: aTargetSelector.\n'
                '    stream := WriteStream on: String new.\n'
                '    instrumentationEntries withIndexDo: [ :entry :index |\n'
                '        stream nextPutAll: (entry at: 1).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: ((entry at: 2) ifTrue: [ \'true\' ] ifFalse: [ \'false\' ]).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: (entry at: 3).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: (entry at: 4).\n'
                '        index < instrumentationEntries size\n'
                '            ifTrue: [ stream nextPut: Character lf ]\n'
                '    ].\n'
                '    ^stream contents'
            ),
            (
                'clearInstrumentationForTarget: aTargetSelector\n'
                '    self instrumentation\n'
                '        removeKey: aTargetSelector asString\n'
                '        ifAbsent: [ ].\n'
                '    true'
            ),
            (
                'registerInstrumentationForTarget: aTargetSelector callerClassName: callerClassName callerMethodSelector: callerMethodSelector callerShowInstanceSide: callerShowInstanceSide aliasSelector: aliasSelector\n'
                '    | instrumentationEntry instrumentationEntries |\n'
                '    instrumentationEntry := Array\n'
                '        with: callerClassName\n'
                '        with: callerShowInstanceSide\n'
                '        with: callerMethodSelector asString\n'
                '        with: aliasSelector asString.\n'
                '    instrumentationEntries := self instrumentation\n'
                '        at: aTargetSelector asString\n'
                '        ifAbsentPut: [ OrderedCollection new ].\n'
                '    (instrumentationEntries includes: instrumentationEntry)\n'
                '        ifFalse: [ instrumentationEntries add: instrumentationEntry ].\n'
                '    true'
            ),
            (
                'selectorEdgeCountsFor: aSelector\n'
                '    ^self edgeCounts\n'
                '        at: aSelector asString\n'
                '        ifAbsentPut: [ Dictionary new ]'
            ),
            (
                'recordSenderExecutionForTarget: aTargetSelector callerClassName: callerClassName callerMethodSelector: callerMethodSelector callerShowInstanceSide: callerShowInstanceSide\n'
                '    | edge selectorEdgeCounts |\n'
                '    (UserGlobals at: #SwordfishMcpTracerEnabled ifAbsent: [ false ])\n'
                '        ifFalse: [ ^self ].\n'
                '    edge := Array\n'
                '        with: callerClassName\n'
                '        with: callerShowInstanceSide\n'
                '        with: callerMethodSelector asString.\n'
                '    selectorEdgeCounts := self selectorEdgeCountsFor: aTargetSelector.\n'
                '    selectorEdgeCounts\n'
                '        at: edge\n'
                '        put: ((selectorEdgeCounts at: edge ifAbsent: [ 0 ]) + 1).\n'
                '    ^self'
            ),
            (
                'observedEdgesFor: aSelector\n'
                '    | selectorEdgeCounts observedEdges |\n'
                '    selectorEdgeCounts := self edgeCounts\n'
                '        at: aSelector asString\n'
                '        ifAbsent: [ Dictionary new ].\n'
                '    observedEdges := OrderedCollection new.\n'
                '    selectorEdgeCounts keysAndValuesDo: [ :edge :count |\n'
                '        observedEdges add: (Array\n'
                '            with: (edge at: 1)\n'
                '            with: (edge at: 2)\n'
                '            with: (edge at: 3)\n'
                '            with: count)\n'
                '    ].\n'
                '    ^observedEdges asArray'
            ),
            (
                'observedEdgesReportFor: aSelector\n'
                '    | observedEdges stream |\n'
                '    observedEdges := self observedEdgesFor: aSelector.\n'
                '    stream := WriteStream on: String new.\n'
                '    observedEdges withIndexDo: [ :edge :index |\n'
                '        stream nextPutAll: (edge at: 1).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: ((edge at: 2) ifTrue: [ \'true\' ] ifFalse: [ \'false\' ]).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: (edge at: 3).\n'
                '        stream nextPut: $|.\n'
                '        stream nextPutAll: (edge at: 4) printString.\n'
                '        index < observedEdges size\n'
                '            ifTrue: [ stream nextPut: Character lf ]\n'
                '    ].\n'
                '    ^stream contents'
            ),
        ]

    def install_tracer_methods(browser_session):
        for method_source in tracer_class_method_sources():
            browser_session.compile_method(
                'SwordfishMcpTracer',
                False,
                method_source,
                'tracing',
            )

    def tracer_status_error_response(connection_id):
        return disabled_tool_response(
            connection_id,
            (
                'Tracer manifest does not match local MCP source. '
                'Run gs_tracer_install or use force=True.'
            ),
        )

    def install_tracer_in_browser_session(browser_session):
        browser_session.install_or_refresh_tracer()

    def ensure_tracer_manifest_matches(browser_session):
        return browser_session.ensure_tracer_manifest_matches()

    def enable_tracer_in_browser_session(browser_session):
        browser_session.enable_tracer()

    def trace_selector_in_browser_session(
        browser_session,
        method_name,
        max_results,
    ):
        return browser_session.trace_selector(
            method_name,
            max_results=max_results,
        )

    def untrace_selector_in_browser_session(browser_session, method_name):
        return browser_session.untrace_selector(method_name)

    def store_sender_evidence(
        connection_id,
        method_name,
        evidence_payload,
    ):
        evidence_run_id = uuid.uuid4().hex
        collected_sender_evidence[evidence_run_id] = {
            'connection_id': connection_id,
            'method_name': method_name,
            'created_at_epoch_seconds': int(time.time()),
            **evidence_payload,
        }
        return evidence_run_id

    def store_sender_test_plan(
        connection_id,
        method_name,
        test_plan_payload,
    ):
        test_plan_id = uuid.uuid4().hex
        planned_sender_tests[test_plan_id] = {
            'connection_id': connection_id,
            'method_name': method_name,
            'created_at_epoch_seconds': int(time.time()),
            **test_plan_payload,
        }
        return test_plan_id

    def sender_test_plan_for_selector(
        browser_session,
        method_name,
        max_depth,
        max_nodes,
        max_senders_per_selector,
        max_test_methods,
    ):
        return browser_session.sender_test_plan_for_selector(
            method_name,
            max_depth,
            max_nodes,
            max_senders_per_selector,
            max_test_methods,
        )

    def test_plan_for_connection_and_selector(
        connection_id,
        method_name,
        test_plan_id,
    ):
        test_plan = planned_sender_tests.get(test_plan_id)
        if test_plan is None:
            raise DomainException('Unknown test_plan_id.')
        if test_plan['connection_id'] != connection_id:
            raise DomainException(
                'test_plan_id is not associated with connection_id.'
            )
        if test_plan['method_name'] != method_name:
            raise DomainException(
                'test_plan_id does not match method_name.'
            )
        return test_plan

    def validate_sender_evidence_for_selector(
        connection_id,
        selector_name,
        evidence_run_id,
        evidence_max_age_seconds,
    ):
        evidence_record = collected_sender_evidence.get(evidence_run_id)
        if evidence_record is None:
            raise DomainException('Unknown evidence_run_id.')
        if evidence_record['connection_id'] != connection_id:
            raise DomainException(
                'evidence_run_id is not associated with connection_id.'
            )
        if evidence_record['method_name'] != selector_name:
            raise DomainException(
                'evidence_run_id does not match old_selector.'
            )
        created_at_epoch_seconds = evidence_record['created_at_epoch_seconds']
        evidence_age_seconds = int(time.time()) - created_at_epoch_seconds
        if evidence_age_seconds > evidence_max_age_seconds:
            raise DomainException(
                'evidence_run_id is older than evidence_max_age_seconds.'
            )
        if evidence_record['observed_total_count'] <= 0:
            raise DomainException(
                'evidence_run_id does not include observed sender evidence.'
            )
        return {
            'evidence_run_id': evidence_run_id,
            'created_at_epoch_seconds': created_at_epoch_seconds,
            'evidence_age_seconds': evidence_age_seconds,
        }

    def tracer_observed_senders_for_selector(
        browser_session,
        method_name,
        max_results=None,
        count_only=False,
    ):
        return browser_session.observed_senders_for_selector(
            method_name,
            max_results=max_results,
            count_only=count_only,
        )

    def validated_literal_value(input_value, argument_name):
        if input_value is None:
            return input_value
        if isinstance(input_value, (bool, int, float, str)):
            return input_value
        raise DomainException(
            '%s must be None, bool, int, float, or string.'
            % argument_name
        )

    def validated_selector(input_value, argument_name):
        input_value = validated_non_empty_string(input_value, argument_name)
        matches_unary_selector = unary_selector_pattern.match(input_value)
        matches_keyword_selector = keyword_selector_pattern.match(input_value)
        if not matches_unary_selector and not matches_keyword_selector:
            raise DomainException(
                (
                    '%s must be a unary selector (exampleSelector) '
                    'or keyword selector (example:with:).'
                )
                % argument_name
            )
        return input_value

    def validated_selector_rename_pair(old_selector, new_selector):
        old_selector = validated_selector(old_selector, 'old_selector')
        new_selector = validated_selector(new_selector, 'new_selector')
        if old_selector.count(':') != new_selector.count(':'):
            raise DomainException(
                'old_selector and new_selector must have the same arity.'
            )
        if old_selector == new_selector:
            raise DomainException(
                'old_selector and new_selector cannot be the same.'
            )
        return old_selector, new_selector

    def validated_keyword_parameter_token(input_value, argument_name):
        input_value = validated_non_empty_string(input_value, argument_name)
        if not keyword_token_pattern.match(input_value):
            raise DomainException(
                (
                    '%s must be a keyword token ending in : '
                    '(example: timeout:).'
                )
                % argument_name
            )
        return input_value

    def validated_statement_indexes(input_value, argument_name):
        if not isinstance(input_value, list) or not input_value:
            raise DomainException(
                '%s must be a non-empty list of integers.'
                % argument_name
            )
        validated_indexes = []
        for index_value in input_value:
            if not isinstance(index_value, int) or index_value <= 0:
                raise DomainException(
                    '%s must contain positive integers only.'
                    % argument_name
                )
            if index_value not in validated_indexes:
                validated_indexes.append(index_value)
        return sorted(validated_indexes)

    def supported_ast_query_sort_fields():
        return [
            'scan_order',
            'class_name',
            'method_selector',
            'send_count',
            'keyword_send_count',
            'unary_send_count',
            'binary_send_count',
            'block_count',
            'return_count',
            'cascade_count',
            'assignment_count',
            'statement_terminator_count',
            'explicit_self_send_count',
            'explicit_super_send_count',
            'body_line_count',
            'statement_count',
            'temporary_count',
            'branch_selector_count',
            'loop_selector_count',
            'max_block_nesting_depth',
        ]

    def validated_ast_query_sort_by(input_value, argument_name):
        input_value = validated_non_empty_string(input_value, argument_name)
        supported_fields = supported_ast_query_sort_fields()
        if input_value not in supported_fields:
            raise DomainException(
                '%s must be one of: %s.'
                % (
                    argument_name,
                    ', '.join(supported_fields),
                )
            )
        return input_value

    def validated_ast_pattern(input_value, argument_name):
        if not isinstance(input_value, dict):
            raise DomainException('%s must be a dictionary.' % argument_name)
        supported_integer_fields = [
            'min_send_count',
            'max_send_count',
            'min_keyword_send_count',
            'max_keyword_send_count',
            'min_unary_send_count',
            'max_unary_send_count',
            'min_binary_send_count',
            'max_binary_send_count',
            'min_block_count',
            'max_block_count',
            'min_return_count',
            'max_return_count',
            'min_cascade_count',
            'max_cascade_count',
            'min_assignment_count',
            'max_assignment_count',
            'min_statement_terminator_count',
            'max_statement_terminator_count',
            'min_explicit_self_send_count',
            'max_explicit_self_send_count',
            'min_explicit_super_send_count',
            'max_explicit_super_send_count',
            'min_body_line_count',
            'max_body_line_count',
            'min_statement_count',
            'max_statement_count',
            'min_temporary_count',
            'max_temporary_count',
            'min_branch_selector_count',
            'max_branch_selector_count',
            'min_loop_selector_count',
            'max_loop_selector_count',
            'min_max_block_nesting_depth',
            'max_max_block_nesting_depth',
        ]
        supported_list_fields = [
            'required_selectors',
            'any_required_selectors',
            'excluded_selectors',
            'required_send_types',
            'excluded_send_types',
            'required_receiver_hints',
            'excluded_receiver_hints',
        ]
        supported_string_fields = [
            'method_selector_regex',
        ]
        supported_fields = set(
            supported_integer_fields
            + supported_list_fields
            + supported_string_fields
        )
        for pattern_key in input_value.keys():
            if pattern_key not in supported_fields:
                raise DomainException(
                    'Unsupported ast_pattern field: %s.' % pattern_key
                )
        validated_pattern = {}
        selector_list_fields = {
            'required_selectors',
            'any_required_selectors',
            'excluded_selectors',
        }
        send_type_list_fields = {
            'required_send_types',
            'excluded_send_types',
        }
        receiver_hint_list_fields = {
            'required_receiver_hints',
            'excluded_receiver_hints',
        }
        supported_send_types = {'keyword', 'unary', 'binary'}
        supported_receiver_hints = {'self', 'super', 'unknown'}
        for field_name in supported_integer_fields:
            if field_name in input_value:
                field_value = input_value[field_name]
                if not isinstance(field_value, int) or field_value < 0:
                    raise DomainException(
                        '%s.%s must be a non-negative integer.'
                        % (
                            argument_name,
                            field_name,
                        )
                    )
                validated_pattern[field_name] = field_value
        for field_name in supported_list_fields:
            if field_name in input_value:
                field_values = input_value[field_name]
                if not isinstance(field_values, list):
                    raise DomainException(
                        '%s.%s must be a list.'
                        % (
                            argument_name,
                            field_name,
                        )
                    )
                if field_name in selector_list_fields:
                    validated_pattern[field_name] = [
                        validated_selector(
                            field_value,
                            '%s.%s' % (argument_name, field_name),
                        )
                        for field_value in field_values
                    ]
                if field_name in send_type_list_fields:
                    validated_values = []
                    for field_value in field_values:
                        field_value = validated_non_empty_string(
                            field_value,
                            '%s.%s' % (argument_name, field_name),
                        )
                        if field_value not in supported_send_types:
                            raise DomainException(
                                (
                                    '%s.%s entries must be one of: %s.'
                                )
                                % (
                                    argument_name,
                                    field_name,
                                    ', '.join(sorted(supported_send_types)),
                                )
                            )
                        if field_value not in validated_values:
                            validated_values.append(field_value)
                    validated_pattern[field_name] = validated_values
                if field_name in receiver_hint_list_fields:
                    validated_values = []
                    for field_value in field_values:
                        field_value = validated_non_empty_string(
                            field_value,
                            '%s.%s' % (argument_name, field_name),
                        )
                        if field_value not in supported_receiver_hints:
                            raise DomainException(
                                (
                                    '%s.%s entries must be one of: %s.'
                                )
                                % (
                                    argument_name,
                                    field_name,
                                    ', '.join(
                                        sorted(supported_receiver_hints)
                                    ),
                                )
                            )
                        if field_value not in validated_values:
                            validated_values.append(field_value)
                    validated_pattern[field_name] = validated_values
        if 'method_selector_regex' in input_value:
            method_selector_regex = validated_non_empty_string(
                input_value['method_selector_regex'],
                '%s.method_selector_regex' % argument_name,
            )
            try:
                re.compile(method_selector_regex)
            except re.error as error:
                raise DomainException(
                    '%s.method_selector_regex is not valid regex: %s.'
                    % (
                        argument_name,
                        error,
                    )
                )
            validated_pattern['method_selector_regex'] = method_selector_regex
        range_field_pairs = [
            ('min_send_count', 'max_send_count'),
            ('min_keyword_send_count', 'max_keyword_send_count'),
            ('min_unary_send_count', 'max_unary_send_count'),
            ('min_binary_send_count', 'max_binary_send_count'),
            ('min_block_count', 'max_block_count'),
            ('min_return_count', 'max_return_count'),
            ('min_cascade_count', 'max_cascade_count'),
            ('min_assignment_count', 'max_assignment_count'),
            (
                'min_statement_terminator_count',
                'max_statement_terminator_count',
            ),
            (
                'min_explicit_self_send_count',
                'max_explicit_self_send_count',
            ),
            (
                'min_explicit_super_send_count',
                'max_explicit_super_send_count',
            ),
            ('min_body_line_count', 'max_body_line_count'),
            ('min_statement_count', 'max_statement_count'),
            ('min_temporary_count', 'max_temporary_count'),
            ('min_branch_selector_count', 'max_branch_selector_count'),
            ('min_loop_selector_count', 'max_loop_selector_count'),
            (
                'min_max_block_nesting_depth',
                'max_max_block_nesting_depth',
            ),
        ]
        for min_field_name, max_field_name in range_field_pairs:
            has_range = (
                min_field_name in validated_pattern
                and max_field_name in validated_pattern
            )
            if has_range:
                min_field_value = validated_pattern[min_field_name]
                max_field_value = validated_pattern[max_field_name]
                if min_field_value > max_field_value:
                    raise DomainException(
                        (
                            '%s.%s cannot be greater than %s.%s.'
                        )
                        % (
                            argument_name,
                            min_field_name,
                            argument_name,
                            max_field_name,
                        )
                    )
        return validated_pattern

    def serialized_debug_frames(debug_session):
        stack_frames = debug_session.call_stack()
        return [
            {
                'level': frame.level,
                'class_name': frame.class_name,
                'method_name': frame.method_name,
                'method_source': frame.method_source,
                'step_point_offset': frame.step_point_offset,
            }
            for frame in stack_frames
        ]

    def debug_payload(debug_session):
        return {
            'stack_frames': serialized_debug_frames(debug_session),
        }

    def debug_action_response(
        connection_id,
        debug_id,
        debug_session,
        action_outcome,
    ):
        if action_outcome.has_completed:
            remove_debug_session(debug_id)
            return {
                'ok': True,
                'connection_id': connection_id,
                'debug_id': debug_id,
                'completed': True,
                'output': debug_session.rendered_result_payload(
                    action_outcome.result
                ),
            }
        return {
            'ok': True,
            'connection_id': connection_id,
            'debug_id': debug_id,
            'completed': False,
            'error': gemstone_error_payload(debug_session.exception),
            'debug': debug_payload(debug_session),
        }

    @mcp_server.tool()
    def gs_connect(
        connection_mode,
        gemstone_user_name='',
        gemstone_password='',
        stone_name='gs64stone',
        rpc_hostname='localhost',
        netldi_name='gemnetobject',
    ):
        if integrated_session_state.has_ide_session():
            gemstone_session = integrated_session_state.ide_session_for_mcp()
            if gemstone_session is None:
                return {
                    'ok': False,
                    'error': {
                        'message': 'IDE session is no longer available.',
                    },
                }
            try:
                summary = session_summary(gemstone_session)
            except GemstoneError as error:
                return {
                    'ok': False,
                    'error': gemstone_error_payload(error),
                }
            return {
                'ok': True,
                'connection_id': integrated_session_state.ide_connection_id(),
                'connection_mode': 'ide_attached',
                'session': summary,
                'managed_by_ide': True,
            }
        if gui_session_is_active():
            return {
                'ok': False,
                'error': {
                    'message': (
                        'gs_connect is disabled while the IDE is active '
                        'without a logged-in session. Log in from the IDE '
                        'first, then attach using gs_connect.'
                    ),
                },
            }
        if connection_mode == 'linked':
            gemstone_session = create_linked_session(
                gemstone_user_name,
                gemstone_password,
                stone_name,
            )
        elif connection_mode == 'rpc':
            gemstone_session = create_rpc_session(
                gemstone_user_name,
                gemstone_password,
                rpc_hostname,
                stone_name,
                netldi_name,
            )
        else:
            return {
                'ok': False,
                'error': {
                    'message': (
                        'Invalid connection_mode value. '
                        "Expected 'linked' or 'rpc'."
                    )
                },
            }

        try:
            summary = session_summary(gemstone_session)
        except GemstoneError as error:
            close_session(gemstone_session)
            return {
                'ok': False,
                'error': gemstone_error_payload(error),
            }

        connection_id = add_connection(
            gemstone_session,
            {
                'connection_mode': connection_mode,
                'transaction_active': False,
            },
        )
        return {
            'ok': True,
            'connection_id': connection_id,
            'connection_mode': connection_mode,
            'session': summary,
        }

    @mcp_server.tool()
    def gs_disconnect(connection_id):
        if (
            gui_session_is_active()
            and has_connection(connection_id)
            and not integrated_session_state.is_ide_connection_id(connection_id)
        ):
            return disabled_tool_response(
                connection_id,
                (
                    'gs_disconnect is disabled while the IDE controls '
                    'session ownership.'
                ),
            )
        if integrated_session_state.is_ide_connection_id(connection_id):
            return disabled_tool_response(
                connection_id,
                (
                    'gs_disconnect is disabled while the IDE owns '
                    'the active session.'
                ),
            )
        if not has_connection(connection_id):
            return {
                'ok': False,
                'error': {
                    'message': 'Unknown connection_id.',
                },
            }

        remove_debug_sessions_for_connection(connection_id)
        gemstone_session = remove_connection(connection_id)
        try:
            close_session(gemstone_session)
        except GemstoneError as error:
            return {
                'ok': False,
                'error': gemstone_error_payload(error),
            }

        return {
            'ok': True,
            'connection_id': connection_id,
        }

    @mcp_server.tool()
    def gs_begin(connection_id):
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        try:
            begin_transaction(gemstone_session)
            metadata = metadata_for_connection_id(connection_id)
            if metadata is not None:
                metadata['transaction_active'] = True
            if integrated_session_state.is_ide_connection_id(connection_id):
                integrated_session_state.mark_ide_transaction_active()
            return {
                'ok': True,
                'connection_id': connection_id,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_begin_if_needed(connection_id):
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        metadata = metadata_for_connection_id(connection_id)
        if metadata is None:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': 'Unknown connection_id.'},
            }
        if metadata.get('transaction_active'):
            return {
                'ok': True,
                'connection_id': connection_id,
                'began_transaction': False,
                'transaction_active': True,
            }
        try:
            begin_transaction(gemstone_session)
            metadata['transaction_active'] = True
            if integrated_session_state.is_ide_connection_id(connection_id):
                integrated_session_state.mark_ide_transaction_active()
            return {
                'ok': True,
                'connection_id': connection_id,
                'began_transaction': True,
                'transaction_active': True,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_commit(
        connection_id,
        approved_by_user=False,
        approval_note='',
    ):
        if not allow_commit:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_commit is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-commit to enable.'
                ),
            )
        if (
            integrated_session_state.is_ide_connection_id(connection_id)
            and not allow_commit_when_gui
        ):
            return disabled_tool_response(
                connection_id,
                (
                    'gs_commit is disabled while the IDE owns the session. '
                    'Use the IDE commit action or start swordfish --mode mcp-headless with '
                    '--allow-mcp-commit-when-gui.'
                ),
            )
        approval_error_response = require_explicit_user_confirmation(
            connection_id,
            'gs_commit',
            'commit',
            approved_by_user,
            approval_note,
        )
        if approval_error_response:
            return approval_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        try:
            commit_transaction(gemstone_session)
            metadata = metadata_for_connection_id(connection_id)
            if metadata is not None:
                metadata['transaction_active'] = False
            if integrated_session_state.is_ide_connection_id(connection_id):
                integrated_session_state.mark_ide_transaction_inactive()
            return {
                'ok': True,
                'connection_id': connection_id,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_transaction_status(connection_id):
        _, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        metadata = metadata_for_connection_id(connection_id)
        if metadata is None:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': 'Unknown connection_id.'},
            }
        return {
            'ok': True,
            'connection_id': connection_id,
            'connection_mode': metadata['connection_mode'],
            'transaction_active': metadata.get('transaction_active', False),
        }

    @mcp_server.tool()
    def gs_capabilities():
        ast_backend = browser_session_for_policy(None).ast_backend_status()
        gui_active = gui_session_is_active()
        shared_connection_id = None
        if gui_active:
            shared_connection_id = integrated_session_state.ide_connection_id()
        return {
            'ok': True,
            'server_name': 'SwordfishMCP',
            'policy': policy_flags(),
            'shared_ide_connection_id': shared_connection_id,
            'ast_backend': ast_backend,
            'ast_support': {
                'expected_version': AST_SUPPORT_VERSION,
                'expected_source_hash': ast_support_source_hash(),
                'tools': [
                    'gs_ast_status',
                    'gs_ast_install',
                ],
            },
            'guidance_intents': guidance_intents(),
            'recommended_bootstrap': [
                'gs_capabilities',
                'gs_guidance',
                'gs_connect',
                'gs_transaction_status',
            ],
            'tool_groups': {
                'navigation': [
                    'gs_find_classes',
                    'gs_find_selectors',
                    'gs_find_implementors',
                    'gs_find_senders',
                    'gs_ast_status',
                    'gs_get_method_source',
                    'gs_method_ast',
                    'gs_method_sends',
                    'gs_method_structure_summary',
                    'gs_method_control_flow_summary',
                    'gs_query_methods_by_ast_pattern',
                ],
                'safe_write': [
                    'gs_begin',
                    'gs_create_package',
                    'gs_install_package',
                    'gs_compile_method',
                    'gs_create_class',
                    'gs_create_class_in_package',
                    'gs_create_test_case_class',
                    'gs_create_test_case_class_in_package',
                    'gs_apply_selector_rename',
                    'gs_apply_rename_method',
                    'gs_apply_move_method',
                    'gs_apply_add_parameter',
                    'gs_apply_remove_parameter',
                    'gs_apply_extract_method',
                    'gs_apply_inline_method',
                    'gs_commit',
                    'gs_abort',
                ],
                'refactor': [
                    'gs_preview_selector_rename',
                    'gs_apply_selector_rename',
                    'gs_preview_rename_method',
                    'gs_apply_rename_method',
                    'gs_preview_move_method',
                    'gs_apply_move_method',
                    'gs_preview_add_parameter',
                    'gs_apply_add_parameter',
                    'gs_preview_remove_parameter',
                    'gs_apply_remove_parameter',
                    'gs_preview_extract_method',
                    'gs_apply_extract_method',
                    'gs_preview_inline_method',
                    'gs_apply_inline_method',
                ],
                'evidence': [
                    'gs_plan_evidence_tests',
                    'gs_collect_sender_evidence',
                    'gs_tracer_*',
                ],
                'ast_support': [
                    'gs_ast_status',
                    'gs_ast_install',
                ],
            },
        }

    @mcp_server.tool()
    def gs_guidance(intent='general', selector=None, change_kind=None):
        try:
            intent = validated_non_empty_string(intent, 'intent').strip().lower()
            if intent not in guidance_intents():
                raise DomainException(
                    'intent must be one of: %s.'
                    % ', '.join(guidance_intents())
                )
            if selector is not None:
                selector = validated_non_empty_string(
                    selector,
                    'selector',
                ).strip()
            if change_kind is not None:
                change_kind = validated_non_empty_string(
                    change_kind,
                    'change_kind',
                ).strip()
            guidance = guidance_for_intent(intent, selector, change_kind)
            return {
                'ok': True,
                'policy': policy_flags(),
                'intent': intent,
                'selector': selector,
                'change_kind': change_kind,
                'guidance': guidance,
            }
        except DomainException as error:
            return {
                'ok': False,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_abort(connection_id):
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        try:
            abort_transaction(gemstone_session)
            metadata = metadata_for_connection_id(connection_id)
            if metadata is not None:
                metadata['transaction_active'] = False
            if integrated_session_state.is_ide_connection_id(connection_id):
                integrated_session_state.mark_ide_transaction_inactive()
            return {
                'ok': True,
                'connection_id': connection_id,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_list_packages(connection_id):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            return {
                'ok': True,
                'connection_id': connection_id,
                'packages': browser_session.list_packages(),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }

    @mcp_server.tool()
    def gs_list_classes(connection_id, package_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
                'classes': browser_session.list_classes(package_name),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }

    @mcp_server.tool()
    def gs_package_exists(connection_id, package_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            package_name = validated_non_empty_string_stripped(
                package_name,
                'package_name',
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
                'exists': browser_session.package_exists(package_name),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_create_package(connection_id, package_name):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_create_package is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            package_name = validated_non_empty_string_stripped(
                package_name,
                'package_name',
            )
            browser_session.create_and_install_package(package_name)
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
                'installed': True,
                'visible_in_package_list': browser_session.package_exists(
                    package_name
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_install_package(connection_id, package_name):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_install_package is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            package_name = validated_non_empty_string_stripped(
                package_name,
                'package_name',
            )
            browser_session.install_package(package_name)
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_list_method_categories(
        connection_id,
        class_name,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_categories': browser_session.list_method_categories(
                    class_name,
                    show_instance_side
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_list_methods(
        connection_id,
        class_name,
        method_category='all',
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_category': method_category,
                'show_instance_side': show_instance_side,
                'selectors': browser_session.list_methods(
                    class_name,
                    method_category,
                    show_instance_side,
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_get_method_source(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
                'source': browser_session.get_method_source(
                    class_name,
                    method_selector,
                    show_instance_side,
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_find_classes(connection_id, search_input):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            return {
                'ok': True,
                'connection_id': connection_id,
                'search_input': search_input,
                'class_names': browser_session.find_classes(search_input),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_method_sends(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            started_at = time.perf_counter()
            sends_result = browser_session.method_sends(
                class_name,
                method_selector,
                show_instance_side,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
                'total_count': sends_result['total_count'],
                'elapsed_ms': elapsed_ms,
                'sends': sends_result['sends'],
                'analysis_limitations': sends_result['analysis_limitations'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_method_ast(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            started_at = time.perf_counter()
            method_ast = browser_session.method_ast(
                class_name,
                method_selector,
                show_instance_side,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
                'elapsed_ms': elapsed_ms,
                'ast': method_ast,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_method_structure_summary(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            started_at = time.perf_counter()
            summary = browser_session.method_structure_summary(
                class_name,
                method_selector,
                show_instance_side,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
                'elapsed_ms': elapsed_ms,
                'summary': summary,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_method_control_flow_summary(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            started_at = time.perf_counter()
            summary = browser_session.method_control_flow_summary(
                class_name,
                method_selector,
                show_instance_side,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
                'elapsed_ms': elapsed_ms,
                'summary': summary,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_query_methods_by_ast_pattern(
        connection_id,
        ast_pattern,
        package_name=None,
        class_name=None,
        show_instance_side=True,
        method_category='all',
        max_results=None,
        sort_by='scan_order',
        sort_descending=False,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            ast_pattern = validated_ast_pattern(
                ast_pattern,
                'ast_pattern',
            )
            if package_name is not None:
                package_name = validated_non_empty_string(
                    package_name,
                    'package_name',
                )
            if class_name is not None:
                class_name = validated_identifier(
                    class_name,
                    'class_name',
                )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            method_category = validated_non_empty_string(
                method_category,
                'method_category',
            )
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            sort_by = validated_ast_query_sort_by(
                sort_by,
                'sort_by',
            )
            sort_descending = validated_boolean_like(
                sort_descending,
                'sort_descending',
            )
            started_at = time.perf_counter()
            query_result = browser_session.query_methods_by_ast_pattern(
                ast_pattern,
                package_name=package_name,
                class_name=class_name,
                show_instance_side=show_instance_side,
                method_category=method_category,
                max_results=max_results,
                sort_by=sort_by,
                sort_descending=sort_descending,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'ast_pattern': ast_pattern,
                'package_name': package_name,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_category': method_category,
                'max_results': max_results,
                'sort_by': sort_by,
                'sort_descending': sort_descending,
                'elapsed_ms': elapsed_ms,
                'match_count': query_result['match_count'],
                'scanned_method_count': query_result['scanned_method_count'],
                'truncated': query_result['truncated'],
                'result_sort_by': query_result['sort_by'],
                'result_sort_descending': query_result[
                    'sort_descending'
                ],
                'matches': query_result['matches'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_find_selectors(connection_id, search_input):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            return {
                'ok': True,
                'connection_id': connection_id,
                'search_input': search_input,
                'selectors': browser_session.find_selectors(search_input),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }

    @mcp_server.tool()
    def gs_find_implementors(
        connection_id,
        method_name,
        max_results=None,
        count_only=False,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            method_name = validated_non_empty_string(method_name, 'method_name')
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            count_only = validated_boolean(count_only, 'count_only')
            started_at = time.perf_counter()
            search_result = browser_session.find_implementors_with_summary(
                method_name,
                max_results=max_results,
                count_only=count_only,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'max_results': max_results,
                'count_only': count_only,
                'total_count': search_result['total_count'],
                'returned_count': search_result['returned_count'],
                'elapsed_ms': elapsed_ms,
                'implementors': search_result['implementors'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_find_senders(
        connection_id,
        method_name,
        max_results=None,
        count_only=False,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            method_name = validated_non_empty_string(method_name, 'method_name')
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            count_only = validated_boolean(count_only, 'count_only')
            started_at = time.perf_counter()
            search_result = browser_session.find_senders(
                method_name,
                max_results=max_results,
                count_only=count_only,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'max_results': max_results,
                'count_only': count_only,
                'total_count': search_result['total_count'],
                'returned_count': search_result['returned_count'],
                'elapsed_ms': elapsed_ms,
                'senders': search_result['senders'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_ast_status(connection_id):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            ast_status = ast_status_for_browser_session(browser_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                'require_gemstone_ast': require_gemstone_ast,
                **ast_status,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_ast_install(connection_id):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_ast_install is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            install_ast_support_in_browser_session(browser_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                **ast_status_for_browser_session(browser_session),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_status(connection_id):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            tracer_status = tracer_status_for_browser_session(browser_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                'tracing_allowed': allow_tracing,
                **tracer_status,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_install(connection_id):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_install is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_install',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            install_tracer_in_browser_session(browser_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                **tracer_status_for_browser_session(browser_session),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_enable(connection_id, force=False):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_enable is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_enable',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            force = validated_boolean(force, 'force')
            tracer_status = tracer_status_for_browser_session(browser_session)
            if not force and not tracer_status['manifest_matches']:
                return tracer_status_error_response(connection_id)
            enable_tracer_in_browser_session(browser_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                **tracer_status_for_browser_session(browser_session),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_disable(connection_id):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_disable is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_disable',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            browser_session.disable_tracer()
            return {
                'ok': True,
                'connection_id': connection_id,
                **tracer_status_for_browser_session(browser_session),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_uninstall(connection_id):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_uninstall is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_uninstall',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            browser_session.uninstall_tracer()
            return {
                'ok': True,
                'connection_id': connection_id,
                **tracer_status_for_browser_session(browser_session),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_trace_selector(
        connection_id,
        method_name,
        max_results=None,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_trace_selector is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_trace_selector',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            method_name = validated_selector(method_name, 'method_name')
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            tracer_status = tracer_status_for_browser_session(browser_session)
            if not tracer_status['manifest_matches']:
                return tracer_status_error_response(connection_id)
            trace_result = trace_selector_in_browser_session(
                browser_session,
                method_name,
                max_results,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                **trace_result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_untrace_selector(
        connection_id,
        method_name,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_untrace_selector is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_untrace_selector',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            method_name = validated_selector(method_name, 'method_name')
            untrace_result = untrace_selector_in_browser_session(
                browser_session,
                method_name,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                **untrace_result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_clear_observed_senders(connection_id, method_name=None):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_tracer_clear_observed_senders is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_clear_observed_senders',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            if method_name is not None:
                method_name = validated_selector(method_name, 'method_name')
            browser_session.clear_observed_senders(method_name)
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'cleared': True,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_tracer_find_observed_senders(
        connection_id,
        method_name,
        max_results=None,
        count_only=False,
    ):
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_tracer_find_observed_senders',
        )
        if tracing_error_response:
            return tracing_error_response
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            method_name = validated_selector(method_name, 'method_name')
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            count_only = validated_boolean(count_only, 'count_only')
            started_at = time.perf_counter()
            observed_senders_result = tracer_observed_senders_for_selector(
                browser_session,
                method_name,
                max_results=max_results,
                count_only=count_only,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'max_results': max_results,
                'count_only': count_only,
                'total_count': observed_senders_result['total_count'],
                'returned_count': observed_senders_result['returned_count'],
                'total_observed_calls': observed_senders_result[
                    'total_observed_calls'
                ],
                'elapsed_ms': elapsed_ms,
                'observed_senders': observed_senders_result[
                    'observed_senders'
                ],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_plan_evidence_tests(
        connection_id,
        method_name,
        max_depth=2,
        max_nodes=500,
        max_senders_per_selector=200,
        max_test_methods=200,
    ):
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_plan_evidence_tests',
        )
        if tracing_error_response:
            return tracing_error_response
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            method_name = validated_selector(method_name, 'method_name')
            max_depth = validated_non_negative_integer_or_none(
                max_depth,
                'max_depth',
            )
            max_nodes = validated_positive_integer(
                max_nodes,
                'max_nodes',
            )
            max_senders_per_selector = validated_positive_integer(
                max_senders_per_selector,
                'max_senders_per_selector',
            )
            max_test_methods = validated_positive_integer(
                max_test_methods,
                'max_test_methods',
            )
            if max_depth is None:
                raise DomainException('max_depth cannot be None.')
            test_plan = sender_test_plan_for_selector(
                browser_session,
                method_name,
                max_depth,
                max_nodes,
                max_senders_per_selector,
                max_test_methods,
            )
            test_plan_id = store_sender_test_plan(
                connection_id,
                method_name,
                test_plan,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'test_plan_id': test_plan_id,
                'plan': test_plan,
                'workflow_guidance': [
                    'Pass this test_plan_id to gs_collect_sender_evidence to execute planned tests.',
                    'If plan.candidate_test_count is 0, use explicit package_name or test_case_class_name during evidence collection.',
                ],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_collect_sender_evidence(
        connection_id,
        method_name,
        test_case_class_name=None,
        test_method_selector=None,
        package_name=None,
        test_plan_id=None,
        max_planned_tests=None,
        stop_on_first_observed=False,
        max_results=None,
        count_only=False,
        clear_observed=True,
        untrace_after=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_collect_sender_evidence is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        tracing_error_response = require_tracing_enabled(
            connection_id,
            'gs_collect_sender_evidence',
        )
        if tracing_error_response:
            return tracing_error_response
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            method_name = validated_selector(method_name, 'method_name')
            max_results = validated_non_negative_integer_or_none(
                max_results,
                'max_results',
            )
            max_planned_tests = validated_non_negative_integer_or_none(
                max_planned_tests,
                'max_planned_tests',
            )
            count_only = validated_boolean(count_only, 'count_only')
            clear_observed = validated_boolean(clear_observed, 'clear_observed')
            untrace_after = validated_boolean(untrace_after, 'untrace_after')
            stop_on_first_observed = validated_boolean(
                stop_on_first_observed,
                'stop_on_first_observed',
            )
            if test_case_class_name is not None:
                test_case_class_name = validated_identifier(
                    test_case_class_name,
                    'test_case_class_name',
                )
            if test_method_selector is not None:
                test_method_selector = validated_non_empty_string(
                    test_method_selector,
                    'test_method_selector',
                )
                if test_case_class_name is None:
                    raise DomainException(
                        'test_case_class_name is required when test_method_selector is provided.'
                    )
            if package_name is not None:
                package_name = validated_non_empty_string(
                    package_name,
                    'package_name',
                )
            if package_name is not None and test_case_class_name is not None:
                raise DomainException(
                    'Specify either package_name or test_case_class_name, not both.'
                )
            if test_plan_id is not None:
                test_plan_id = validated_non_empty_string(
                    test_plan_id,
                    'test_plan_id',
                )
            started_at = time.perf_counter()
            ensure_tracer_manifest_matches(browser_session)
            enable_tracer_in_browser_session(browser_session)
            trace_result = trace_selector_in_browser_session(
                browser_session,
                method_name,
                max_results,
            )
            if clear_observed:
                browser_session.clear_observed_senders(method_name)
            test_runs = []
            planned_tests = []
            if test_plan_id is not None:
                test_plan = test_plan_for_connection_and_selector(
                    connection_id,
                    method_name,
                    test_plan_id,
                )
                planned_tests = test_plan['candidate_tests']
                if max_planned_tests is not None:
                    planned_tests = planned_tests[:max_planned_tests]
            keep_running_planned_tests = True
            for planned_test in planned_tests:
                if keep_running_planned_tests:
                    planned_test_result = browser_session.run_test_method(
                        planned_test['test_case_class_name'],
                        planned_test['test_method_selector'],
                    )
                    test_runs.append(
                        {
                            'scope': 'planned_test_method',
                            'target': planned_test['test_case_class_name'],
                            'selector': planned_test['test_method_selector'],
                            'depth': planned_test['depth'],
                            'tests_passed': planned_test_result['has_passed'],
                            'result': planned_test_result,
                        }
                    )
                    if stop_on_first_observed:
                        observed_snapshot = tracer_observed_senders_for_selector(
                            browser_session,
                            method_name,
                            max_results=1,
                            count_only=True,
                        )
                        has_observed_sender = (
                            observed_snapshot['total_count'] > 0
                        )
                        if has_observed_sender:
                            keep_running_planned_tests = False
            should_run_explicit_tests = keep_running_planned_tests
            if should_run_explicit_tests and test_method_selector is not None:
                test_result = browser_session.run_test_method(
                    test_case_class_name,
                    test_method_selector,
                )
                test_runs.append(
                    {
                        'scope': 'test_method',
                        'target': test_case_class_name,
                        'selector': test_method_selector,
                        'tests_passed': test_result['has_passed'],
                        'result': test_result,
                    }
                )
            elif should_run_explicit_tests and package_name is not None:
                test_result = browser_session.run_tests_in_package(package_name)
                test_runs.append(
                    {
                        'scope': 'package',
                        'target': package_name,
                        'tests_passed': test_result['has_passed'],
                        'result': test_result,
                    }
                )
            elif should_run_explicit_tests and test_case_class_name is not None:
                test_result = browser_session.run_gemstone_tests(
                    test_case_class_name
                )
                test_runs.append(
                    {
                        'scope': 'test_case_class',
                        'target': test_case_class_name,
                        'tests_passed': test_result['has_passed'],
                        'result': test_result,
                    }
                )
            observed_senders_result = tracer_observed_senders_for_selector(
                browser_session,
                method_name,
                max_results=max_results,
                count_only=count_only,
            )
            untrace_result = None
            if untrace_after:
                untrace_result = untrace_selector_in_browser_session(
                    browser_session,
                    method_name,
                )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            evidence_run_id = store_sender_evidence(
                connection_id,
                method_name,
                {
                    'trace_result': trace_result,
                    'test_runs': test_runs,
                    'observed_total_count': observed_senders_result[
                        'total_count'
                    ],
                    'observed_total_calls': observed_senders_result[
                        'total_observed_calls'
                    ],
                },
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'test_plan_id': test_plan_id,
                'planned_test_count': len(planned_tests),
                'max_planned_tests': max_planned_tests,
                'stop_on_first_observed': stop_on_first_observed,
                'max_results': max_results,
                'count_only': count_only,
                'clear_observed': clear_observed,
                'untrace_after': untrace_after,
                'trace': trace_result,
                'test_runs': test_runs,
                'observed': observed_senders_result,
                'untrace': untrace_result,
                'evidence_run_id': evidence_run_id,
                'elapsed_ms': elapsed_ms,
                'workflow_guidance': [
                    'Use this evidence_run_id when applying selector rename with require_observed_sender_evidence=True.',
                    'If observed.total_count is 0, rerun with broader tests or a deeper gs_plan_evidence_tests plan.',
                ],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_compile_method(
        connection_id,
        class_name,
        source,
        show_instance_side=True,
        method_category='as yet unclassified',
        in_dictionary=None,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_compile_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            source = validated_non_empty_string(source, 'source')
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            method_category = validated_non_empty_string(
                method_category,
                'method_category',
            )
            if in_dictionary is not None:
                in_dictionary = validated_non_empty_string_stripped(
                    in_dictionary,
                    'in_dictionary',
                )
                browser_session.compile_method_in_dictionary(
                    class_name,
                    in_dictionary,
                    show_instance_side,
                    source,
                    method_category,
                )
            else:
                browser_session.compile_method(
                    class_name,
                    show_instance_side,
                    source,
                    method_category,
                )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_category': method_category,
                'in_dictionary': in_dictionary,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_create_class(
        connection_id,
        class_name,
        superclass_name='Object',
        inst_var_names=None,
        class_var_names=None,
        class_inst_var_names=None,
        pool_dictionary_names=None,
        in_dictionary='UserGlobals',
        package_name='',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_create_class is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            superclass_name = validated_identifier(
                superclass_name,
                'superclass_name',
            )
            in_dictionary, package_name = resolved_class_creation_target(
                browser_session,
                in_dictionary,
                package_name,
            )
            inst_var_names = validated_identifier_names(
                inst_var_names,
                'inst_var_names',
            )
            class_var_names = validated_identifier_names(
                class_var_names,
                'class_var_names',
            )
            class_inst_var_names = validated_identifier_names(
                class_inst_var_names,
                'class_inst_var_names',
            )
            pool_dictionary_names = validated_identifier_names(
                pool_dictionary_names,
                'pool_dictionary_names',
            )
            browser_session.create_class(
                class_name=class_name,
                superclass_name=superclass_name,
                inst_var_names=inst_var_names,
                class_var_names=class_var_names,
                class_inst_var_names=class_inst_var_names,
                pool_dictionary_names=pool_dictionary_names,
                in_dictionary=in_dictionary,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'superclass_name': superclass_name,
                'inst_var_names': inst_var_names,
                'class_var_names': class_var_names,
                'class_inst_var_names': class_inst_var_names,
                'pool_dictionary_names': pool_dictionary_names,
                'in_dictionary': in_dictionary,
                'package_name': package_name,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_create_class_in_package(
        connection_id,
        class_name,
        package_name,
        superclass_name='Object',
        inst_var_names=None,
        class_var_names=None,
        class_inst_var_names=None,
        pool_dictionary_names=None,
    ):
        return gs_create_class(
            connection_id=connection_id,
            class_name=class_name,
            superclass_name=superclass_name,
            inst_var_names=inst_var_names,
            class_var_names=class_var_names,
            class_inst_var_names=class_inst_var_names,
            pool_dictionary_names=pool_dictionary_names,
            package_name=package_name,
        )

    @mcp_server.tool()
    def gs_create_test_case_class(
        connection_id,
        class_name,
        in_dictionary='UserGlobals',
        package_name='',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_create_test_case_class is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            in_dictionary, package_name = resolved_class_creation_target(
                browser_session,
                in_dictionary,
                package_name,
            )
            browser_session.create_test_case_class(
                class_name=class_name,
                in_dictionary=in_dictionary,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'superclass_name': 'TestCase',
                'in_dictionary': in_dictionary,
                'package_name': package_name,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_create_test_case_class_in_package(
        connection_id,
        class_name,
        package_name,
    ):
        return gs_create_test_case_class(
            connection_id=connection_id,
            class_name=class_name,
            package_name=package_name,
        )

    @mcp_server.tool()
    def gs_get_class_definition(connection_id, class_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'class_definition': browser_session.get_class_definition(
                    class_name
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_delete_class(
        connection_id,
        class_name,
        in_dictionary='UserGlobals',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_delete_class is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
            )
            browser_session.delete_class(
                class_name=class_name,
                in_dictionary=in_dictionary,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'in_dictionary': in_dictionary,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_delete_method(
        connection_id,
        class_name,
        method_selector,
        show_instance_side=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_delete_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            browser_session.delete_method(
                class_name=class_name,
                method_selector=method_selector,
                show_instance_side=show_instance_side,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_set_method_category(
        connection_id,
        class_name,
        method_selector,
        method_category,
        show_instance_side=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_set_method_category is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
            )
            method_category = validated_non_empty_string(
                method_category,
                'method_category',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            browser_session.set_method_category(
                class_name=class_name,
                method_selector=method_selector,
                method_category=method_category,
                show_instance_side=show_instance_side,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'method_selector': method_selector,
                'method_category': method_category,
                'show_instance_side': show_instance_side,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_list_test_case_classes(connection_id, package_name=None):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            if package_name is not None:
                package_name = validated_non_empty_string(
                    package_name,
                    'package_name',
                )
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
                'test_case_classes': browser_session.list_test_case_classes(
                    package_name
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_run_tests_in_package(connection_id, package_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            package_name = validated_non_empty_string(
                package_name,
                'package_name',
            )
            test_result = browser_session.run_tests_in_package(package_name)
            return {
                'ok': True,
                'connection_id': connection_id,
                'package_name': package_name,
                'result': test_result,
                'tests_passed': test_result['has_passed'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_run_test_method(
        connection_id,
        test_case_class_name,
        test_method_selector,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            test_case_class_name = validated_identifier(
                test_case_class_name,
                'test_case_class_name',
            )
            test_method_selector = validated_non_empty_string(
                test_method_selector,
                'test_method_selector',
            )
            test_result = browser_session.run_test_method(
                test_case_class_name,
                test_method_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'test_case_class_name': test_case_class_name,
                'test_method_selector': test_method_selector,
                'result': test_result,
                'tests_passed': test_result['has_passed'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_rename_method(
        connection_id,
        class_name,
        old_selector,
        new_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(class_name, 'class_name')
            old_selector, new_selector = validated_selector_rename_pair(
                old_selector,
                new_selector,
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            preview = browser_session.method_rename_preview(
                class_name,
                show_instance_side,
                old_selector,
                new_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'old_selector': old_selector,
                'new_selector': new_selector,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_rename_method(
        connection_id,
        class_name,
        old_selector,
        new_selector,
        show_instance_side=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_rename_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            old_selector, new_selector = validated_selector_rename_pair(
                old_selector,
                new_selector,
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            result = browser_session.apply_method_rename(
                class_name,
                show_instance_side,
                old_selector,
                new_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'old_selector': old_selector,
                'new_selector': new_selector,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_move_method(
        connection_id,
        source_class_name,
        method_selector,
        target_class_name,
        source_show_instance_side=True,
        target_show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            source_class_name = validated_identifier(
                source_class_name,
                'source_class_name',
            )
            target_class_name = validated_identifier(
                target_class_name,
                'target_class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            source_show_instance_side = validated_boolean_like(
                source_show_instance_side,
                'source_show_instance_side',
            )
            target_show_instance_side = validated_boolean_like(
                target_show_instance_side,
                'target_show_instance_side',
            )
            preview = browser_session.method_move_preview(
                source_class_name,
                source_show_instance_side,
                target_class_name,
                target_show_instance_side,
                method_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'source_class_name': source_class_name,
                'source_show_instance_side': source_show_instance_side,
                'target_class_name': target_class_name,
                'target_show_instance_side': target_show_instance_side,
                'method_selector': method_selector,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_move_method(
        connection_id,
        source_class_name,
        method_selector,
        target_class_name,
        source_show_instance_side=True,
        target_show_instance_side=True,
        overwrite_target_method=False,
        delete_source_method=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_move_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            source_class_name = validated_identifier(
                source_class_name,
                'source_class_name',
            )
            target_class_name = validated_identifier(
                target_class_name,
                'target_class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            source_show_instance_side = validated_boolean_like(
                source_show_instance_side,
                'source_show_instance_side',
            )
            target_show_instance_side = validated_boolean_like(
                target_show_instance_side,
                'target_show_instance_side',
            )
            overwrite_target_method = validated_boolean_like(
                overwrite_target_method,
                'overwrite_target_method',
            )
            delete_source_method = validated_boolean_like(
                delete_source_method,
                'delete_source_method',
            )
            result = browser_session.apply_method_move(
                source_class_name,
                source_show_instance_side,
                target_class_name,
                target_show_instance_side,
                method_selector,
                overwrite_target_method=overwrite_target_method,
                delete_source_method=delete_source_method,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'source_class_name': source_class_name,
                'source_show_instance_side': source_show_instance_side,
                'target_class_name': target_class_name,
                'target_show_instance_side': target_show_instance_side,
                'method_selector': method_selector,
                'overwrite_target_method': overwrite_target_method,
                'delete_source_method': delete_source_method,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_add_parameter(
        connection_id,
        class_name,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            if ':' not in method_selector:
                raise DomainException(
                    'method_selector must be a keyword selector.'
                )
            parameter_keyword = validated_keyword_parameter_token(
                parameter_keyword,
                'parameter_keyword',
            )
            parameter_name = validated_identifier(
                parameter_name,
                'parameter_name',
            )
            default_argument_source = validated_non_empty_string(
                default_argument_source,
                'default_argument_source',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            preview = browser_session.method_add_parameter_preview(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                parameter_name,
                default_argument_source,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'parameter_keyword': parameter_keyword,
                'parameter_name': parameter_name,
                'default_argument_source': default_argument_source,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_add_parameter(
        connection_id,
        class_name,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
        show_instance_side=True,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_add_parameter is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            if ':' not in method_selector:
                raise DomainException(
                    'method_selector must be a keyword selector.'
                )
            parameter_keyword = validated_keyword_parameter_token(
                parameter_keyword,
                'parameter_keyword',
            )
            parameter_name = validated_identifier(
                parameter_name,
                'parameter_name',
            )
            default_argument_source = validated_non_empty_string(
                default_argument_source,
                'default_argument_source',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            result = browser_session.apply_method_add_parameter(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                parameter_name,
                default_argument_source,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'parameter_keyword': parameter_keyword,
                'parameter_name': parameter_name,
                'default_argument_source': default_argument_source,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_remove_parameter(
        connection_id,
        class_name,
        method_selector,
        parameter_keyword,
        show_instance_side=True,
        rewrite_source_senders=False,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            if ':' not in method_selector:
                raise DomainException(
                    'method_selector must be a keyword selector.'
                )
            parameter_keyword = validated_keyword_parameter_token(
                parameter_keyword,
                'parameter_keyword',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            rewrite_source_senders = validated_boolean_like(
                rewrite_source_senders,
                'rewrite_source_senders',
            )
            preview = browser_session.method_remove_parameter_preview(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                rewrite_source_senders=rewrite_source_senders,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'parameter_keyword': parameter_keyword,
                'rewrite_source_senders': rewrite_source_senders,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_remove_parameter(
        connection_id,
        class_name,
        method_selector,
        parameter_keyword,
        show_instance_side=True,
        overwrite_new_method=False,
        rewrite_source_senders=False,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_remove_parameter is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            if ':' not in method_selector:
                raise DomainException(
                    'method_selector must be a keyword selector.'
                )
            parameter_keyword = validated_keyword_parameter_token(
                parameter_keyword,
                'parameter_keyword',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            overwrite_new_method = validated_boolean_like(
                overwrite_new_method,
                'overwrite_new_method',
            )
            rewrite_source_senders = validated_boolean_like(
                rewrite_source_senders,
                'rewrite_source_senders',
            )
            result = browser_session.apply_method_remove_parameter(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                overwrite_new_method=overwrite_new_method,
                rewrite_source_senders=rewrite_source_senders,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'parameter_keyword': parameter_keyword,
                'overwrite_new_method': overwrite_new_method,
                'rewrite_source_senders': rewrite_source_senders,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_extract_method(
        connection_id,
        class_name,
        method_selector,
        new_selector,
        statement_indexes,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            new_selector = validated_selector(
                new_selector,
                'new_selector',
            )
            if ':' in new_selector:
                raise DomainException(
                    'new_selector must be a unary selector.'
                )
            statement_indexes = validated_statement_indexes(
                statement_indexes,
                'statement_indexes',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            preview = browser_session.method_extract_preview(
                class_name,
                show_instance_side,
                method_selector,
                new_selector,
                statement_indexes,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'new_selector': new_selector,
                'statement_indexes': statement_indexes,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_extract_method(
        connection_id,
        class_name,
        method_selector,
        new_selector,
        statement_indexes,
        show_instance_side=True,
        overwrite_new_method=False,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_extract_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            method_selector = validated_selector(
                method_selector,
                'method_selector',
            )
            new_selector = validated_selector(
                new_selector,
                'new_selector',
            )
            if ':' in new_selector:
                raise DomainException(
                    'new_selector must be a unary selector.'
                )
            statement_indexes = validated_statement_indexes(
                statement_indexes,
                'statement_indexes',
            )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            overwrite_new_method = validated_boolean_like(
                overwrite_new_method,
                'overwrite_new_method',
            )
            result = browser_session.apply_method_extract(
                class_name,
                show_instance_side,
                method_selector,
                new_selector,
                statement_indexes,
                overwrite_new_method=overwrite_new_method,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'new_selector': new_selector,
                'statement_indexes': statement_indexes,
                'overwrite_new_method': overwrite_new_method,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_inline_method(
        connection_id,
        class_name,
        caller_selector,
        inline_selector,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            caller_selector = validated_selector(
                caller_selector,
                'caller_selector',
            )
            inline_selector = validated_selector(
                inline_selector,
                'inline_selector',
            )
            if ':' in inline_selector:
                raise DomainException(
                    'inline_selector must be a unary selector.'
                )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            preview = browser_session.method_inline_preview(
                class_name,
                show_instance_side,
                caller_selector,
                inline_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'caller_selector': caller_selector,
                'inline_selector': inline_selector,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_inline_method(
        connection_id,
        class_name,
        caller_selector,
        inline_selector,
        show_instance_side=True,
        delete_inlined_method=False,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_inline_method is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            class_name = validated_identifier(
                class_name,
                'class_name',
            )
            caller_selector = validated_selector(
                caller_selector,
                'caller_selector',
            )
            inline_selector = validated_selector(
                inline_selector,
                'inline_selector',
            )
            if ':' in inline_selector:
                raise DomainException(
                    'inline_selector must be a unary selector.'
                )
            show_instance_side = validated_boolean_like(
                show_instance_side,
                'show_instance_side',
            )
            delete_inlined_method = validated_boolean_like(
                delete_inlined_method,
                'delete_inlined_method',
            )
            result = browser_session.apply_method_inline(
                class_name,
                show_instance_side,
                caller_selector,
                inline_selector,
                delete_inlined_method=delete_inlined_method,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'caller_selector': caller_selector,
                'inline_selector': inline_selector,
                'delete_inlined_method': delete_inlined_method,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_preview_selector_rename(
        connection_id,
        old_selector,
        new_selector,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            old_selector, new_selector = validated_selector_rename_pair(
                old_selector,
                new_selector,
            )
            preview = browser_session.selector_rename_preview(
                old_selector,
                new_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'old_selector': old_selector,
                'new_selector': new_selector,
                'preview': preview,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_apply_selector_rename(
        connection_id,
        old_selector,
        new_selector,
        require_observed_sender_evidence=False,
        evidence_run_id=None,
        evidence_max_age_seconds=3600,
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_apply_selector_rename is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            old_selector, new_selector = validated_selector_rename_pair(
                old_selector,
                new_selector,
            )
            require_observed_sender_evidence = validated_boolean(
                require_observed_sender_evidence,
                'require_observed_sender_evidence',
            )
            evidence_max_age_seconds = validated_positive_integer(
                evidence_max_age_seconds,
                'evidence_max_age_seconds',
            )
            evidence_validation = None
            if require_observed_sender_evidence:
                if evidence_run_id is None:
                    raise DomainException(
                        'evidence_run_id is required when require_observed_sender_evidence is true.'
                    )
                evidence_run_id = validated_non_empty_string(
                    evidence_run_id,
                    'evidence_run_id',
                )
                evidence_validation = validate_sender_evidence_for_selector(
                    connection_id,
                    old_selector,
                    evidence_run_id,
                    evidence_max_age_seconds,
                )
            result = browser_session.apply_selector_rename(
                old_selector,
                new_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'old_selector': old_selector,
                'new_selector': new_selector,
                'require_observed_sender_evidence': (
                    require_observed_sender_evidence
                ),
                'evidence_validation': evidence_validation,
                'result': result,
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_global_set(
        connection_id,
        symbol_name,
        literal_value,
        in_dictionary='UserGlobals',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_global_set is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            symbol_name = validated_identifier(symbol_name, 'symbol_name')
            literal_value = validated_literal_value(
                literal_value,
                'literal_value',
            )
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
            )
            browser_session.global_set(
                symbol_name=symbol_name,
                literal_value=literal_value,
                in_dictionary=in_dictionary,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'symbol_name': symbol_name,
                'in_dictionary': in_dictionary,
                'exists': browser_session.global_exists(
                    symbol_name,
                    in_dictionary,
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_global_remove(
        connection_id,
        symbol_name,
        in_dictionary='UserGlobals',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_global_remove is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = browser_session_for_policy(gemstone_session)
        try:
            symbol_name = validated_identifier(symbol_name, 'symbol_name')
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
            )
            browser_session.global_remove(
                symbol_name=symbol_name,
                in_dictionary=in_dictionary,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'symbol_name': symbol_name,
                'in_dictionary': in_dictionary,
                'exists': browser_session.global_exists(
                    symbol_name,
                    in_dictionary,
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_global_exists(
        connection_id,
        symbol_name,
        in_dictionary='UserGlobals',
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            symbol_name = validated_identifier(symbol_name, 'symbol_name')
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'symbol_name': symbol_name,
                'in_dictionary': in_dictionary,
                'exists': browser_session.global_exists(
                    symbol_name,
                    in_dictionary,
                ),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_run_gemstone_tests(connection_id, test_case_class_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            test_result = browser_session.run_gemstone_tests(test_case_class_name)
            return {
                'ok': True,
                'connection_id': connection_id,
                'test_case_class_name': test_case_class_name,
                'result': test_result,
                'tests_passed': test_result['has_passed'],
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_debug_eval(
        connection_id,
        source,
        reason='',
        approved_by_user=False,
        approval_note='',
    ):
        if not allow_eval:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_debug_eval is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-eval to enable.'
                ),
            )
        try:
            source = validated_non_empty_string(source, 'source')
            reason = validated_non_empty_string_stripped(reason, 'reason')
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        approval_error_response = require_explicit_user_confirmation(
            connection_id,
            'gs_debug_eval',
            'eval bypass',
            approved_by_user,
            approval_note or reason,
        )
        if approval_error_response:
            return approval_error_response
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        metadata = metadata_for_connection_id(connection_id)
        if metadata is None:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': 'Unknown connection_id.'},
            }
        try:
            output = browser_session.evaluate_source(source)
            transaction_state_effect = (
                transaction_state_effect_for_eval_source(source)
            )
            if transaction_state_effect == 'active':
                metadata['transaction_active'] = True
                if integrated_session_state.is_ide_connection_id(connection_id):
                    integrated_session_state.mark_ide_transaction_active()
            if transaction_state_effect == 'inactive':
                metadata['transaction_active'] = False
                if integrated_session_state.is_ide_connection_id(connection_id):
                    integrated_session_state.mark_ide_transaction_inactive()
            return {
                'ok': True,
                'connection_id': connection_id,
                'completed': True,
                'eval_mode': current_eval_mode(),
                'reason': reason,
                'output': output,
            }
        except GemstoneError as error:
            debug_session = GemstoneDebugSession(error)
            debug_id = add_debug_session(connection_id, debug_session)
            return {
                'ok': True,
                'connection_id': connection_id,
                'debug_id': debug_id,
                'completed': False,
                'error': gemstone_error_payload(error),
                'debug': debug_payload(debug_session),
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }

    @mcp_server.tool()
    def gs_debug_stack(connection_id, debug_id):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        return {
            'ok': True,
            'connection_id': connection_id,
            'debug_id': debug_id,
            'completed': False,
            'error': gemstone_error_payload(debug_session.exception),
            'debug': debug_payload(debug_session),
        }

    @mcp_server.tool()
    def gs_debug_continue(connection_id, debug_id):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        action_outcome = debug_session.continue_running()
        return debug_action_response(
            connection_id,
            debug_id,
            debug_session,
            action_outcome,
        )

    @mcp_server.tool()
    def gs_debug_step_over(connection_id, debug_id, level=1):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        action_outcome = debug_session.step_over(level)
        return debug_action_response(
            connection_id,
            debug_id,
            debug_session,
            action_outcome,
        )

    @mcp_server.tool()
    def gs_debug_step_into(connection_id, debug_id, level=1):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        action_outcome = debug_session.step_into(level)
        return debug_action_response(
            connection_id,
            debug_id,
            debug_session,
            action_outcome,
        )

    @mcp_server.tool()
    def gs_debug_step_through(connection_id, debug_id, level=1):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        action_outcome = debug_session.step_through(level)
        return debug_action_response(
            connection_id,
            debug_id,
            debug_session,
            action_outcome,
        )

    @mcp_server.tool()
    def gs_debug_stop(connection_id, debug_id):
        debug_session, error_response = get_active_debug_session(
            connection_id,
            debug_id,
        )
        if error_response:
            return error_response
        action_outcome = debug_session.stop()
        remove_debug_session(debug_id)
        if action_outcome.has_completed:
            return {
                'ok': True,
                'connection_id': connection_id,
                'debug_id': debug_id,
                'stopped': True,
            }
        return {
            'ok': False,
            'connection_id': connection_id,
            'debug_id': debug_id,
            'stopped': False,
            'error': gemstone_error_payload(debug_session.exception),
        }

    @mcp_server.tool()
    def gs_eval(
        connection_id,
        source,
        unsafe=False,
        reason='',
        approved_by_user=False,
        approval_note='',
    ):
        if not allow_eval:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_eval is disabled. '
                    'Start swordfish --mode mcp-headless with --allow-eval to enable.'
                ),
            )
        if not unsafe:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_eval requires unsafe=True. '
                    'Prefer explicit gs_* tools when possible.'
                ),
            )
        try:
            source = validated_non_empty_string(source, 'source')
            reason = validated_non_empty_string_stripped(reason, 'reason')
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
        approval_error_response = require_explicit_user_confirmation(
            connection_id,
            'gs_eval',
            'eval bypass',
            approved_by_user,
            approval_note or reason,
        )
        if approval_error_response:
            return approval_error_response
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        metadata = metadata_for_connection_id(connection_id)
        if metadata is None:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': 'Unknown connection_id.'},
            }

        try:
            output = browser_session.evaluate_source(source)
            transaction_state_effect = (
                transaction_state_effect_for_eval_source(source)
            )
            if transaction_state_effect == 'active':
                metadata['transaction_active'] = True
                if integrated_session_state.is_ide_connection_id(connection_id):
                    integrated_session_state.mark_ide_transaction_active()
            if transaction_state_effect == 'inactive':
                metadata['transaction_active'] = False
                if integrated_session_state.is_ide_connection_id(connection_id):
                    integrated_session_state.mark_ide_transaction_inactive()
            return {
                'ok': True,
                'connection_id': connection_id,
                'connection_mode': metadata['connection_mode'],
                'unsafe': unsafe,
                'reason': reason,
                'eval_mode': current_eval_mode(),
                'output': output,
            }
        except GemstoneError as error:
            debug_session = GemstoneDebugSession(error)
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
                'debug': {
                    'stack_frames': serialized_debug_frames(debug_session),
                },
            }
        except GemstoneApiError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
