from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.smalltalk_method_parser import (
    AssignmentNode,
    BlockNode,
    CascadeNode,
    MessageSendNode,
    MethodNode,
    OverlappingSourceEditsError,
    ReturnNode,
    SmalltalkMethodParser,
    SmalltalkSyntaxError,
    SourceEdit,
    apply_source_edits,
    index_nodes_by_path,
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


@with_fixtures(ParserFixture)
def test_each_node_path_resolves_to_the_node_whose_span_is_that_path(parser_fixture):
    """AI: A node_path names a structural position; resolving it returns the node whose source span slices back to exactly the text at that position - the address an edit will target."""
    source = 'm\n    ^dictionary at: key put: 42'
    method = parser_fixture.parse(source)
    indexed = index_nodes_by_path(method)

    keyword_send = indexed['method/statements[0]/expression']
    assert keyword_send.node_path == 'method/statements[0]/expression'
    assert (
        source[keyword_send.start_offset : keyword_send.end_offset]
        == 'dictionary at: key put: 42'
    )
    argument = indexed['method/statements[0]/expression/arguments[1]']
    assert source[argument.start_offset : argument.end_offset] == '42'


@with_fixtures(ParserFixture)
def test_a_node_path_is_unchanged_when_an_unrelated_sibling_changes_text(parser_fixture):
    """AI: node_path derives from structural position, not byte offsets, so editing one statement's text leaves a later statement's address intact - the property that lets several edits to one method compose without re-fetching addresses."""
    narrow = index_nodes_by_path(parser_fixture.parse('m\n    x := 1.\n    ^x foo'))
    wide = index_nodes_by_path(parser_fixture.parse('m\n    x := 1000000.\n    ^x foo'))

    assert narrow['method/statements[1]/expression'].selector == 'foo'
    assert wide['method/statements[1]/expression'].selector == 'foo'


@with_fixtures(ParserFixture)
def test_adding_a_leading_statement_reindexes_the_paths_that_follow_it(parser_fixture):
    """AI: list roles are indexed by position, so inserting a statement shifts the indices of those after it - the one documented case where a node_path is not stable, distinct from a sibling text edit."""
    without = index_nodes_by_path(parser_fixture.parse('m\n    ^answer'))
    with_extra = index_nodes_by_path(parser_fixture.parse('m\n    answer := 1.\n    ^answer'))

    assert without['method/statements[0]'].node_kind == 'return'
    assert with_extra['method/statements[1]'].node_kind == 'return'


@with_fixtures(ParserFixture)
def test_node_summaries_describe_each_node_in_one_line_without_its_source(parser_fixture):
    """AI: an outline carries a one-line summary per node so a caller can navigate structure without paying for full bodies - selector for sends, header for blocks, value for literals, name for variables."""
    method = parser_fixture.parse(
        'm: aCollection\n    ^aCollection inject: 0 into: [:sum :each | sum + each]'
    )
    indexed = index_nodes_by_path(method)

    assert indexed['method'].describe() == 'm:'
    assert indexed['method/statements[0]/expression'].describe() == 'inject:into:'
    assert indexed['method/statements[0]/expression/receiver'].describe() == 'aCollection'
    assert indexed['method/statements[0]/expression/arguments[0]'].describe() == '0'
    block = indexed['method/statements[0]/expression/arguments[1]']
    assert block.node_kind == 'block'
    assert block.describe() == '[:sum :each |]'


@with_fixtures(ParserFixture)
def test_a_cascade_shared_receiver_is_indexed_once_not_once_per_message(parser_fixture):
    """AI: a cascade's messages share one receiver object; the path index records that receiver a single time under the cascade, so the shared node has one stable address rather than an alias per message."""
    method = parser_fixture.parse('m\n    stream nextPutAll: 1; flush')
    indexed = index_nodes_by_path(method)
    cascade = method.statements[0]

    assert indexed['method/statements[0]/receiver'] is cascade.receiver
    assert cascade.messages[0].receiver is cascade.receiver
    assert 'method/statements[0]/messages[0]/receiver' not in indexed
    assert cascade.receiver.node_path == 'method/statements[0]/receiver'


@with_fixtures(ParserFixture)
def test_apply_source_edits_replaces_a_single_targeted_span(parser_fixture):
    """AI: A SourceEdit names a half-open [start,end) range and a replacement; apply_source_edits with a single edit substitutes exactly that span and leaves the rest of the source intact."""
    source = 'oldName foo\n    ^self'
    edit = SourceEdit(0, 7, 'newName')

    assert apply_source_edits(source, [edit]) == 'newName foo\n    ^self'


@with_fixtures(ParserFixture)
def test_apply_source_edits_composes_multiple_non_overlapping_edits_regardless_of_order(
    parser_fixture,
):
    """AI: non-overlapping edits compose unambiguously: apply_source_edits sorts them by start offset and applies right-to-left, so each unapplied edit's offsets remain valid no matter what order the caller passes them in."""
    source = 'aaa bbb ccc'
    first_edit = SourceEdit(0, 3, 'AAA')
    last_edit = SourceEdit(8, 11, 'CCC')

    assert (
        apply_source_edits(source, [first_edit, last_edit])
        == apply_source_edits(source, [last_edit, first_edit])
        == 'AAA bbb CCC'
    )


@with_fixtures(ParserFixture)
def test_overlapping_source_edits_raise_OverlappingSourceEditsError(parser_fixture):
    """AI: two edits whose spans overlap have no canonical ordering, so apply_source_edits refuses them rather than producing one of several possible results - the invariant the apply mechanism rests on."""
    overlapping_first = SourceEdit(0, 5, 'X')
    overlapping_second = SourceEdit(3, 8, 'Y')

    with expected(OverlappingSourceEditsError):
        apply_source_edits('hello world', [overlapping_first, overlapping_second])


@with_fixtures(ParserFixture)
def test_as_source_edit_produces_an_edit_over_the_nodes_exact_span(parser_fixture):
    """AI: A node turns itself into a SourceEdit over its own [start,end) span when given replacement text; the node_path → edit resolver in D2 is this method, called on the node looked up by index_nodes_by_path."""
    source = 'm\n    ^x foo'
    method = parser_fixture.parse(source)
    indexed = index_nodes_by_path(method)
    unary_send = indexed['method/statements[0]/expression']

    edit = unary_send.as_source_edit('answer + 1')

    assert edit.start_offset == unary_send.start_offset
    assert edit.end_offset == unary_send.end_offset
    assert apply_source_edits(source, [edit]) == 'm\n    ^answer + 1'


@with_fixtures(ParserFixture)
def test_a_node_path_edit_leaves_a_matching_text_inside_a_string_literal_untouched(
    parser_fixture,
):
    """AI: a node-path edit targets exactly one node's source span; a string literal elsewhere whose characters happen to spell the same value is a separate LiteralNode and is left untouched - the correctness a regex replacement cannot give and the insight that makes AST-driven refactoring safe."""
    source = "m\n    ^Array with: 42 with: '42'"
    method = parser_fixture.parse(source)
    indexed = index_nodes_by_path(method)
    numeric_literal = indexed['method/statements[0]/expression/arguments[0]']

    edit = numeric_literal.as_source_edit('99')

    assert apply_source_edits(source, [edit]) == "m\n    ^Array with: 99 with: '42'"
