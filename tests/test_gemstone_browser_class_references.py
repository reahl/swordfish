from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


# AI: Issue #14: class-reference search was slow because the original fast path called
# AI: ClassOrganizer >> allCallsOn:, which does not exist in any current GemStone image.
# AI: Every call raised, the exception was swallowed by a defensive try/except, and a
# AI: client-side regex walk over every method's source silently ran instead. The fix
# AI: is to ask GemStone's reference index directly via ClassOrganizer >> referencesTo:
# AI: and to delete the slow fallback - if the index ever fails to answer, that is a
# AI: bug to surface, not a case to paper over. These tests pin down the single path.


@stubclass(GemstoneBrowserSession)
class RecordingBrowserSession(GemstoneBrowserSession):
    """AI: Replaces the single GemStone-side leaf - run_code - with a recorder so we
    can prove the path asks for referencesTo: and parses the tab-delimited output it
    returns, without standing up a real stone."""

    recorded_run_code_source = None
    canned_run_code_result = None

    def run_code(self, source):
        self.recorded_run_code_source = source
        return self.canned_run_code_result


class TabDelimitedResult:
    """AI: parseltongue's run_code returns a GemStone object whose .to_py yields the
    Python value. The path reads .to_py - this stub satisfies just that contract."""

    def __init__(self, to_py):
        self.to_py = to_py


class ClassReferenceFixture(Fixture):
    def new_browser_session(self):
        return RecordingBrowserSession(None)


@with_fixtures(ClassReferenceFixture)
def test_class_reference_search_queries_the_class_symbol_via_references_to(fixture):
    """AI: 'find references to class X' must ask GemStone's reference index for
    ClassOrganizer>>referencesTo: against the class's Symbol. The historical
    allCallsOn: selector does not exist in any current image, so any query mentioning
    it is dead - hence issue #14."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult('')

    fixture.browser_session.find_class_references('Order')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'referencesTo:' in source
    assert "'Order' asSymbol" in source
    assert 'allCallsOn:' not in source


@with_fixtures(ClassReferenceFixture)
def test_class_reference_search_parses_tab_delimited_method_lines(fixture):
    """AI: The whole point of the server-side query is to do the per-method work in
    one GCI round-trip: one tab-delimited line per GsNMethod - class<tab>isInstanceSide
    <tab>selector - so the cost of finding references is constant in result count from
    the Python side."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult(
        '\n'.join([
            'Order\ttrue\taddLine:',
            'Order\tfalse\tdefaultLineClass',
            'OrderBuilder\ttrue\tfromOrder:',
        ])
    )

    result = fixture.browser_session.find_class_references('Order')

    assert result['returned_count'] == 3
    assert result['references'] == [
        {'class_name': 'Order', 'show_instance_side': False, 'method_selector': 'defaultLineClass'},
        {'class_name': 'Order', 'show_instance_side': True, 'method_selector': 'addLine:'},
        {'class_name': 'OrderBuilder', 'show_instance_side': True, 'method_selector': 'fromOrder:'},
    ]
