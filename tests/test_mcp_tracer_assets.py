from hashlib import sha256

from reahl.swordfish.mcp.tracer_assets import tracer_source
from reahl.swordfish.mcp.tracer_assets import tracer_source_hash
from reahl.swordfish.mcp.tracer_assets import TRACER_VERSION


def test_tracer_source_hash_matches_source_contents():
    source = tracer_source()
    assert 'SwordfishMcpTracer' in source
    assert tracer_source_hash() == sha256(source.encode('utf-8')).hexdigest()
    assert TRACER_VERSION
