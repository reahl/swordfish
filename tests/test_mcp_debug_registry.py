from reahl.tofu import NoException
from reahl.tofu import expected

from reahl.swordfish.mcp.debug_registry import add_debug_session
from reahl.swordfish.mcp.debug_registry import clear_debug_sessions
from reahl.swordfish.mcp.debug_registry import get_debug_metadata
from reahl.swordfish.mcp.debug_registry import get_debug_session
from reahl.swordfish.mcp.debug_registry import has_debug_session
from reahl.swordfish.mcp.debug_registry import remove_debug_session
from reahl.swordfish.mcp.debug_registry import remove_debug_sessions_for_connection


def test_add_and_remove_debug_session():
    with expected(NoException):
        clear_debug_sessions()
    debug_session = object()

    with expected(NoException):
        debug_id = add_debug_session('connection-1', debug_session)

    assert has_debug_session(debug_id)
    assert get_debug_session(debug_id) is debug_session
    assert get_debug_metadata(debug_id)['connection_id'] == 'connection-1'

    with expected(NoException):
        removed_debug_session = remove_debug_session(debug_id)
    assert removed_debug_session is debug_session
    assert not has_debug_session(debug_id)

    with expected(NoException):
        clear_debug_sessions()


def test_remove_debug_sessions_for_connection():
    with expected(NoException):
        clear_debug_sessions()
    debug_session_one = object()
    debug_session_two = object()

    with expected(NoException):
        first_debug_id = add_debug_session('connection-1', debug_session_one)
        second_debug_id = add_debug_session('connection-1', debug_session_two)

    assert has_debug_session(first_debug_id)
    assert has_debug_session(second_debug_id)

    with expected(NoException):
        remove_debug_sessions_for_connection('connection-1')

    assert not has_debug_session(first_debug_id)
    assert not has_debug_session(second_debug_id)

    with expected(NoException):
        clear_debug_sessions()
