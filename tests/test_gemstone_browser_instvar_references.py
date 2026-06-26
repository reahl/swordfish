from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class RecordingBrowserSession(GemstoneBrowserSession):
    """AI: Stubs run_code so tests verify the Smalltalk query without a live stone."""

    recorded_run_code_source = None
    canned_run_code_result = None

    def run_code(self, source):
        self.recorded_run_code_source = source
        return self.canned_run_code_result


class TabDelimitedResult:
    """AI: Satisfies the .to_py contract that parseltongue's run_code returns."""

    def __init__(self, to_py):
        self.to_py = to_py


class InstVarReferenceFixture(Fixture):
    def new_browser_session(self):
        return RecordingBrowserSession(None)


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_query_uses_instVarsAccessed(fixture):
    """AI: The query must ask GemStone for each method's instVarsAccessed and filter
    on the named inst var. This tests that the correct Smalltalk API is used and
    that the class name and inst var name appear in the emitted source."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult('')

    fixture.browser_session.find_instvar_references('Amount', 'currency')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'instVarsAccessed' in source
    assert "'Amount' asSymbol" in source
    assert "'currency' asSymbol" in source


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_search_parses_newline_delimited_selectors(fixture):
    """AI: GemStone returns one selector per line. The returned dicts must expose
    class_name, show_instance_side, and method_selector for each method that
    accesses the named inst var."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult(
        'printOn:\ncurrency'
    )

    result = fixture.browser_session.find_instvar_references('Amount', 'currency')

    assert result['total_count'] == 2
    assert result['returned_count'] == 2
    selectors = [r['method_selector'] for r in result['references']]
    assert sorted(selectors) == ['currency', 'printOn:']
    for ref in result['references']:
        assert ref['class_name'] == 'Amount'
        assert ref['show_instance_side'] is True


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_empty_result_when_no_methods_access_the_var(fixture):
    """AI: When no methods access the named inst var GemStone returns an empty
    string. The result dict must report zero references, not an error."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult('')

    result = fixture.browser_session.find_instvar_references('Amount', 'value')

    assert result['references'] == []
    assert result['total_count'] == 0


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_returns_empty_when_class_name_is_blank(fixture):
    """AI: A blank class name means no class is selected. The method must
    short-circuit without querying GemStone to avoid a Smalltalk error."""
    result = fixture.browser_session.find_instvar_references('', 'currency')

    assert result['references'] == []
    assert fixture.browser_session.recorded_run_code_source is None


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_returns_empty_when_instvar_name_is_blank(fixture):
    """AI: A blank inst var name must not query GemStone — no variable to search for."""
    result = fixture.browser_session.find_instvar_references('Amount', '')

    assert result['references'] == []
    assert fixture.browser_session.recorded_run_code_source is None
