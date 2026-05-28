from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class StubbedQuerySession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession whose scope-enumeration and source-fetch leaves
    are stubbed from a fixed {(class, selector): source} map, so the real
    node-level query_methods_by_ast_pattern runs offline. stubclass checks every
    override still matches the real signature."""

    methods = {}

    def query_scope_class_names(self, package_name, class_name):
        return sorted({scoped_class for (scoped_class, selector) in self.methods})

    def selector_names_for_scope(self, class_name, show_instance_side, method_category):
        return [
            selector
            for (scoped_class, selector) in self.methods
            if scoped_class == class_name
        ]

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.methods[(class_name, method_selector)]

    def get_method_category(self, class_name, method_selector, show_instance_side):
        return 'testing'


class AstPatternFixture(Fixture):
    def new_browser_session(self):
        return StubbedQuerySession(None)

    def given_methods(self, methods):
        self.browser_session.methods = methods

    def query(self, ast_pattern, **keyword_arguments):
        return self.browser_session.query_methods_by_ast_pattern(
            ast_pattern, **keyword_arguments
        )


@with_fixtures(AstPatternFixture)
def test_query_locates_every_send_of_a_selector_with_its_node_path(fixture):
    """AI: A node-level pattern locates each matching node and returns its address - here every send of 'at:put:' across the scope - so the result says where the call is, not merely that some method contains one. A selector inside a string is a literal, not a send, so it is excluded."""
    fixture.given_methods(
        {
            ('Account', 'store'): 'store\n    ^dictionary at: #k put: 1',
            ('Account', 'plain'): 'plain\n    ^42',
            ('Account', 'mentions'): "mentions\n    ^'at:put: text'",
        }
    )
    result = fixture.query(
        {'node_kind': 'message_send', 'selector': 'at:put:'}, class_name='Account'
    )

    assert len(result['matches']) == 1
    match = result['matches'][0]
    assert match['method_selector'] == 'store'
    assert match['node_path'] == 'method/statements[0]/expression'
    assert match['kind'] == 'message_send'
    assert match['summary'] == 'at:put:'
    assert result['scanned_method_count'] == 3


@with_fixtures(AstPatternFixture)
def test_query_locates_blocks_by_their_nesting_depth(fixture):
    """AI: min_nesting_depth selects nodes by how many blocks enclose them - the structural query the old aggregate counts could not express - so a caller can find a block nested inside another block."""
    fixture.given_methods({('Widget', 'nested'): 'nested\n    ^[ [ :x | x ] ] value'})
    result = fixture.query(
        {'node_kind': 'block', 'min_nesting_depth': 1}, class_name='Widget'
    )

    assert len(result['matches']) == 1
    assert result['matches'][0]['kind'] == 'block'
    assert result['matches'][0]['summary'] == '[:x |]'


@with_fixtures(AstPatternFixture)
def test_query_filters_sends_by_send_kind(fixture):
    """AI: send_kind narrows matches to unary, binary or keyword sends, so a caller can ask for only binary sends regardless of selector."""
    fixture.given_methods({('Account', 'mixed'): 'mixed\n    ^self at: 1 put: (2 + 3)'})
    result = fixture.query(
        {'node_kind': 'message_send', 'send_kind': 'binary'}, class_name='Account'
    )

    assert len(result['matches']) == 1
    assert result['matches'][0]['summary'] == '+'


@with_fixtures(AstPatternFixture)
def test_query_skips_a_method_that_does_not_parse(fixture):
    """AI: node-level matching needs a parse tree; a method whose source will not parse is scanned but yields no node matches rather than aborting the whole query."""
    fixture.given_methods(
        {
            ('Account', 'good'): 'good\n    ^self foo',
            ('Account', 'broken'): 'broken\n    ^[ ',
        }
    )
    result = fixture.query(
        {'node_kind': 'message_send', 'selector': 'foo'}, class_name='Account'
    )

    assert [match['method_selector'] for match in result['matches']] == ['good']
    assert result['scanned_method_count'] == 2


@with_fixtures(AstPatternFixture)
def test_query_truncates_to_max_results_and_flags_truncation(fixture):
    """AI: max_results bounds the number of node matches returned and the result flags that it was truncated, so a broad structural query stays affordable."""
    fixture.given_methods({('Account', 'many'): 'many\n    self a. self b. self c'})
    result = fixture.query(
        {'node_kind': 'message_send'}, class_name='Account', max_results=2
    )

    assert len(result['matches']) == 2
    assert result['truncated'] is True
