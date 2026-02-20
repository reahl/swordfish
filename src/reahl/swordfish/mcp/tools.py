import re

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


def register_tools(
    mcp_server,
    allow_eval=False,
    allow_compile=False,
):
    identifier_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    unary_selector_pattern = re.compile('^[A-Za-z][A-Za-z0-9_]*$')
    keyword_selector_pattern = re.compile('^([A-Za-z][A-Za-z0-9_]*:)+$')

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
    def gs_commit(connection_id):
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
    def gs_find_implementors(connection_id, method_name):
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            return {
                'ok': True,
                'connection_id': connection_id,
                'method_name': method_name,
                'implementors': browser_session.find_implementors(method_name),
            }
        except GemstoneError as error:
            return {
                'ok': False,
                'connection_id': connection_id,
                'error': gemstone_error_payload(error),
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
            result = browser_session.apply_selector_rename(
                old_selector,
                new_selector,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
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
