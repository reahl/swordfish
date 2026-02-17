from reahl.tofu import NoException
from reahl.tofu import expected

from reahl.swordfish.mcp.session_registry import add_connection
from reahl.swordfish.mcp.session_registry import clear_connections
from reahl.swordfish.mcp.session_registry import get_metadata
from reahl.swordfish.mcp.session_registry import get_session
from reahl.swordfish.mcp.session_registry import has_connection
from reahl.swordfish.mcp.session_registry import remove_connection


def test_add_and_remove_connection():
    with expected(NoException):
        clear_connections()
    session = object()
    metadata = {'connection_mode': 'linked'}

    with expected(NoException):
        connection_id = add_connection(session, metadata)

    assert has_connection(connection_id)
    assert get_session(connection_id) is session
    assert get_metadata(connection_id) == metadata

    with expected(NoException):
        removed_session = remove_connection(connection_id)

    assert removed_session is session
    assert not has_connection(connection_id)
    with expected(NoException):
        clear_connections()
