from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


# AI: method_ast historically derived argument and temporary names from a GsNMethod
# AI: round-trip (compiled_method.argsAndTemps / numArgs), which only worked when an
# AI: in-image AST-support package was installed. The Python SmalltalkMethodParser is
# AI: always available and already extracts these from source, so the GsNMethod
# AI: fetch is unnecessary. These tests pin the new contract: arg/temp names come
# AI: from the parser, and get_compiled_method is never reached.


@stubclass(GemstoneBrowserSession)
class ParserBackedAstBrowserSession(GemstoneBrowserSession):
    """AI: Stubs only the source fetch and asserts that the compiled-method fetch is
    not reached - the whole point of routing through the parser is that we no longer
    need the GsNMethod round-trip."""

    canned_source = ''
    get_compiled_method_call_count = 0

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.canned_source

    def get_compiled_method(self, class_name, method_selector, show_instance_side):
        self.get_compiled_method_call_count += 1
        raise AssertionError(
            'AI: method_ast must derive argument and temporary names from the parser, '
            'not from a GsNMethod round-trip.'
        )


class MethodAstParserFixture(Fixture):
    def new_browser_session(self):
        return ParserBackedAstBrowserSession(None)


@with_fixtures(MethodAstParserFixture)
def test_method_ast_derives_argument_names_from_the_parsed_method_header(fixture):
    """AI: argument_names must reflect the method header as written in source - that is
    the authoritative declaration. The compiled-method-metadata route returned the same
    names by a more expensive path; the parser route is the canonical one."""
    fixture.browser_session.canned_source = (
        'addTo: anAccount with: anAmount\n'
        '    ^anAccount balance + anAmount'
    )

    payload = fixture.browser_session.method_ast('Order', 'addTo:with:', True)

    assert payload['argument_names'] == ['anAccount', 'anAmount']
    assert fixture.browser_session.get_compiled_method_call_count == 0


@with_fixtures(MethodAstParserFixture)
def test_method_ast_derives_temporaries_from_the_parsed_temporary_declaration(fixture):
    """AI: temporaries declared between vertical bars are the parser's territory; the
    new contract is that the AST payload reflects them directly from the parsed
    declaration rather than re-fetching them from the compiled method."""
    fixture.browser_session.canned_source = (
        'reconcile\n'
        '    | running totals |\n'
        '    running := 0.\n'
        '    totals := OrderedCollection new.\n'
        '    ^totals'
    )

    payload = fixture.browser_session.method_ast('Ledger', 'reconcile', True)

    assert payload['temporaries'] == ['running', 'totals']
    assert fixture.browser_session.get_compiled_method_call_count == 0


@with_fixtures(MethodAstParserFixture)
def test_method_ast_header_source_reflects_parser_derived_argument_names(fixture):
    """AI: header_source is rendered from the method selector and the argument names;
    once the names come from the parser, the rendered header must reflect them too -
    that is what callers like the refactoring previews depend on to know how the
    method is declared."""
    fixture.browser_session.canned_source = (
        'addTo: anAccount with: anAmount\n'
        '    ^anAccount balance + anAmount'
    )

    payload = fixture.browser_session.method_ast('Order', 'addTo:with:', True)

    assert 'addTo: anAccount' in payload['header_source']
    assert 'with: anAmount' in payload['header_source']
