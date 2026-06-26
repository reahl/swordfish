"""Parses GemStone Smalltalk method source into an abstract syntax tree.

This is a hand-written recursive-descent parser built directly on the shared
SmalltalkSourceScanner. It depends on nothing from GemStone, so it produces the
same tree whether the IDE is connected to an image or not, and on the barest
image (which ships no RBParser). The tree it returns is what AST-driven
refactorings reason about; callers fall back to the source heuristic when
parsing raises SmalltalkSyntaxError.
"""

from reahl.swordfish.gemstone.smalltalk_source_scanner import (
    SmalltalkSourceScanner,
    SmalltalkTokenKind,
)


class SmalltalkSyntaxError(Exception):
    """Raised when source cannot be parsed into a well-formed method tree."""



class OverlappingSourceEditsError(Exception):
    """AI: Raised by apply_source_edits when two edits' source spans overlap. Overlapping
    edits have no canonical ordering and would silently lose one or the other, so the apply
    mechanism refuses them rather than producing an ambiguous result."""


class SourceEdit:
    """AI: A delta against a source string - replace text[start_offset:end_offset) with
    replacement. Carries no AST identity of its own: SyntaxNode.as_source_edit builds one over
    a node's exact span, while a caller can construct one directly for sub-node edits (e.g.
    a selector token inside a MessageSendNode, where the selector is not its own AST node)."""

    def __init__(self, start_offset, end_offset, replacement):
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.replacement = replacement


class SyntaxNode:
    """A node in the method's abstract syntax tree, located by its source span."""

    node_kind = 'node'

    def __init__(self, start_offset, end_offset, line=None, column=None):
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.line = line
        self.column = column
        self.node_path = None

    def labelled_child_nodes(self):
        return []

    def child_nodes(self):
        return [child for role_segment, child in self.labelled_child_nodes()]

    def describe(self):
        return self.node_kind

    def as_source_edit(self, replacement):
        return SourceEdit(self.start_offset, self.end_offset, replacement)

    def accept(self, visitor):
        return visitor.visit(self)


class MethodNode(SyntaxNode):
    node_kind = 'method'

    def __init__(
        self,
        selector,
        argument_names,
        temporaries,
        statements,
        start_offset,
        end_offset,
        line=None,
        column=None,
        pragmas=None,
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.selector = selector
        self.argument_names = argument_names
        self.temporaries = temporaries
        self.statements = statements
        self.pragmas = pragmas if pragmas is not None else []

    def labelled_child_nodes(self):
        return [
            (f'statements[{index}]', statement)
            for index, statement in enumerate(self.statements)
        ]

    def describe(self):
        return self.selector


class MessageSendNode(SyntaxNode):
    node_kind = 'message_send'

    def __init__(
        self,
        receiver,
        selector,
        arguments,
        send_kind,
        start_offset,
        end_offset,
        line=None,
        column=None,
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.receiver = receiver
        self.selector = selector
        self.arguments = arguments
        self.send_kind = send_kind

    def labelled_child_nodes(self):
        return [('receiver', self.receiver)] + [
            (f'arguments[{index}]', argument)
            for index, argument in enumerate(self.arguments)
        ]

    def describe(self):
        return self.selector


class CascadeNode(SyntaxNode):
    node_kind = 'cascade'

    def __init__(
        self, receiver, messages, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.receiver = receiver
        self.messages = messages

    def labelled_child_nodes(self):
        return [('receiver', self.receiver)] + [
            (f'messages[{index}]', message)
            for index, message in enumerate(self.messages)
        ]

    def describe(self):
        return ';'.join(message.selector for message in self.messages)


class AssignmentNode(SyntaxNode):
    node_kind = 'assignment'

    def __init__(
        self, variable_name, value, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.variable_name = variable_name
        self.value = value

    def labelled_child_nodes(self):
        return [('value', self.value)]

    def describe(self):
        return f'{self.variable_name} :='


class ReturnNode(SyntaxNode):
    node_kind = 'return'

    def __init__(self, expression, start_offset, end_offset, line=None, column=None):
        super().__init__(start_offset, end_offset, line, column)
        self.expression = expression

    def labelled_child_nodes(self):
        return [('expression', self.expression)]

    def describe(self):
        return '^'


class BlockNode(SyntaxNode):
    node_kind = 'block'

    def __init__(
        self,
        argument_names,
        temporaries,
        statements,
        start_offset,
        end_offset,
        line=None,
        column=None,
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.argument_names = argument_names
        self.temporaries = temporaries
        self.statements = statements

    def labelled_child_nodes(self):
        return [
            (f'statements[{index}]', statement)
            for index, statement in enumerate(self.statements)
        ]

    def describe(self):
        if self.argument_names:
            return '[:' + ' :'.join(self.argument_names) + ' |]'
        return '[]'


class DynamicArrayNode(SyntaxNode):
    node_kind = 'dynamic_array'

    def __init__(self, elements, start_offset, end_offset, line=None, column=None):
        super().__init__(start_offset, end_offset, line, column)
        self.elements = elements

    def labelled_child_nodes(self):
        return [
            (f'elements[{index}]', element)
            for index, element in enumerate(self.elements)
        ]

    def describe(self):
        return f'{{ {len(self.elements)} elements }}'


class LiteralNode(SyntaxNode):
    node_kind = 'literal'

    def __init__(
        self, literal_kind, text, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.literal_kind = literal_kind
        self.text = text

    def describe(self):
        if len(self.text) > 40:
            return self.text[:37] + '...'
        return self.text


class VariableNode(SyntaxNode):
    node_kind = 'variable'

    def __init__(
        self, name, start_offset, end_offset, line=None, column=None, is_pseudo=False
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.name = name
        self.is_pseudo = is_pseudo

    def describe(self):
        return self.name


class SmalltalkMethodParser:
    """Reads method source into a MethodNode tree using recursive descent."""

    insignificant_kinds = frozenset(
        {SmalltalkTokenKind.whitespace, SmalltalkTokenKind.comment}
    )

    def parse_method(self, source):
        self.prepare(source)
        method = self.read_method()
        self.require_all_consumed()
        return method

    def parse_expression(self, source):
        self.prepare(source)
        expression = self.read_assignment()
        self.require_all_consumed()
        return expression

    def prepare(self, source):
        self.source = source
        all_tokens = SmalltalkSourceScanner().scan_tokens(source)
        self.tokens = [
            token for token in all_tokens if token.kind not in self.insignificant_kinds
        ]
        self.position = 0
        self.last_consumed_end_offset = 0

    def require_all_consumed(self):
        if not self.at_end():
            raise SmalltalkSyntaxError(
                'unexpected trailing token %r' % self.current_token().text
            )

    def at_end(self):
        return self.position >= len(self.tokens)

    def current_token(self):
        if self.at_end():
            return None
        return self.tokens[self.position]

    def current_kind(self):
        token = self.current_token()
        return token.kind if token is not None else None

    def kind_after_current(self):
        following_index = self.position + 1
        if following_index >= len(self.tokens):
            return None
        return self.tokens[following_index].kind

    def advance(self):
        token = self.tokens[self.position]
        self.position = self.position + 1
        self.last_consumed_end_offset = token.end_offset
        return token

    def consume_kind(self, kind):
        if self.at_end() or self.current_token().kind != kind:
            raise SmalltalkSyntaxError('expected %s token' % kind)
        return self.advance()

    def read_method(self):
        selector, argument_names = self.read_method_header()
        temporaries = []
        pragmas = []
        temporaries_seen = False
        reading_prefix = True
        while reading_prefix:
            if self.current_is_pragma_start():
                pragmas.append(self.read_pragma())
            elif (
                self.current_kind() == SmalltalkTokenKind.vertical_bar
                and not temporaries_seen
            ):
                temporaries = self.read_temporaries()
                temporaries_seen = True
            else:
                reading_prefix = False
        statements = self.read_statements(frozenset())
        return MethodNode(
            selector,
            argument_names,
            temporaries,
            statements,
            0,
            len(self.source),
            1,
            1,
            pragmas,
        )

    def current_is_pragma_start(self):
        # AI: A statement never starts with a binary operator, so a leading '<' is always a pragma opener.
        token = self.current_token()
        return (
            token is not None
            and token.kind == SmalltalkTokenKind.binary_selector
            and token.text == '<'
        )

    def current_token_closes_pragma(self):
        token = self.current_token()
        return (
            token is not None
            and token.kind == SmalltalkTokenKind.binary_selector
            and token.text == '>'
        )

    def read_pragma(self):
        # AI: Consume < ... > verbatim; pragma arguments are literals, so the closing '>' is the only bare '>' token.
        opening = self.advance()
        while not self.at_end() and not self.current_token_closes_pragma():
            self.advance()
        if self.at_end():
            raise SmalltalkSyntaxError('unterminated method pragma')
        closing = self.advance()
        return self.source[opening.start_offset : closing.end_offset]

    def read_method_header(self):
        if self.at_end():
            raise SmalltalkSyntaxError('empty method source has no selector')
        kind = self.current_kind()
        if kind == SmalltalkTokenKind.keyword_message_part:
            selector_parts = []
            argument_names = []
            while self.current_kind() == SmalltalkTokenKind.keyword_message_part:
                selector_parts.append(self.advance().text)
                argument_names.append(
                    self.consume_kind(SmalltalkTokenKind.unary_or_identifier).text
                )
            return (''.join(selector_parts), argument_names)
        if kind in (
            SmalltalkTokenKind.binary_selector,
            SmalltalkTokenKind.vertical_bar,
        ):
            operator = self.advance()
            argument = self.consume_kind(SmalltalkTokenKind.unary_or_identifier)
            return (operator.text, [argument.text])
        if kind == SmalltalkTokenKind.unary_or_identifier:
            return (self.advance().text, [])
        raise SmalltalkSyntaxError('method header does not begin with a selector')

    def read_temporaries(self):
        # AI: A leading | ... | at the start of a method or block body declares temporaries.
        if self.current_kind() != SmalltalkTokenKind.vertical_bar:
            return []
        self.advance()
        names = []
        while self.current_kind() == SmalltalkTokenKind.unary_or_identifier:
            names.append(self.advance().text)
        self.consume_kind(SmalltalkTokenKind.vertical_bar)
        return names

    def read_statements(self, terminator_kinds):
        statements = []
        parsing = True
        while parsing:
            if self.at_end() or self.current_kind() in terminator_kinds:
                parsing = False
            else:
                statements.append(self.read_statement())
                if self.current_kind() == SmalltalkTokenKind.statement_period:
                    self.advance()
        return statements

    def read_statement(self):
        if self.current_kind() == SmalltalkTokenKind.return_caret:
            caret = self.advance()
            expression = self.read_assignment()
            return ReturnNode(
                expression,
                caret.start_offset,
                expression.end_offset,
                caret.line,
                caret.column,
            )
        return self.read_assignment()

    def read_assignment(self):
        is_assignment = (
            self.current_kind() == SmalltalkTokenKind.unary_or_identifier
            and self.kind_after_current() == SmalltalkTokenKind.assignment
        )
        if is_assignment:
            variable = self.advance()
            self.consume_kind(SmalltalkTokenKind.assignment)
            value = self.read_assignment()
            return AssignmentNode(
                variable.text,
                value,
                variable.start_offset,
                value.end_offset,
                variable.line,
                variable.column,
            )
        return self.read_cascade()

    def read_cascade(self):
        first_send = self.read_keyword_send()
        is_cascade = self.current_kind() == SmalltalkTokenKind.cascade_semicolon and (
            isinstance(first_send, MessageSendNode)
        )
        if not is_cascade:
            return first_send
        shared_receiver = first_send.receiver
        messages = [first_send]
        while self.current_kind() == SmalltalkTokenKind.cascade_semicolon:
            self.advance()
            messages.append(self.read_message_tail(shared_receiver))
        return CascadeNode(
            shared_receiver,
            messages,
            shared_receiver.start_offset,
            self.last_consumed_end_offset,
            shared_receiver.line,
            shared_receiver.column,
        )

    def read_keyword_send(self):
        return self.read_message_tail(self.read_primary())

    def read_message_tail(self, receiver):
        receiver = self.read_binary_tail(receiver)
        if self.current_kind() != SmalltalkTokenKind.keyword_message_part:
            return receiver
        selector_parts = []
        arguments = []
        while self.current_kind() == SmalltalkTokenKind.keyword_message_part:
            selector_parts.append(self.advance().text)
            arguments.append(self.read_binary_send())
        return MessageSendNode(
            receiver,
            ''.join(selector_parts),
            arguments,
            'keyword',
            receiver.start_offset,
            arguments[-1].end_offset,
            receiver.line,
            receiver.column,
        )

    def read_binary_send(self):
        return self.read_binary_tail(self.read_unary_send())

    def read_binary_tail(self, receiver):
        receiver = self.read_unary_tail(receiver)
        while self.current_is_binary_operator():
            operator = self.advance()
            right = self.read_unary_send()
            receiver = MessageSendNode(
                receiver,
                operator.text,
                [right],
                'binary',
                receiver.start_offset,
                right.end_offset,
                receiver.line,
                receiver.column,
            )
        return receiver

    def read_unary_send(self):
        return self.read_unary_tail(self.read_primary())

    def read_unary_tail(self, receiver):
        while self.current_kind() == SmalltalkTokenKind.unary_or_identifier:
            selector = self.advance()
            receiver = MessageSendNode(
                receiver,
                selector.text,
                [],
                'unary',
                receiver.start_offset,
                selector.end_offset,
                receiver.line,
                receiver.column,
            )
        return receiver

    def current_is_binary_operator(self):
        # AI: '|' lexes as its own token but acts as a binary selector outside temp declarations.
        return self.current_kind() in (
            SmalltalkTokenKind.binary_selector,
            SmalltalkTokenKind.vertical_bar,
        )

    def read_primary(self):
        kind = self.current_kind()
        if kind == SmalltalkTokenKind.binary_selector and self.current_is_negative_number():
            return self.read_negative_number()
        if kind == SmalltalkTokenKind.number_literal:
            return self.read_literal('number')
        if kind == SmalltalkTokenKind.string_literal:
            return self.read_literal('string')
        if kind == SmalltalkTokenKind.character_literal:
            return self.read_literal('character')
        if kind == SmalltalkTokenKind.symbol_literal:
            return self.read_symbol_or_literal_array()
        if kind == SmalltalkTokenKind.pseudo_variable:
            token = self.advance()
            return VariableNode(
                token.text,
                token.start_offset,
                token.end_offset,
                token.line,
                token.column,
                True,
            )
        if kind == SmalltalkTokenKind.unary_or_identifier:
            token = self.advance()
            return VariableNode(
                token.text,
                token.start_offset,
                token.end_offset,
                token.line,
                token.column,
            )
        if kind == SmalltalkTokenKind.open_paren:
            return self.read_parenthesised()
        if kind == SmalltalkTokenKind.open_bracket:
            return self.read_block()
        if kind == SmalltalkTokenKind.open_brace:
            return self.read_dynamic_array()
        raise SmalltalkSyntaxError(
            'expected an expression but found %s' % self.describe_current()
        )

    def current_is_negative_number(self):
        # AI: A '-' directly before a number, in primary position, is a negative literal (not binary minus, which only fires once a receiver exists).
        token = self.current_token()
        return (
            token is not None
            and token.text == '-'
            and self.kind_after_current() == SmalltalkTokenKind.number_literal
        )

    def read_negative_number(self):
        minus = self.advance()
        number = self.advance()
        return LiteralNode(
            'number',
            '-' + number.text,
            minus.start_offset,
            number.end_offset,
            minus.line,
            minus.column,
        )

    def describe_current(self):
        if self.at_end():
            return 'end of source'
        return '%r' % self.current_token().text

    def read_literal(self, literal_kind):
        token = self.advance()
        return LiteralNode(
            literal_kind,
            token.text,
            token.start_offset,
            token.end_offset,
            token.line,
            token.column,
        )

    def read_symbol_or_literal_array(self):
        token = self.advance()
        if token.text == '#' and self.current_kind() == SmalltalkTokenKind.open_paren:
            return self.read_literal_array(token)
        return LiteralNode(
            'symbol',
            token.text,
            token.start_offset,
            token.end_offset,
            token.line,
            token.column,
        )

    def read_literal_array(self, hash_token):
        # AI: #( ... ) is a literal array; its contents are consumed as balanced tokens, not expressions.
        self.consume_kind(SmalltalkTokenKind.open_paren)
        depth = 1
        while depth > 0 and not self.at_end():
            inner_kind = self.advance().kind
            if inner_kind == SmalltalkTokenKind.open_paren:
                depth = depth + 1
            elif inner_kind == SmalltalkTokenKind.close_paren:
                depth = depth - 1
        if depth > 0:
            raise SmalltalkSyntaxError('unterminated literal array')
        return LiteralNode(
            'array',
            self.source[hash_token.start_offset : self.last_consumed_end_offset],
            hash_token.start_offset,
            self.last_consumed_end_offset,
            hash_token.line,
            hash_token.column,
        )

    def read_parenthesised(self):
        self.consume_kind(SmalltalkTokenKind.open_paren)
        expression = self.read_assignment()
        self.consume_kind(SmalltalkTokenKind.close_paren)
        return expression

    def read_block(self):
        opening = self.consume_kind(SmalltalkTokenKind.open_bracket)
        argument_names = []
        while self.current_starts_block_argument():
            argument_names.append(self.read_block_argument_name())
        if argument_names:
            self.consume_kind(SmalltalkTokenKind.vertical_bar)
        temporaries = self.read_temporaries()
        statements = self.read_statements(
            frozenset({SmalltalkTokenKind.close_bracket})
        )
        closing = self.consume_kind(SmalltalkTokenKind.close_bracket)
        return BlockNode(
            argument_names,
            temporaries,
            statements,
            opening.start_offset,
            closing.end_offset,
            opening.line,
            opening.column,
        )

    def current_starts_block_argument(self):
        # AI: GemStone allows whitespace after the colon, so a block argument is either ':x' or a lone colon followed by an identifier.
        if self.current_kind() == SmalltalkTokenKind.block_argument:
            return True
        return (
            self.current_kind() == SmalltalkTokenKind.colon
            and self.kind_after_current() == SmalltalkTokenKind.unary_or_identifier
        )

    def read_block_argument_name(self):
        if self.current_kind() == SmalltalkTokenKind.block_argument:
            return self.advance().text[1:]
        self.advance()
        return self.advance().text

    def read_dynamic_array(self):
        opening = self.consume_kind(SmalltalkTokenKind.open_brace)
        elements = []
        parsing = True
        while parsing:
            if self.at_end() or self.current_kind() == SmalltalkTokenKind.close_brace:
                parsing = False
            else:
                elements.append(self.read_assignment())
                if self.current_kind() == SmalltalkTokenKind.statement_period:
                    self.advance()
        closing = self.consume_kind(SmalltalkTokenKind.close_brace)
        return DynamicArrayNode(
            elements,
            opening.start_offset,
            closing.end_offset,
            opening.line,
            opening.column,
        )


def index_nodes_by_path(root_node):
    """AI: Walk the method AST in pre-order, assigning each node its structural
    node_path and returning an ordered {node_path: node} mapping. A node reached
    by more than one route - such as the receiver a cascade shares across its
    messages - is recorded once, at the first path that reaches it, so every node
    has a single stable address."""
    indexed = {}
    already_seen = set()

    def record(node, path):
        if node is not None and id(node) not in already_seen:
            already_seen.add(id(node))
            node.node_path = path
            indexed[path] = node
            for role_segment, child in node.labelled_child_nodes():
                record(child, f'{path}/{role_segment}')

    record(root_node, 'method')
    return indexed


def block_nesting_depths(root_node):
    """AI: Map id(node) -> the number of enclosing BlockNodes (its block-nesting
    depth), so a structural query can select, for example, blocks nested two or
    more deep. A node reached by more than one route is recorded once, matching
    index_nodes_by_path."""
    depths = {}
    already_seen = set()

    def record(node, depth):
        if node is not None and id(node) not in already_seen:
            already_seen.add(id(node))
            depths[id(node)] = depth
            child_depth = depth + 1 if node.node_kind == 'block' else depth
            for role_segment, child in node.labelled_child_nodes():
                record(child, child_depth)

    record(root_node, 0)
    return depths



def apply_source_edits(source, source_edits):
    """AI: Apply a sequence of non-overlapping SourceEdits to source and return the new text.
    Edits are validated for non-overlap, then applied in descending order of start_offset so
    that the offsets of as-yet-unapplied edits stay valid as later spans are rewritten. The
    caller may pass edits in any order; the relative position of two edits in the input does
    not change the result. Overlapping edits raise OverlappingSourceEditsError."""
    ordered_edits = sorted(source_edits, key=lambda edit: edit.start_offset)
    for prior_edit, later_edit in zip(ordered_edits, ordered_edits[1:]):
        if later_edit.start_offset < prior_edit.end_offset:
            raise OverlappingSourceEditsError(
                f'Source edits overlap: '
                f'[{prior_edit.start_offset}, {prior_edit.end_offset}) and '
                f'[{later_edit.start_offset}, {later_edit.end_offset}).'
            )
    edited_source = source
    for edit in reversed(ordered_edits):
        edited_source = (
            edited_source[: edit.start_offset]
            + edit.replacement
            + edited_source[edit.end_offset :]
        )
    return edited_source


class SmalltalkMethodFormat:
    """AI: AST-based Smalltalk method formatter producing canonical GemStone 1-tab style.

    Rules derived from analysis of Wonka- codebase:
    - 1 tab per nesting level; method body at depth 1.
    - Keyword sends with 2+ keywords OR a long block arg → multi-line:
      receiver on opener line, each keyword:arg at depth+1.
    - Cascade: receiver at depth, each message at depth+1, ';' on all but last.
    - Multi-keyword cascade messages: first keyword at cascade depth, continuations at depth+1.
    - Short block (≤1 stmt, no temps, expr not itself multi-line) → inline [ expr ].
    - Long block: '[ :args |' on opener line, body at +1 depth, ']' on last body line.
    - No trailing '.' on the last statement of any scope.
    - Leading method comment → blank line → (temps) → statements.
    - On parse error: return source unchanged."""

    INDENT = '\t'

    def format_method(self, source):
        try:
            method_node = SmalltalkMethodParser().parse_method(source)
        except SmalltalkSyntaxError:
            return source
        comments = self.scan_body_comments(source)
        return self.render_method(source, method_node, comments)

    def scan_body_comments(self, source):
        header_end = source.find('\n')
        if header_end == -1:
            return []
        result = []
        for token in SmalltalkSourceScanner().scan_tokens(source):
            if token.kind == SmalltalkTokenKind.comment and token.start_offset > header_end:
                result.append((token.start_offset, source[token.start_offset:token.end_offset]))
        return result

    def render_method(self, source, method_node, comments):
        parts = [self.format_header(method_node.selector, method_node.argument_names)]
        for pragma in method_node.pragmas:
            parts.append(self.INDENT + source[pragma.start_offset:pragma.end_offset])
        first_stmt_offset = method_node.statements[0].start_offset if method_node.statements else float('inf')
        leading_comments = [(off, text) for off, text in comments if off < first_stmt_offset]
        body_comments = [(off, text) for off, text in comments if off >= first_stmt_offset]
        if leading_comments:
            for _off, text in leading_comments:
                parts.append(self.INDENT + text)
            parts.append('')
        if method_node.temporaries:
            parts.append(self.INDENT + '| ' + ' '.join(method_node.temporaries) + ' |')
        items = [(s.start_offset, 'stmt', s) for s in method_node.statements]
        items += [(off, 'comment', text) for off, text in body_comments]
        items.sort(key=lambda t: t[0])
        stmt_total = len(method_node.statements)
        stmt_index = 0
        prev_comment = False
        for item_index, (_offset, kind, item) in enumerate(items):
            is_last_item = (item_index == len(items) - 1)
            if kind == 'comment':
                if not prev_comment and parts and not is_last_item:
                    parts.append('')
                parts.append(self.INDENT + item)
                prev_comment = True
            else:
                if prev_comment:
                    parts.append('')
                stmt_index += 1
                lines = self.node_lines(item, 1)
                if stmt_index < stmt_total:
                    lines[-1] += '.'
                parts.extend(lines)
                prev_comment = False
        return '\n'.join(parts)

    def format_header(self, selector, argument_names):
        if not argument_names:
            return selector
        if ':' not in selector:
            return selector + ' ' + argument_names[0]
        keywords = [k + ':' for k in selector.split(':') if k]
        return ' '.join(kw + ' ' + arg for kw, arg in zip(keywords, argument_names))

    def node_lines(self, node, depth):
        """AI: Returns a list of fully-indented strings for this node at depth."""
        tab = self.INDENT * depth
        if isinstance(node, ReturnNode):
            inner = self.node_lines(node.expression, depth)
            inner[0] = tab + '^ ' + inner[0][len(tab):]
            return inner
        if isinstance(node, AssignmentNode):
            inner = self.node_lines(node.value, depth)
            inner[0] = tab + node.variable_name + ' := ' + inner[0][len(tab):]
            return inner
        if isinstance(node, MessageSendNode):
            return self.message_lines(node, depth)
        if isinstance(node, CascadeNode):
            return self.cascade_lines(node, depth)
        if isinstance(node, BlockNode):
            header, body = self.long_block(node, depth)
            return [tab + header] + body
        if isinstance(node, DynamicArrayNode):
            return self.dynamic_array_lines(node, depth)
        return [tab + self.inline(node, 'none')]

    def message_lines(self, node, depth):
        tab = self.INDENT * depth
        if node.send_kind == 'unary':
            return [tab + self.inline(node.receiver, 'unary_receiver') + ' ' + node.selector]
        if node.send_kind == 'binary':
            recv = self.inline(node.receiver, 'binary_receiver')
            arg = self.inline(node.arguments[0], 'binary_arg')
            return [tab + recv + ' ' + node.selector + ' ' + arg]
        keywords = [k + ':' for k in node.selector.split(':') if k]
        if not self.send_is_multiline(node):
            recv = self.inline(node.receiver, 'binary_receiver')
            kw_args = ' '.join(kw + ' ' + self.inline(a, 'keyword_arg')
                               for kw, a in zip(keywords, node.arguments))
            return [tab + recv + ' ' + kw_args]
        recv = self.inline(node.receiver, 'binary_receiver')
        result = [tab + recv]
        kd = depth + 1
        for kw, arg in zip(keywords, node.arguments):
            result.extend(self.keyword_arg_lines(kw, arg, kd))
        return result

    def keyword_arg_lines(self, keyword, arg, depth):
        """AI: Lines for 'keyword: arg' at depth, expanding long blocks inline."""
        tab = self.INDENT * depth
        if isinstance(arg, BlockNode) and self.is_long_block(arg):
            header, body = self.long_block(arg, depth)
            return [tab + keyword + ' ' + header] + body
        return [tab + keyword + ' ' + self.inline(arg, 'keyword_arg')]

    def cascade_lines(self, node, depth):
        recv = self.inline(node.receiver, 'binary_receiver')
        result = [self.INDENT * depth + recv]
        for i, msg in enumerate(node.messages):
            is_last = (i == len(node.messages) - 1)
            lines = self.cascade_message_lines(msg, depth + 1)
            if not is_last:
                lines[-1] += ';'
            result.extend(lines)
        return result

    def cascade_message_lines(self, msg, depth):
        tab = self.INDENT * depth
        if msg.send_kind == 'unary':
            return [tab + msg.selector]
        if msg.send_kind == 'binary':
            return [tab + msg.selector + ' ' + self.inline(msg.arguments[0], 'binary_arg')]
        keywords = [k + ':' for k in msg.selector.split(':') if k]
        if len(keywords) == 1 and not any(
            isinstance(a, BlockNode) and self.is_long_block(a) for a in msg.arguments
        ):
            return [tab + keywords[0] + ' ' + self.inline(msg.arguments[0], 'keyword_arg')]
        result = []
        kd = depth + 1
        for i, (kw, arg) in enumerate(zip(keywords, msg.arguments)):
            result.extend(self.keyword_arg_lines(kw, arg, depth if i == 0 else kd))
        return result

    def long_block(self, block, opener_depth):
        """AI: Returns (header_text, body_lines).
        header_text goes on the same line as the keyword/opener.
        body_lines are at opener_depth+1; ']' is appended to the last body line."""
        header_parts = []
        if block.argument_names:
            header_parts.append(' '.join(':' + a for a in block.argument_names) + ' |')
        if block.temporaries and not block.argument_names:
            header_parts.append('| ' + ' '.join(block.temporaries) + ' |')
        header = ('[ ' + ' '.join(header_parts)) if header_parts else '['
        body_depth = opener_depth + 1
        body = []
        if block.temporaries and block.argument_names:
            body.append(self.INDENT * body_depth + '| ' + ' '.join(block.temporaries) + ' |')
        stmts = block.statements
        for i, stmt in enumerate(stmts):
            lines = self.node_lines(stmt, body_depth)
            if i < len(stmts) - 1:
                lines[-1] += '.'
            body.extend(lines)
        if body:
            body[-1] += ' ]'
        else:
            header += ' ]'
        return header, body

    def dynamic_array_lines(self, node, depth):
        tab = self.INDENT * depth
        if not node.elements:
            return [tab + '{}']
        elems = '. '.join(self.inline(e, 'none') for e in node.elements)
        return [tab + '{' + elems + '}']

    def send_is_multiline(self, node):
        if node.send_kind in ('unary', 'binary'):
            return False
        if node.selector.count(':') >= 2:
            return True
        if isinstance(node.receiver, MessageSendNode) and node.receiver.send_kind == 'keyword':
            return True
        return any(isinstance(a, BlockNode) and self.is_long_block(a) for a in node.arguments)

    def is_long_block(self, block):
        if block.temporaries or len(block.statements) > 1:
            return True
        if len(block.statements) == 1:
            return self.node_is_multiline(block.statements[0])
        return False

    def node_is_multiline(self, node):
        if isinstance(node, ReturnNode):
            return self.node_is_multiline(node.expression)
        if isinstance(node, AssignmentNode):
            return self.node_is_multiline(node.value)
        if isinstance(node, CascadeNode):
            return True
        if isinstance(node, MessageSendNode):
            return self.send_is_multiline(node)
        if isinstance(node, BlockNode):
            return self.is_long_block(node)
        return False

    def inline(self, node, context):
        """AI: Single-line string, adding parentheses where Smalltalk precedence requires."""
        text = self.inline_raw(node)
        if self.needs_parens(node, context):
            return '(' + text + ')'
        return text

    def inline_raw(self, node):
        if isinstance(node, VariableNode):
            return node.name
        if isinstance(node, LiteralNode):
            return node.text
        if isinstance(node, BlockNode):
            parts = []
            if node.argument_names:
                parts.append(' '.join(':' + a for a in node.argument_names) + ' |')
            if node.temporaries:
                parts.append('| ' + ' '.join(node.temporaries) + ' |')
            stmt_texts = []
            for i, s in enumerate(node.statements):
                t = self.inline(s, 'none')
                stmt_texts.append(t + '.' if i < len(node.statements) - 1 else t)
            body = ' '.join(parts + stmt_texts)
            return ('[ ' + body + ' ]') if body else '[]'
        if isinstance(node, ReturnNode):
            return '^ ' + self.inline(node.expression, 'none')
        if isinstance(node, AssignmentNode):
            return node.variable_name + ' := ' + self.inline(node.value, 'none')
        if isinstance(node, MessageSendNode):
            if node.send_kind == 'unary':
                return self.inline(node.receiver, 'unary_receiver') + ' ' + node.selector
            if node.send_kind == 'binary':
                recv = self.inline(node.receiver, 'binary_receiver')
                arg = self.inline(node.arguments[0], 'binary_arg')
                return recv + ' ' + node.selector + ' ' + arg
            recv = self.inline(node.receiver, 'binary_receiver')
            keywords = [k + ':' for k in node.selector.split(':') if k]
            kw_args = ' '.join(kw + ' ' + self.inline(a, 'keyword_arg')
                               for kw, a in zip(keywords, node.arguments))
            return recv + ' ' + kw_args
        if isinstance(node, CascadeNode):
            recv = self.inline(node.receiver, 'binary_receiver')
            msgs = '; '.join(self.inline_cascade_msg(m) for m in node.messages)
            return recv + ' ' + msgs
        if isinstance(node, DynamicArrayNode):
            return '{' + '. '.join(self.inline(e, 'none') for e in node.elements) + '}'
        return '???'

    def inline_cascade_msg(self, msg):
        if msg.send_kind == 'unary':
            return msg.selector
        if msg.send_kind == 'binary':
            return msg.selector + ' ' + self.inline(msg.arguments[0], 'binary_arg')
        keywords = [k + ':' for k in msg.selector.split(':') if k]
        return ' '.join(kw + ' ' + self.inline(a, 'keyword_arg')
                        for kw, a in zip(keywords, msg.arguments))

    def needs_parens(self, node, context):
        if not isinstance(node, MessageSendNode):
            return False
        if context == 'unary_receiver':
            return node.send_kind in ('binary', 'keyword')
        if context == 'binary_receiver':
            return node.send_kind == 'keyword'
        if context == 'binary_arg':
            return node.send_kind in ('binary', 'keyword')
        if context == 'keyword_arg':
            return node.send_kind == 'keyword'
        return False
