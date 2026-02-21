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
from reahl.swordfish.mcp.tracer_assets import tracer_source
from reahl.swordfish.mcp.tracer_assets import tracer_source_hash
from reahl.swordfish.mcp.tracer_assets import TRACER_VERSION


def register_tools(
    mcp_server,
    allow_eval=False,
    allow_compile=False,
    allow_commit=False,
    allow_tracing=False,
):
    identifier_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    unary_selector_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    keyword_selector_pattern = re.compile('^([A-Za-z][A-Za-z0-9_]*:)+$')
    tracer_alias_selector_prefix = 'swordfishMcpTracerOriginal__'
    collected_sender_evidence = {}
    planned_sender_tests = {}

    def get_active_session(connection_id):
        if not has_connection(connection_id):
            return None, {
                'ok': False,
                'error': {
                    'message': 'Unknown connection_id.',
                },
            }
        return get_session(connection_id), None

    def require_active_transaction(connection_id):
        metadata = get_metadata(connection_id)
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
        return GemstoneBrowserSession(gemstone_session), None

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
                'Start swordfish-mcp with --allow-tracing to enable.'
            )
            % tool_name,
        )

    def require_tracing_enabled(connection_id, tool_name):
        if allow_tracing:
            return None
        return tracing_disabled_tool_response(connection_id, tool_name)

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

    def tracer_status_for_browser_session(browser_session):
        expected_source_hash = tracer_source_hash()
        expected_version = TRACER_VERSION
        manifest_exists = browser_session.run_code(
            'UserGlobals includesKey: #SwordfishMcpTracerManifest'
        ).to_py
        installed_source_hash = ''
        installed_version = ''
        installed_at = ''
        observed_selector_count = 0
        observed_edge_count = 0
        enabled = browser_session.run_code(
            'UserGlobals at: #SwordfishMcpTracerEnabled ifAbsent: [ false ]'
        ).to_py
        observed_selector_count = browser_session.run_code(
            (
                '(UserGlobals at: #SwordfishMcpTracerEdgeCounts ifAbsent: [ Dictionary new ]) '
                'size'
            )
        ).to_py
        observed_edge_count = browser_session.run_code(
            (
                '| edgeCounts edgeTotal |\n'
                'edgeCounts := UserGlobals\n'
                '    at: #SwordfishMcpTracerEdgeCounts\n'
                '    ifAbsent: [ Dictionary new ].\n'
                'edgeTotal := 0.\n'
                'edgeCounts valuesDo: [ :selectorEdgeCounts |\n'
                '    edgeTotal := edgeTotal + selectorEdgeCounts size\n'
                '].\n'
                'edgeTotal'
            )
        ).to_py
        if manifest_exists:
            installed_source_hash = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpTracerManifest) '
                    "at: #sourceHash ifAbsent: ['']"
                )
            ).to_py
            installed_version = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpTracerManifest) '
                    "at: #version ifAbsent: ['']"
                )
            ).to_py
            installed_at = browser_session.run_code(
                (
                    '(UserGlobals at: #SwordfishMcpTracerManifest) '
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
            'tracer_installed': manifest_exists,
            'tracer_enabled': enabled,
            'expected_version': expected_version,
            'installed_version': installed_version,
            'versions_match': versions_match,
            'expected_source_hash': expected_source_hash,
            'installed_source_hash': installed_source_hash,
            'hashes_match': hashes_match,
            'manifest_matches': manifest_matches,
            'installed_at': installed_at,
            'observed_selector_count': observed_selector_count,
            'observed_edge_count': observed_edge_count,
        }

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
            'swordfish-mcp'
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
        browser_session.run_code(tracer_source())
        install_tracer_methods(browser_session)
        browser_session.run_code(
            tracer_manifest_install_script(browser_session)
        )
        browser_session.run_code('SwordfishMcpTracer clearEdgeCounts')

    def ensure_tracer_manifest_matches(browser_session):
        tracer_status = tracer_status_for_browser_session(browser_session)
        if not tracer_status['manifest_matches']:
            install_tracer_in_browser_session(browser_session)
            tracer_status = tracer_status_for_browser_session(browser_session)
        return tracer_status

    def enable_tracer_in_browser_session(browser_session):
        browser_session.run_code(
            'UserGlobals at: #SwordfishMcpTracerEnabled put: true. true'
        )

    def trace_selector_in_browser_session(
        browser_session,
        method_name,
        max_results,
    ):
        browser_session.run_code(
            'SwordfishMcpTracer clearInstrumentationForTarget: %s'
            % browser_session.selector_reference_expression(method_name)
        )
        sender_search_result = browser_session.find_senders(
            method_name,
            max_results=max_results,
            count_only=False,
        )
        traced_senders = []
        skipped_senders = []
        for sender_entry in sender_search_result['senders']:
            class_name = sender_entry['class_name']
            show_instance_side = sender_entry['show_instance_side']
            sender_method_selector = sender_entry['method_selector']
            alias_selector = tracer_alias_selector(sender_method_selector)
            selectors = browser_session.list_methods(
                class_name,
                'all',
                show_instance_side,
            )
            if alias_selector in selectors:
                skipped_senders.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': show_instance_side,
                        'method_selector': sender_method_selector,
                        'alias_selector': alias_selector,
                    }
                )
            else:
                method_source = browser_session.get_method_source(
                    class_name,
                    sender_method_selector,
                    show_instance_side,
                )
                method_category = browser_session.get_method_category(
                    class_name,
                    sender_method_selector,
                    show_instance_side,
                )
                alias_method_source = source_with_rewritten_method_header(
                    browser_session,
                    method_source,
                    sender_method_selector,
                    alias_selector,
                )
                browser_session.compile_method(
                    class_name,
                    show_instance_side,
                    alias_method_source,
                    method_category,
                )
                wrapper_method_source = tracer_sender_wrapper_source(
                    browser_session,
                    sender_method_selector,
                    alias_selector,
                    method_name,
                    class_name,
                    show_instance_side,
                )
                browser_session.compile_method(
                    class_name,
                    show_instance_side,
                    wrapper_method_source,
                    method_category,
                )
                traced_senders.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': show_instance_side,
                        'method_selector': sender_method_selector,
                        'alias_selector': alias_selector,
                    }
                )
            browser_session.run_code(
                (
                    'SwordfishMcpTracer '
                    'registerInstrumentationForTarget: %s '
                    'callerClassName: %s '
                    'callerMethodSelector: %s '
                    'callerShowInstanceSide: %s '
                    'aliasSelector: %s'
                )
                % (
                    browser_session.selector_reference_expression(
                        method_name
                    ),
                    browser_session.smalltalk_string_literal(class_name),
                    browser_session.selector_reference_expression(
                        sender_method_selector
                    ),
                    'true' if show_instance_side else 'false',
                    browser_session.selector_reference_expression(
                        alias_selector
                    ),
                )
            )
        return {
            'method_name': method_name,
            'max_results': max_results,
            'total_sender_count': sender_search_result['total_count'],
            'targeted_sender_count': len(sender_search_result['senders']),
            'traced_sender_count': len(traced_senders),
            'skipped_sender_count': len(skipped_senders),
            'traced_senders': traced_senders,
            'skipped_senders': skipped_senders,
        }

    def untrace_selector_in_browser_session(browser_session, method_name):
        instrumentation_entries_report = browser_session.run_code(
            'SwordfishMcpTracer instrumentationReportForTarget: %s'
            % browser_session.selector_reference_expression(method_name)
        ).to_py
        instrumentation_entry_lines = (
            []
            if instrumentation_entries_report == ''
            else instrumentation_entries_report.splitlines()
        )
        restored_senders = []
        skipped_senders = []
        for instrumentation_entry_line in instrumentation_entry_lines:
            instrumentation_entry_fields = instrumentation_entry_line.split('|')
            if len(instrumentation_entry_fields) != 4:
                raise DomainException(
                    'Instrumentation entry must have four fields.'
                )
            class_name = instrumentation_entry_fields[0]
            show_instance_side = instrumentation_entry_fields[1] == 'true'
            sender_method_selector = instrumentation_entry_fields[2]
            alias_selector = instrumentation_entry_fields[3]
            selectors = browser_session.list_methods(
                class_name,
                'all',
                show_instance_side,
            )
            if alias_selector not in selectors:
                skipped_senders.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': show_instance_side,
                        'method_selector': sender_method_selector,
                        'alias_selector': alias_selector,
                    }
                )
            else:
                alias_method_source = browser_session.get_method_source(
                    class_name,
                    alias_selector,
                    show_instance_side,
                )
                alias_method_category = browser_session.get_method_category(
                    class_name,
                    alias_selector,
                    show_instance_side,
                )
                restored_method_source = source_with_rewritten_method_header(
                    browser_session,
                    alias_method_source,
                    alias_selector,
                    sender_method_selector,
                )
                browser_session.compile_method(
                    class_name,
                    show_instance_side,
                    restored_method_source,
                    alias_method_category,
                )
                browser_session.delete_method(
                    class_name,
                    alias_selector,
                    show_instance_side,
                )
                restored_senders.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': show_instance_side,
                        'method_selector': sender_method_selector,
                        'alias_selector': alias_selector,
                    }
                )
        browser_session.run_code(
            'SwordfishMcpTracer clearInstrumentationForTarget: %s'
            % browser_session.selector_reference_expression(method_name)
        )
        return {
            'method_name': method_name,
            'total_instrumented_sender_count': len(
                instrumentation_entry_lines
            ),
            'restored_sender_count': len(restored_senders),
            'skipped_sender_count': len(skipped_senders),
            'restored_senders': restored_senders,
            'skipped_senders': skipped_senders,
        }

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
        selector_queue = [{'selector': method_name, 'depth': 0}]
        queued_selector_names = {method_name}
        visited_selector_names = set()
        queue_index = 0
        visited_selector_count = 0
        sender_search_truncated = False
        class_is_test_case = {}
        candidate_tests_by_key = {}
        sender_edges = []
        while queue_index < len(selector_queue):
            selector_item = selector_queue[queue_index]
            queue_index += 1
            can_visit_more_selectors = visited_selector_count < max_nodes
            selector_name = selector_item['selector']
            is_unseen_selector = selector_name not in visited_selector_names
            if can_visit_more_selectors and is_unseen_selector:
                visited_selector_names.add(selector_name)
                visited_selector_count += 1
                selector_depth = selector_item['depth']
                sender_search_result = browser_session.find_senders(
                    selector_name,
                    max_results=max_senders_per_selector,
                    count_only=False,
                )
                selector_result_was_truncated = (
                    sender_search_result['returned_count']
                    < sender_search_result['total_count']
                )
                if selector_result_was_truncated:
                    sender_search_truncated = True
                for sender_entry in sender_search_result['senders']:
                    sender_class_name = sender_entry['class_name']
                    sender_method_selector = sender_entry['method_selector']
                    sender_depth = selector_depth + 1
                    sender_edges.append(
                        {
                            'from_selector': selector_name,
                            'to_class_name': sender_class_name,
                            'to_method_selector': sender_method_selector,
                            'to_show_instance_side': sender_entry[
                                'show_instance_side'
                            ],
                            'depth': sender_depth,
                        }
                    )
                    is_test_method_name = (
                        sender_entry['show_instance_side']
                        and sender_method_selector.startswith('test')
                    )
                    if is_test_method_name:
                        if sender_class_name not in class_is_test_case:
                            class_is_test_case[sender_class_name] = (
                                browser_session.class_inherits_from(
                                    sender_class_name,
                                    'TestCase',
                                )
                            )
                        if class_is_test_case[sender_class_name]:
                            sender_key = (
                                sender_class_name,
                                sender_method_selector,
                            )
                            has_capacity_for_new_test = (
                                len(candidate_tests_by_key)
                                < max_test_methods
                            )
                            if (
                                sender_key not in candidate_tests_by_key
                                and has_capacity_for_new_test
                            ):
                                candidate_tests_by_key[sender_key] = {
                                    'test_case_class_name': sender_class_name,
                                    'test_method_selector': sender_method_selector,
                                    'depth': sender_depth,
                                    'reached_from_selector': selector_name,
                                }
                    can_expand_depth = selector_depth < max_depth
                    can_enqueue_more_selectors = (
                        len(queued_selector_names) < max_nodes
                    )
                    if (
                        can_expand_depth
                        and can_enqueue_more_selectors
                        and sender_method_selector not in queued_selector_names
                    ):
                        selector_queue.append(
                            {
                                'selector': sender_method_selector,
                                'depth': sender_depth,
                            }
                        )
                        queued_selector_names.add(sender_method_selector)
        candidate_tests = sorted(
            candidate_tests_by_key.values(),
            key=lambda candidate_test: (
                candidate_test['depth'],
                candidate_test['test_case_class_name'],
                candidate_test['test_method_selector'],
            ),
        )
        selector_limit_reached = visited_selector_count >= max_nodes
        return {
            'method_name': method_name,
            'max_depth': max_depth,
            'max_nodes': max_nodes,
            'max_senders_per_selector': max_senders_per_selector,
            'max_test_methods': max_test_methods,
            'visited_selector_count': visited_selector_count,
            'sender_edge_count': len(sender_edges),
            'sender_search_truncated': sender_search_truncated,
            'selector_limit_reached': selector_limit_reached,
            'candidate_test_count': len(candidate_tests),
            'candidate_tests': candidate_tests,
            'sender_edges': sender_edges,
        }

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
        selector_expression = browser_session.selector_reference_expression(
            method_name
        )
        observed_edges_report = browser_session.run_code(
            'SwordfishMcpTracer observedEdgesReportFor: %s'
            % selector_expression
        ).to_py
        observed_sender_entries = []
        observed_edge_lines = (
            []
            if observed_edges_report == ''
            else observed_edges_report.splitlines()
        )
        for observed_edge_line in observed_edge_lines:
            observed_edge_fields = observed_edge_line.split('|')
            if len(observed_edge_fields) != 4:
                raise DomainException(
                    'Observed tracer edge must have four fields.'
                )
            caller_class_name = observed_edge_fields[0]
            caller_show_instance_side = observed_edge_fields[1] == 'true'
            caller_method_selector = observed_edge_fields[2]
            observed_count = int(observed_edge_fields[3])
            observed_sender_entries.append(
                {
                    'caller_class_name': caller_class_name,
                    'caller_show_instance_side': caller_show_instance_side,
                    'caller_method_selector': caller_method_selector,
                    'method_selector': method_name,
                    'observed_count': observed_count,
                }
            )
        observed_sender_entries = sorted(
            observed_sender_entries,
            key=lambda observed_sender_entry: (
                observed_sender_entry['caller_class_name'],
                observed_sender_entry['caller_show_instance_side'],
                observed_sender_entry['caller_method_selector'],
            ),
        )
        total_count = len(observed_sender_entries)
        returned_entries = (
            []
            if count_only
            else browser_session.limited_entries(
                observed_sender_entries,
                max_results,
            )
        )
        return {
            'total_count': total_count,
            'returned_count': len(returned_entries),
            'total_observed_calls': sum(
                [
                    observed_sender_entry['observed_count']
                    for observed_sender_entry in observed_sender_entries
                ]
            ),
            'observed_senders': returned_entries,
        }

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
        gemstone_user_name,
        gemstone_password,
        stone_name='gs64stone',
        rpc_hostname='localhost',
        netldi_name='gemnetobject',
    ):
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
            get_metadata(connection_id)['transaction_active'] = True
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
        metadata = get_metadata(connection_id)
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
    def gs_commit(connection_id):
        if not allow_commit:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_commit is disabled. '
                    'Start swordfish-mcp with --allow-commit to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        try:
            commit_transaction(gemstone_session)
            get_metadata(connection_id)['transaction_active'] = False
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
        metadata = get_metadata(connection_id)
        return {
            'ok': True,
            'connection_id': connection_id,
            'connection_mode': metadata['connection_mode'],
            'transaction_active': metadata.get('transaction_active', False),
        }

    @mcp_server.tool()
    def gs_abort(connection_id):
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        try:
            abort_transaction(gemstone_session)
            get_metadata(connection_id)['transaction_active'] = False
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
    def gs_list_method_categories(
        connection_id,
        class_name,
        show_instance_side=True,
    ):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            browser_session.run_code(
                'UserGlobals at: #SwordfishMcpTracerEnabled put: false. true'
            )
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            browser_session.run_code(
                (
                    'UserGlobals removeKey: #SwordfishMcpTracerManifest '
                    'ifAbsent: [ ].\n'
                    'UserGlobals removeKey: #SwordfishMcpTracerEdgeCounts '
                    'ifAbsent: [ ].\n'
                    'UserGlobals removeKey: #SwordfishMcpTracerInstrumentation '
                    'ifAbsent: [ ].\n'
                    'UserGlobals at: #SwordfishMcpTracerEnabled put: false.\n'
                    'true'
                )
            )
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            if method_name is None:
                browser_session.run_code('SwordfishMcpTracer clearEdgeCounts')
            else:
                method_name = validated_selector(method_name, 'method_name')
                method_name_literal = browser_session.smalltalk_string_literal(
                    method_name
                )
                browser_session.run_code(
                    '(SwordfishMcpTracer edgeCounts) removeKey: %s ifAbsent: [ ]. true'
                    % method_name_literal
                )
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
                    'Start swordfish-mcp with --allow-compile to enable.'
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
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                browser_session.run_code(
                    '(SwordfishMcpTracer edgeCounts) removeKey: %s ifAbsent: [ ]. true'
                    % browser_session.smalltalk_string_literal(method_name)
                )
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
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_compile_method is disabled. '
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            source = validated_non_empty_string(source, 'source')
            method_category = validated_non_empty_string(
                method_category,
                'method_category',
            )
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
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_create_class is disabled. '
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            superclass_name = validated_identifier(
                superclass_name,
                'superclass_name',
            )
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
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
    def gs_create_test_case_class(
        connection_id,
        class_name,
        in_dictionary='UserGlobals',
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_create_test_case_class is disabled. '
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            in_dictionary = validated_identifier(
                in_dictionary,
                'in_dictionary',
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
        try:
            class_name = validated_identifier(class_name, 'class_name')
            method_selector = validated_non_empty_string(
                method_selector,
                'method_selector',
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
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
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        gemstone_session, error_response = get_active_session(connection_id)
        if error_response:
            return error_response
        transaction_error_response = require_active_transaction(connection_id)
        if transaction_error_response:
            return transaction_error_response
        browser_session = GemstoneBrowserSession(gemstone_session)
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
    def gs_debug_eval(connection_id, source):
        if not allow_eval:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_debug_eval is disabled. '
                    'Start swordfish-mcp with --allow-eval to enable.'
                ),
            )
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            output = browser_session.evaluate_source(source)
            return {
                'ok': True,
                'connection_id': connection_id,
                'completed': True,
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
    ):
        if not allow_eval:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_eval is disabled. '
                    'Start swordfish-mcp with --allow-eval to enable.'
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
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        metadata = get_metadata(connection_id)

        try:
            source = validated_non_empty_string(source, 'source')
            if reason is not None:
                if not isinstance(reason, str):
                    raise DomainException('reason must be a string.')
            output = browser_session.evaluate_source(source)
            return {
                'ok': True,
                'connection_id': connection_id,
                'connection_mode': metadata['connection_mode'],
                'unsafe': unsafe,
                'reason': reason,
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
        except DomainException as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': {'message': str(error)},
            }
