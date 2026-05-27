from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.smalltalk_method_parser import (
    AssignmentNode,
    BlockNode,
    CascadeNode,
    MessageSendNode,
    MethodNode,
    ReturnNode,
    SmalltalkMethodParser,
    SmalltalkSyntaxError,
)


class ParserFixture(Fixture):
    def new_parser(self):
        return SmalltalkMethodParser()

    def parse(self, source):
        return self.parser.parse_method(source)


@with_fixtures(ParserFixture)
def test_message_precedence_nests_unary_inside_binary_inside_keyword(parser_fixture):
    """AI: Smalltalk precedence is unary > binary > keyword, so 'a foo + b bar: c' is a keyword send whose first argument is a binary send whose receiver is a unary send."""
    method = parser_fixture.parse('m\n    ^a foo + b bar: c')
    return_node = method.statements[0]
    keyword_send = return_node.expression

    assert isinstance(keyword_send, MessageSendNode)
    assert keyword_send.selector == 'bar:'
    binary_send = keyword_send.receiver
    assert isinstance(binary_send, MessageSendNode)
    assert binary_send.selector == '+'
    unary_send = binary_send.receiver
    assert isinstance(unary_send, MessageSendNode)
    assert unary_send.selector == 'foo'


@with_fixtures(ParserFixture)
def test_cascade_groups_several_sends_onto_one_receiver(parser_fixture):
    """AI: A cascade sends each message to the receiver of the first send, which the AST represents as one CascadeNode over that shared receiver."""
    method = parser_fixture.parse('m\n    stream nextPutAll: 1; nl; flush')
    cascade = method.statements[0]

    assert isinstance(cascade, CascadeNode)
    assert [send.selector for send in cascade.messages] == [
        'nextPutAll:',
        'nl',
        'flush',
    ]


@with_fixtures(ParserFixture)
def test_block_owns_its_arguments_and_temporaries_as_a_scope(parser_fixture):
    """AI: A block is the unit of lexical scope; its arguments and temporaries belong to the BlockNode, which is what lets extract/rename reason about shadowing."""
    method = parser_fixture.parse('m\n    ^[:each | | tally | tally := each]')
    block = method.statements[0].expression

    assert isinstance(block, BlockNode)
    assert block.argument_names == ['each']
    assert block.temporaries == ['tally']
    assert isinstance(block.statements[0], AssignmentNode)


@with_fixtures(ParserFixture)
def test_method_header_yields_selector_arguments_and_temporaries(parser_fixture):
    """AI: Parsing the method header recovers the selector, its argument names and the method-level temporaries — the facts a signature-changing refactoring needs."""
    method = parser_fixture.parse('at: anIndex put: aValue\n    | slot |\n    ^slot')

    assert isinstance(method, MethodNode)
    assert method.selector == 'at:put:'
    assert method.argument_names == ['anIndex', 'aValue']
    assert method.temporaries == ['slot']
    assert isinstance(method.statements[0], ReturnNode)


@with_fixtures(ParserFixture)
def test_every_node_span_slices_back_to_its_exact_source(parser_fixture):
    """AI: Each node records the [start,end) source span it covers, so an edit can replace a node by its bytes — the property that makes AST-driven refactoring safe."""
    source = 'm\n    ^self foo + 2'
    method = parser_fixture.parse(source)
    binary_send = method.statements[0].expression

    assert source[binary_send.start_offset : binary_send.end_offset] == 'self foo + 2'
    unary_send = binary_send.receiver
    assert source[unary_send.start_offset : unary_send.end_offset] == 'self foo'


@with_fixtures(ParserFixture)
def test_method_pragma_is_captured_and_the_following_body_still_parses(parser_fixture):
    """AI: A primitive pragma precedes the body in many kernel methods; it is captured on the method and the statements after it parse normally."""
    method = parser_fixture.parse(
        'size\n    <primitive: 60>\n    ^self _basicSize'
    )

    assert method.pragmas == ['<primitive: 60>']
    assert isinstance(method.statements[0], ReturnNode)


@with_fixtures(ParserFixture)
def test_block_argument_may_have_whitespace_after_the_colon(parser_fixture):
    """AI: GemStone allows a space between the colon and a block argument name ('[: each | ...]'); it must still bind as the block's argument."""
    method = parser_fixture.parse('m\n    ^[: each | each]')
    block = method.statements[0].expression

    assert isinstance(block, BlockNode)
    assert block.argument_names == ['each']


@with_fixtures(ParserFixture)
def test_a_method_whose_selector_is_the_bar_operator_parses(parser_fixture):
    """AI: '|' is a genuine binary selector, so the header '| aBoolean' defines the binary method '|' (as Boolean>>| does)."""
    method = parser_fixture.parse('| aBoolean\n    ^aBoolean')

    assert method.selector == '|'
    assert method.argument_names == ['aBoolean']


@with_fixtures(ParserFixture)
def test_unbalanced_block_is_reported_as_a_syntax_error(parser_fixture):
    """AI: A malformed method raises SmalltalkSyntaxError so callers can fall back to the heuristic rather than acting on a broken tree."""
    with expected(SmalltalkSyntaxError):
        parser_fixture.parse('m\n    ^[:each | each')
