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
    def get_active_session(connection_id):
        if not has_connection(connection_id):
            return None, {
                'ok': False,
                'error': {
                    'message': 'Unknown connection_id.',
                },
            }
        return get_session(connection_id), None

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
            {'connection_mode': connection_mode},
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
    ):
        if not allow_compile:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_compile_method is disabled. '
                    'Start swordfish-mcp with --allow-compile to enable.'
                ),
            )
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        try:
            browser_session.compile_method(
                class_name,
                show_instance_side,
                source,
            )
            return {
                'ok': True,
                'connection_id': connection_id,
                'class_name': class_name,
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
    def gs_eval(connection_id, source):
        if not allow_eval:
            return disabled_tool_response(
                connection_id,
                (
                    'gs_eval is disabled. '
                    'Start swordfish-mcp with --allow-eval to enable.'
                ),
            )
        browser_session, error_response = get_browser_session(connection_id)
        if error_response:
            return error_response
        metadata = get_metadata(connection_id)

        try:
            output = browser_session.evaluate_source(source)
            return {
                'ok': True,
                'connection_id': connection_id,
                'connection_mode': metadata['connection_mode'],
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
