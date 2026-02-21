from hashlib import sha256
from pkgutil import get_data


TRACER_VERSION = '2'
TRACER_RESOURCE_PACKAGE = 'reahl.swordfish.mcp.tracing'
TRACER_RESOURCE_NAME = 'swordfish_mcp_tracer.st'


def tracer_source():
    tracer_source_bytes = get_data(
        TRACER_RESOURCE_PACKAGE,
        TRACER_RESOURCE_NAME,
    )
    if tracer_source_bytes is None:
        raise FileNotFoundError(
            'Tracer source asset could not be loaded from package data.'
        )
    return tracer_source_bytes.decode('utf-8')


def tracer_source_hash():
    return sha256(tracer_source().encode('utf-8')).hexdigest()
