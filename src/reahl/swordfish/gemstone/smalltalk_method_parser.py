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


class SyntaxNode:
    """A node in the method's abstract syntax tree, located by its source span."""

    def __init__(self, start_offset, end_offset, line=None, column=None):
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.line = line
        self.column = column

    def child_nodes(self):
        return []

    def accept(self, visitor):
        return visitor.visit(self)


class MethodNode(SyntaxNode):
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

    def child_nodes(self):
        return list(self.statements)


class MessageSendNode(SyntaxNode):
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

    def child_nodes(self):
        return [self.receiver] + list(self.arguments)


class CascadeNode(SyntaxNode):
    def __init__(
        self, receiver, messages, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.receiver = receiver
        self.messages = messages

    def child_nodes(self):
        return [self.receiver] + list(self.messages)


class AssignmentNode(SyntaxNode):
    def __init__(
        self, variable_name, value, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.variable_name = variable_name
        self.value = value

    def child_nodes(self):
        return [self.value]


class ReturnNode(SyntaxNode):
    def __init__(self, expression, start_offset, end_offset, line=None, column=None):
        super().__init__(start_offset, end_offset, line, column)
        self.expression = expression

    def child_nodes(self):
        return [self.expression]


class BlockNode(SyntaxNode):
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

    def child_nodes(self):
        return list(self.statements)


class DynamicArrayNode(SyntaxNode):
    def __init__(self, elements, start_offset, end_offset, line=None, column=None):
        super().__init__(start_offset, end_offset, line, column)
        self.elements = elements

    def child_nodes(self):
        return list(self.elements)


class LiteralNode(SyntaxNode):
    def __init__(
        self, literal_kind, text, start_offset, end_offset, line=None, column=None
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.literal_kind = literal_kind
        self.text = text


class VariableNode(SyntaxNode):
    def __init__(
        self, name, start_offset, end_offset, line=None, column=None, is_pseudo=False
    ):
        super().__init__(start_offset, end_offset, line, column)
        self.name = name
        self.is_pseudo = is_pseudo


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
