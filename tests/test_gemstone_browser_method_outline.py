from reahl.stubble import stubclass
from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException


@stubclass(GemstoneBrowserSession)
class StubbedBrowserSession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession whose only live dependency - fetching method
    source - is replaced, so method_outline runs for real against fixed source.
    stubclass checks get_method_source still matches the real signature."""

    method_source = None

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.method_source


class MethodOutlineFixture(Fixture):
    def new_browser_session(self):
        return StubbedBrowserSession(None)

    def given_method_source(self, source):
        self.browser_session.method_source = source

    def ast_for(self, **keyword_arguments):
        return self.browser_session.method_outline(
            'Account', 'compute', True, **keyword_arguments
        )


@with_fixtures(MethodOutlineFixture)
def test_method_ast_returns_a_bodyless_outline_from_the_real_parser_by_default(fixture):
    """AI: By default gs_method_ast returns the recursive-descent structure as a bodyless outline - node_path/kind/summary/span per node, no source text - so a caller can navigate a method without paying tokens for its body."""
    fixture.given_method_source('compute\n    ^self balance + 1')
    ast = fixture.ast_for()

    assert ast['schema_version'] == 2
    assert ast['analysis_backend'] == 'swordfish_recursive_descent'
    assert ast['node_offsets_origin'] == 'zero_based'
    assert ast['nodes'][0]['node_path'] == 'method'
    assert ast['nodes'][0]['kind'] == 'method'
    assert all('source' not in entry for entry in ast['nodes'])
    paths = [entry['node_path'] for entry in ast['nodes']]
    assert 'method/statements[0]/expression' in paths


@with_fixtures(MethodOutlineFixture)
def test_include_source_attaches_each_node_exact_source_slice(fixture):
    """AI: include_source drills into the outline, attaching each node's exact source bytes - the opt-in that trades tokens for literal text only when a caller needs it."""
    source = 'compute\n    ^self balance + 1'
    fixture.given_method_source(source)
    ast = fixture.ast_for(include_source=True)

    by_path = {entry['node_path']: entry for entry in ast['nodes']}
    send = by_path['method/statements[0]/expression']
    assert send['source'] == source[send['start'] : send['end']]
    assert send['source'] == 'self balance + 1'


@with_fixtures(MethodOutlineFixture)
def test_node_path_scopes_the_outline_to_one_subtree(fixture):
    """AI: passing node_path returns only that node and its descendants - the find_symbol(name_path) analog that lets a caller zoom into one argument or block without re-receiving the whole method."""
    fixture.given_method_source('compute\n    ^self balance + 1')
    ast = fixture.ast_for(node_path='method/statements[0]/expression/arguments[0]')

    paths = [entry['node_path'] for entry in ast['nodes']]
    assert paths == ['method/statements[0]/expression/arguments[0]']
    assert ast['scope_node_path'] == 'method/statements[0]/expression/arguments[0]'
    assert ast['nodes'][0]['summary'] == '1'


@with_fixtures(MethodOutlineFixture)
def test_malformed_source_falls_back_to_the_heuristic_backend(fixture):
    """AI: a half-typed or unparseable method must not break tooling - on SmalltalkSyntaxError gs_method_ast falls back to the source heuristic, keeping the legacy statements/sends keys so existing callers still work."""
    fixture.given_method_source('compute\n    ^[ ')
    ast = fixture.ast_for()

    assert ast['analysis_backend'] == 'source_heuristic'
    assert ast['schema_version'] == 1
    assert 'sends' in ast


@with_fixtures(MethodOutlineFixture)
def test_unknown_node_path_is_rejected(fixture):
    """AI: an address that names no node is a caller error, reported as a DomainException rather than silently returning an empty outline."""
    fixture.given_method_source('compute\n    ^self balance + 1')
    with expected(DomainException):
        fixture.ast_for(node_path='method/statements[9]')
