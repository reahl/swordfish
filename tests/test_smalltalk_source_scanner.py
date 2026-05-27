from reahl.tofu import Fixture, scenario, uses, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.smalltalk_source_scanner import (
    SmalltalkSourceScanner,
    SmalltalkTokenKind,
)


def historical_code_character_map(source):
    """AI: The original character-map state machine, kept here as the reference the refactor must still match."""
    code_character_map = [True for _ in source]
    index = 0
    state = 'code'
    while index < len(source):
        character = source[index]
        if state == 'code':
            if character == "'":
                code_character_map[index] = False
                state = 'string'
            elif character == '"':
                code_character_map[index] = False
                state = 'comment'
        elif state == 'string':
            code_character_map[index] = False
            if character == "'":
                has_escaped_quote = (
                    index + 1 < len(source) and source[index + 1] == "'"
                )
                if has_escaped_quote:
                    code_character_map[index + 1] = False
                    index = index + 1
                else:
                    state = 'code'
        elif state == 'comment':
            code_character_map[index] = False
            if character == '"':
                state = 'code'
        index = index + 1
    return code_character_map


class ScannerFixture(Fixture):
    def new_scanner(self):
        return SmalltalkSourceScanner()

    def tokens_for(self, source):
        return self.scanner.scan_tokens(source)

    def kinds_for(self, source):
        return [token.kind for token in self.tokens_for(source)]

    def first_token_of_kind(self, source, kind):
        matching = [
            token for token in self.tokens_for(source) if token.kind == kind
        ]
        return matching[0] if matching else None

    def has_kind(self, source, kind):
        return self.first_token_of_kind(source, kind) is not None


class BrowserSessionFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None)


@with_fixtures(ScannerFixture)
def test_doubled_quote_does_not_end_a_string_literal(scanner_fixture):
    """AI: In Smalltalk '' is an escaped quote inside a string, so 'a''b' is one literal, not two."""
    source = "'a''b'"
    string_token = scanner_fixture.first_token_of_kind(
        source, SmalltalkTokenKind.string_literal
    )

    assert string_token.text == "'a''b'"
    assert (
        len(
            [
                token
                for token in scanner_fixture.tokens_for(source)
                if token.kind == SmalltalkTokenKind.string_literal
            ]
        )
        == 1
    )


@with_fixtures(ScannerFixture)
def test_double_quote_inside_a_string_is_inert(scanner_fixture):
    """AI: A " inside a string literal is ordinary text and must not be mistaken for a comment delimiter."""
    source = "'say \"hi\"'"

    assert scanner_fixture.first_token_of_kind(
        source, SmalltalkTokenKind.string_literal
    ).text == "'say \"hi\"'"
    assert not scanner_fixture.has_kind(source, SmalltalkTokenKind.comment)


@with_fixtures(ScannerFixture)
def test_single_quote_inside_a_comment_is_inert(scanner_fixture):
    """AI: A ' inside a "comment" is ordinary text and must not open a string literal."""
    source = "\"it's fine\" foo"

    assert scanner_fixture.first_token_of_kind(
        source, SmalltalkTokenKind.comment
    ).text == "\"it's fine\""
    assert not scanner_fixture.has_kind(source, SmalltalkTokenKind.string_literal)


@with_fixtures(ScannerFixture)
def test_pseudo_variable_is_distinguished_from_a_same_prefixed_identifier(
    scanner_fixture,
):
    """AI: 'self' is a pseudo-variable but 'selfish' is just an identifier — classification respects whole-word boundaries."""
    kinds = {
        token.text: token.kind
        for token in scanner_fixture.tokens_for('self selfish')
    }

    assert kinds['self'] == SmalltalkTokenKind.pseudo_variable
    assert kinds['selfish'] == SmalltalkTokenKind.unary_or_identifier


@with_fixtures(ScannerFixture)
def test_character_literal_dollar_quote_does_not_open_a_string(scanner_fixture):
    """AI: $' is the single-character literal for a quote; it must not flip the scanner into string state (a bug in the old character map)."""
    source = "$' foo"

    assert scanner_fixture.first_token_of_kind(
        source, SmalltalkTokenKind.character_literal
    ).text == "$'"
    assert scanner_fixture.first_token_of_kind(
        source, SmalltalkTokenKind.unary_or_identifier
    ).text == 'foo'
    assert not scanner_fixture.has_kind(source, SmalltalkTokenKind.string_literal)


@with_fixtures(ScannerFixture)
def test_bar_symbol_scans_as_a_single_symbol_literal(scanner_fixture):
    """AI: '#|' is the symbol naming the binary | selector and must scan as one symbol literal, not '#' followed by a bar."""
    tokens = scanner_fixture.tokens_for('#|')

    assert len(tokens) == 1
    assert tokens[0].kind == SmalltalkTokenKind.symbol_literal
    assert tokens[0].text == '#|'


@with_fixtures(ScannerFixture)
def test_token_text_reconstructs_the_original_source(scanner_fixture):
    """AI: Tokens partition the source with no gaps or overlaps, so concatenating their text rebuilds the input exactly — the property that makes offset-based edits safe."""
    source = "at: anIndex put: aValue\n    | t |\n    t := aValue + 1.\n    ^t"

    assert (
        ''.join(token.text for token in scanner_fixture.tokens_for(source)) == source
    )


@uses(scanner_fixture=ScannerFixture)
class TokenKindScenarios(Fixture):
    @scenario
    def keyword_message_part(self):
        """AI: An identifier immediately followed by a colon is one keyword-message-part token (at:)."""
        self.snippet = 'at:'
        self.expected_kind = SmalltalkTokenKind.keyword_message_part

    @scenario
    def keyword_symbol_literal(self):
        """AI: #at:put: is a single symbol literal, even though it spans two keyword parts."""
        self.snippet = '#at:put:'
        self.expected_kind = SmalltalkTokenKind.symbol_literal

    @scenario
    def block_argument(self):
        """AI: A colon that leads an identifier marks a block argument (:x), the mirror image of a keyword part."""
        self.snippet = ':x'
        self.expected_kind = SmalltalkTokenKind.block_argument

    @scenario
    def assignment(self):
        """AI: ':=' is the assignment token and must not be split into a colon and an equals selector."""
        self.snippet = ':='
        self.expected_kind = SmalltalkTokenKind.assignment

    @scenario
    def binary_selector(self):
        """AI: A run of binary characters forms one binary selector (->)."""
        self.snippet = '->'
        self.expected_kind = SmalltalkTokenKind.binary_selector

    @scenario
    def number_literal(self):
        """AI: A radix integer such as 16r1F is a single number literal."""
        self.snippet = '16r1F'
        self.expected_kind = SmalltalkTokenKind.number_literal


@with_fixtures(ScannerFixture, TokenKindScenarios)
def test_leading_token_kind_for_snippet(scanner_fixture, token_kind_scenarios):
    """AI: Each snippet scans to exactly one significant token of the expected kind."""
    tokens = scanner_fixture.tokens_for(token_kind_scenarios.snippet)

    assert len(tokens) == 1
    assert tokens[0].kind == token_kind_scenarios.expected_kind
    assert tokens[0].text == token_kind_scenarios.snippet


class RealisticMethodSourceScenarios(Fixture):
    @scenario
    def keyword_method_with_temps(self):
        """AI: A typical keyword method with a temporary and a return."""
        self.source = (
            'at: anIndex put: aValue\n'
            '    | slot |\n'
            '    slot := aValue + 1.\n'
            '    ^slot'
        )

    @scenario
    def method_with_comment_and_string(self):
        """AI: Comments and string literals (including a '' escape) are the non-code regions the map must mark."""
        self.source = (
            'describe\n'
            '    "explain the result"\n'
            "    ^'it''s done'"
        )

    @scenario
    def cascade_and_block(self):
        """AI: Cascades and blocks are pure code as far as the character map is concerned."""
        self.source = (
            'render\n'
            '    stream nextPutAll: 1 printString; nl.\n'
            '    items do: [:each | stream print: each]'
        )


@with_fixtures(BrowserSessionFixture, RealisticMethodSourceScenarios)
def test_refactored_character_map_matches_the_historical_algorithm(
    browser_session_fixture, realistic_method_source_scenarios
):
    """AI: For realistic source (no $'/$" edge cases) the scanner-backed map is byte-identical to the original, so every existing heuristic consumer is unaffected."""
    source = realistic_method_source_scenarios.source

    assert browser_session_fixture.browser_session.source_code_character_map(
        source
    ) == historical_code_character_map(source)
