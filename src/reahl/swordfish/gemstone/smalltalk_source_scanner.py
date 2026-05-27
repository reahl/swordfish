"""Tokenises GemStone Smalltalk source into a flat stream of tokens.

This scanner is deliberately free of any GemStone/parseltongue dependency so that
both the IDE (syntax highlighting in the Tk editor) and the server-facing browser
session can rely on a single, identical view of Smalltalk lexical structure.
"""


class SmalltalkTokenKind:
    """AI: Vocabulary of Smalltalk source token kinds, used as tags by the scanner and its consumers."""

    whitespace = 'whitespace'
    comment = 'comment'
    string_literal = 'string_literal'
    symbol_literal = 'symbol_literal'
    character_literal = 'character_literal'
    number_literal = 'number_literal'
    keyword_message_part = 'keyword_message_part'
    binary_selector = 'binary_selector'
    unary_or_identifier = 'unary_or_identifier'
    pseudo_variable = 'pseudo_variable'
    assignment = 'assignment'
    return_caret = 'return_caret'
    statement_period = 'statement_period'
    cascade_semicolon = 'cascade_semicolon'
    block_argument = 'block_argument'
    colon = 'colon'
    vertical_bar = 'vertical_bar'
    open_paren = 'open_paren'
    close_paren = 'close_paren'
    open_bracket = 'open_bracket'
    close_bracket = 'close_bracket'
    open_brace = 'open_brace'
    close_brace = 'close_brace'
    unknown = 'unknown'


class SourceToken:
    """A single lexical token with its kind, source span and 1-based line/column position."""

    def __init__(self, kind, start_offset, end_offset, line, column, text):
        self.kind = kind
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.line = line
        self.column = column
        self.text = text

    def coordinates(self):
        return (self.line, self.column)

    def covers_offset(self, offset):
        return self.start_offset <= offset < self.end_offset

    def __repr__(self):
        return 'SourceToken(%r, %r, %r)' % (self.kind, self.start_offset, self.text)


class SmalltalkSourceScanner:
    """Turns Smalltalk source text into an ordered list of SourceToken values."""

    pseudo_variable_names = frozenset(
        {'self', 'super', 'nil', 'true', 'false', 'thisContext'}
    )
    binary_characters = frozenset('+-*/~<>=&@%,?!\\')

    def scan_tokens(self, source):
        tokens = []
        cursor = 0
        line = 1
        column = 1
        length = len(source)
        while cursor < length:
            kind, end = self.read_token_at(source, cursor)
            text = source[cursor:end]
            tokens.append(SourceToken(kind, cursor, end, line, column, text))
            for character in text:
                if character == '\n':
                    line = line + 1
                    column = 1
                else:
                    column = column + 1
            cursor = end
        return tokens

    def next_token_at(self, source, cursor):
        # AI: Single-shot lookup of the token starting at cursor; coordinates are derived from the prefix.
        if cursor >= len(source):
            return None
        kind, end = self.read_token_at(source, cursor)
        line, column = self.coordinates_at(source, cursor)
        return SourceToken(kind, cursor, end, line, column, source[cursor:end])

    def classify_identifier(self, identifier_text):
        if identifier_text in self.pseudo_variable_names:
            return SmalltalkTokenKind.pseudo_variable
        return SmalltalkTokenKind.unary_or_identifier

    def read_token_at(self, source, cursor):
        # AI: Returns (kind, end_offset) for the token starting at cursor; end is always > cursor so scanning makes progress.
        character = source[cursor]
        if self.is_whitespace(character):
            return (SmalltalkTokenKind.whitespace, self.scan_whitespace(source, cursor))
        if character == '"':
            return (SmalltalkTokenKind.comment, self.scan_comment(source, cursor))
        if character == "'":
            return (
                SmalltalkTokenKind.string_literal,
                self.scan_string_literal(source, cursor),
            )
        if character == '$':
            return (
                SmalltalkTokenKind.character_literal,
                self.scan_character_literal(source, cursor),
            )
        if character == '#':
            return (
                SmalltalkTokenKind.symbol_literal,
                self.scan_symbol_literal(source, cursor),
            )
        if character == '^':
            return (SmalltalkTokenKind.return_caret, cursor + 1)
        if character == '.':
            return (SmalltalkTokenKind.statement_period, cursor + 1)
        if character == ';':
            return (SmalltalkTokenKind.cascade_semicolon, cursor + 1)
        if character == '|':
            return (SmalltalkTokenKind.vertical_bar, cursor + 1)
        if character == '(':
            return (SmalltalkTokenKind.open_paren, cursor + 1)
        if character == ')':
            return (SmalltalkTokenKind.close_paren, cursor + 1)
        if character == '[':
            return (SmalltalkTokenKind.open_bracket, cursor + 1)
        if character == ']':
            return (SmalltalkTokenKind.close_bracket, cursor + 1)
        if character == '{':
            return (SmalltalkTokenKind.open_brace, cursor + 1)
        if character == '}':
            return (SmalltalkTokenKind.close_brace, cursor + 1)
        if character == ':':
            return self.read_colon_token(source, cursor)
        if character.isdigit():
            return (SmalltalkTokenKind.number_literal, self.scan_number(source, cursor))
        if self.is_identifier_start(character):
            return self.read_identifier_token(source, cursor)
        if self.is_binary_character(character):
            return (
                SmalltalkTokenKind.binary_selector,
                self.scan_binary_run(source, cursor),
            )
        return (SmalltalkTokenKind.unknown, cursor + 1)

    def read_colon_token(self, source, cursor):
        length = len(source)
        next_index = cursor + 1
        if next_index < length and source[next_index] == '=':
            return (SmalltalkTokenKind.assignment, cursor + 2)
        if next_index < length and self.is_identifier_start(source[next_index]):
            return (
                SmalltalkTokenKind.block_argument,
                self.scan_identifier_run(source, next_index),
            )
        return (SmalltalkTokenKind.colon, cursor + 1)

    def read_identifier_token(self, source, cursor):
        length = len(source)
        end = self.scan_identifier_run(source, cursor)
        # AI: An identifier directly followed by ':' is a keyword part (at:), unless that colon begins ':=' assignment.
        is_keyword_part = (
            end < length
            and source[end] == ':'
            and not (end + 1 < length and source[end + 1] == '=')
        )
        if is_keyword_part:
            return (SmalltalkTokenKind.keyword_message_part, end + 1)
        return (self.classify_identifier(source[cursor:end]), end)

    def scan_whitespace(self, source, start):
        length = len(source)
        index = start
        while index < length and self.is_whitespace(source[index]):
            index = index + 1
        return index

    def scan_identifier_run(self, source, start):
        length = len(source)
        index = start
        while index < length and self.is_identifier_part(source[index]):
            index = index + 1
        return index

    def scan_binary_run(self, source, start):
        length = len(source)
        index = start
        while index < length and self.is_binary_character(source[index]):
            index = index + 1
        return index

    def scan_comment(self, source, start):
        # AI: A "comment" runs to the next lone double quote; "" embeds a literal double quote.
        length = len(source)
        index = start + 1
        closed = False
        while index < length and not closed:
            if source[index] == '"':
                if index + 1 < length and source[index + 1] == '"':
                    index = index + 2
                else:
                    index = index + 1
                    closed = True
            else:
                index = index + 1
        return index

    def scan_string_literal(self, source, start):
        # AI: A 'string' runs to the next lone single quote; '' embeds a literal single quote.
        length = len(source)
        index = start + 1
        closed = False
        while index < length and not closed:
            if source[index] == "'":
                if index + 1 < length and source[index + 1] == "'":
                    index = index + 2
                else:
                    index = index + 1
                    closed = True
            else:
                index = index + 1
        return index

    def scan_character_literal(self, source, start):
        # AI: $ takes the very next character verbatim, so $' , $$ and $<space> are all single-character literals.
        if start + 1 < len(source):
            return start + 2
        return start + 1

    def scan_symbol_literal(self, source, start):
        # AI: Symbol forms after '#': #'quoted', #unary, #key:word:, or a binary symbol such as #+ or #|.
        length = len(source)
        index = start + 1
        if index >= length:
            return index
        leading = source[index]
        if leading == "'":
            return self.scan_string_literal(source, index)
        if self.is_identifier_start(leading):
            index = self.scan_identifier_run(source, index)
            while index < length and source[index] == ':':
                index = index + 1
                if index < length and self.is_identifier_start(source[index]):
                    index = self.scan_identifier_run(source, index)
            return index
        if leading == '|' or self.is_binary_character(leading):
            while index < length and (
                source[index] == '|' or self.is_binary_character(source[index])
            ):
                index = index + 1
            return index
        return index

    def scan_number(self, source, start):
        length = len(source)
        index = start
        while index < length and source[index].isdigit():
            index = index + 1
        # AI: Radix literal such as 16r1F — alphanumeric digits follow the 'r'.
        if index < length and source[index] == 'r':
            index = index + 1
            while index < length and source[index].isalnum():
                index = index + 1
            return index
        # AI: Fractional part, only when a digit follows the dot, so a statement period stays its own token.
        if index + 1 < length and source[index] == '.' and source[index + 1].isdigit():
            index = index + 2
            while index < length and source[index].isdigit():
                index = index + 1
        # AI: Exponent (e/d/q) with an optional sign, consumed only when real digits follow.
        if index < length and source[index] in 'edq':
            exponent_index = index + 1
            if exponent_index < length and source[exponent_index] in '+-':
                exponent_index = exponent_index + 1
            if exponent_index < length and source[exponent_index].isdigit():
                index = exponent_index
                while index < length and source[index].isdigit():
                    index = index + 1
        # AI: Scaled-decimal suffix such as 3.14s2.
        if index < length and source[index] == 's':
            index = index + 1
            while index < length and source[index].isdigit():
                index = index + 1
        return index

    def coordinates_at(self, source, offset):
        # AI: 1-based line/column for an offset, computed by scanning the prefix.
        line = 1
        column = 1
        index = 0
        limit = min(offset, len(source))
        while index < limit:
            if source[index] == '\n':
                line = line + 1
                column = 1
            else:
                column = column + 1
            index = index + 1
        return (line, column)

    def is_whitespace(self, character):
        return character in ' \t\r\n\f'

    def is_identifier_start(self, character):
        return character.isalpha() or character == '_'

    def is_identifier_part(self, character):
        return character.isalnum() or character == '_'

    def is_binary_character(self, character):
        return character in self.binary_characters
