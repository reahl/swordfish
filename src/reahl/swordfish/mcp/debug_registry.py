import uuid


debug_sessions_by_id = {}
debug_metadata_by_id = {}
debug_ids_by_connection_id = {}


def add_debug_session(connection_id, debug_session):
    debug_id = str(uuid.uuid4())
    debug_sessions_by_id[debug_id] = debug_session
    debug_metadata_by_id[debug_id] = {
        'connection_id': connection_id,
    }
    debug_ids_by_connection_id.setdefault(connection_id, set()).add(debug_id)
    return debug_id


def get_debug_session(debug_id):
    return debug_sessions_by_id[debug_id]


def get_debug_metadata(debug_id):
    return debug_metadata_by_id[debug_id]


def remove_debug_session(debug_id):
    debug_session = debug_sessions_by_id.pop(debug_id)
    metadata = debug_metadata_by_id.pop(debug_id, None)
    if metadata is not None:
        connection_id = metadata['connection_id']
        if connection_id in debug_ids_by_connection_id:
            debug_ids_by_connection_id[connection_id].discard(debug_id)
            if not debug_ids_by_connection_id[connection_id]:
                debug_ids_by_connection_id.pop(connection_id)
    return debug_session


def has_debug_session(debug_id):
    return debug_id in debug_sessions_by_id


def remove_debug_sessions_for_connection(connection_id):
    debug_ids = list(debug_ids_by_connection_id.get(connection_id, set()))
    for debug_id in debug_ids:
        remove_debug_session(debug_id)


def clear_debug_sessions():
    debug_sessions_by_id.clear()
    debug_metadata_by_id.clear()
    debug_ids_by_connection_id.clear()
