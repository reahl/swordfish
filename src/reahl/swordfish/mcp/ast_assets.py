from hashlib import sha256
from pkgutil import get_data


AST_SUPPORT_VERSION = '1'
AST_SUPPORT_RESOURCE_PACKAGE = 'reahl.swordfish.mcp.ast'
AST_SUPPORT_RESOURCE_NAME = 'swordfish_mcp_ast_support.st'


def ast_support_source():
    source_bytes = get_data(
        AST_SUPPORT_RESOURCE_PACKAGE,
        AST_SUPPORT_RESOURCE_NAME,
    )
    if source_bytes is None:
        raise FileNotFoundError(
            'AST support source asset could not be loaded from package data.'
        )
    return source_bytes.decode('utf-8')


def ast_support_source_hash():
    return sha256(ast_support_source().encode('utf-8')).hexdigest()
