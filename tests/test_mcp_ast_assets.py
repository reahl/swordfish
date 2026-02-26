from hashlib import sha256

from reahl.swordfish.mcp.ast_assets import ast_support_source
from reahl.swordfish.mcp.ast_assets import ast_support_source_hash
from reahl.swordfish.mcp.ast_assets import AST_SUPPORT_VERSION


def test_ast_support_source_hash_matches_source_contents():
    source = ast_support_source()
    assert 'SwordfishMcpAstSupport' in source
    assert 'objectNamed: #Swordfish' in source
    assert ast_support_source_hash() == sha256(source.encode('utf-8')).hexdigest()
    assert AST_SUPPORT_VERSION
