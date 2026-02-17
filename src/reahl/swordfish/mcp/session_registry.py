import uuid


sessions_by_connection_id = {}
metadata_by_connection_id = {}


def add_connection(gemstone_session, metadata):
    connection_id = str(uuid.uuid4())
    sessions_by_connection_id[connection_id] = gemstone_session
    metadata_by_connection_id[connection_id] = metadata
    return connection_id


def get_session(connection_id):
    return sessions_by_connection_id[connection_id]


def get_metadata(connection_id):
    return metadata_by_connection_id[connection_id]


def remove_connection(connection_id):
    gemstone_session = sessions_by_connection_id.pop(connection_id)
    metadata_by_connection_id.pop(connection_id, None)
    return gemstone_session


def has_connection(connection_id):
    return connection_id in sessions_by_connection_id


def clear_connections():
    sessions_by_connection_id.clear()
    metadata_by_connection_id.clear()
