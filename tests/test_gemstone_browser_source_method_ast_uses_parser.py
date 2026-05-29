from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


# AI: After consolidating method_ast with method_outline, source_method_ast is the
# AI: single parser-backed primitive the IDE and refactorings share. Its
# AI: argument_names/temporaries come from SmalltalkMethodParser; the scanner-based
# AI: temporaries only fill in when the source is half-typed. These tests pin that
# AI: contract so an accidental regression to scanner-only behaviour is caught
# AI: before reaching consumers.


@stubclass(GemstoneBrowserSession)
class StandaloneBrowserSession(GemstoneBrowserSession):
    """AI: source_method_ast is a pure function of source - no live GemStone leaves -
    so the test fixture can stand a browser session up with a nil session and still
    exercise the real method."""


class SourceMethodAstFixture(Fixture):
    def new_browser_session(self):
        return StandaloneBrowserSession(None)


@with_fixtures(SourceMethodAstFixture)
def test_argument_names_come_from_the_parsed_method_header(fixture):
    """AI: argument_names must reflect the method header as written in source - that
    is the authoritative declaration. The previous compiled-method-metadata route
    returned the same names by a more expensive round-trip; the parser route is
    the canonical one."""
    source = 'addTo: anAccount with: anAmount\n    ^anAccount balance + anAmount'

    payload = fixture.browser_session.source_method_ast(source, 'addTo:with:')

    assert payload['argument_names'] == ['anAccount', 'anAmount']


@with_fixtures(SourceMethodAstFixture)
def test_temporaries_come_from_the_parsed_temporary_declaration(fixture):
    """AI: Temporaries declared between vertical bars are the parser's territory; the
    AST payload reflects them directly from the parsed declaration rather than
    re-scanning them with a regex heuristic."""
    source = (
        'reconcile\n'
        '    | running totals |\n'
        '    running := 0.\n'
        '    totals := OrderedCollection new.\n'
        '    ^totals'
    )

    payload = fixture.browser_session.source_method_ast(source, 'reconcile')

    assert payload['temporaries'] == ['running', 'totals']


@with_fixtures(SourceMethodAstFixture)
def test_header_source_reflects_parser_derived_argument_names(fixture):
    """AI: header_source is rendered from the method selector and the argument names;
    once the names come from the parser, the rendered header must reflect them too -
    that is what callers like the refactoring previews depend on to know how the
    method is declared."""
    source = 'addTo: anAccount with: anAmount\n    ^anAccount balance + anAmount'

    payload = fixture.browser_session.source_method_ast(source, 'addTo:with:')

    assert 'addTo: anAccount' in payload['header_source']
    assert 'with: anAmount' in payload['header_source']


@with_fixtures(SourceMethodAstFixture)
def test_unparseable_source_falls_back_to_the_scanner_temporaries(fixture):
    """AI: A half-typed method during refactoring must still answer with what the
    scanner could extract, rather than fail; argument_names is empty in that case
    because the method header itself did not parse."""
    source = 'compute\n    | running\n    ^running'

    payload = fixture.browser_session.source_method_ast(source, 'compute')

    assert payload['argument_names'] == []
