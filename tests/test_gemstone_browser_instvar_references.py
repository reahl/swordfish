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


class PlainResult:
    """AI: Satisfies the .to_py contract that parseltongue's run_code returns."""

    def __init__(self, to_py):
        self.to_py = to_py


class InstVarReferenceFixture(Fixture):
    def new_browser_session(self):
        return RecordingBrowserSession(None)


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_query_uses_instVarsAccessed(fixture):
    """AI: The query must ask GemStone for each method's instVarsAccessed and filter
    on the named inst var, searching the full subclass hierarchy. This tests that
    the correct Smalltalk API is used and that class name and inst var name appear."""
    fixture.browser_session.canned_run_code_result = PlainResult('')

    fixture.browser_session.find_instvar_references('Amount', 'currency')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'instVarsAccessed' in source
    assert "'Amount' asSymbol" in source
    assert "'currency' asSymbol" in source
    assert 'allSubclasses' in source


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_search_parses_class_side_and_instance_side_results(fixture):
    """AI: GemStone returns class TAB side TAB selector per line. The returned dicts
    must expose class_name, show_instance_side, and method_selector, distinguishing
    instance-side from class-side results."""
    fixture.browser_session.canned_run_code_result = PlainResult(
        'Amount\tinstance\tprintOn:\nAmount\tclass\tnew'
    )

    result = fixture.browser_session.find_instvar_references('Amount', 'currency')

    assert result['total_count'] == 2
    assert result['returned_count'] == 2
    by_selector = {r['method_selector']: r for r in result['references']}
    assert by_selector['printOn:']['class_name'] == 'Amount'
    assert by_selector['printOn:']['show_instance_side'] is True
    assert by_selector['new']['class_name'] == 'Amount'
    assert by_selector['new']['show_instance_side'] is False


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_search_includes_subclass_results(fixture):
    """AI: Because the query traverses allSubclasses, results can come from a subclass
    of the named class. The class_name field must reflect the actual defining class."""
    fixture.browser_session.canned_run_code_result = PlainResult(
        'Amount\tinstance\tprintOn:\nMoney\tinstance\tprintOn:'
    )

    result = fixture.browser_session.find_instvar_references('Amount', 'currency')

    class_names = {r['class_name'] for r in result['references']}
    assert class_names == {'Amount', 'Money'}


@with_fixtures(InstVarReferenceFixture)
def test_classvar_reference_query_matches_association_literal_in_owner_hierarchy(fixture):
    """AI: Class variables are invisible to instVarsAccessed, so the class-var query
    must instead scan method literals for an Association whose key is the variable,
    after walking up to the variable's owner so the whole scope is covered. It must
    use the portable selectors that also exist on the older GemStone (detect:ifNone:
    and Association rather than anySatisfy:/SymbolAssociation)."""
    fixture.browser_session.canned_run_code_result = PlainResult('')

    fixture.browser_session.find_classvar_references('Date', 'MonthNames')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'instVarsAccessed' not in source
    assert 'literals' in source
    assert 'key == varSym' in source
    assert 'superclass classVarNames includes: varSym' in source
    assert 'allSubclasses' in source
    assert 'detect:' in source
    assert 'isKindOf: Association' in source
    assert "'Date' asSymbol" in source
    assert "'MonthNames' asSymbol" in source


@with_fixtures(InstVarReferenceFixture)
def test_classvar_reference_search_parses_both_sides(fixture):
    """AI: The class-var search returns the same class TAB side TAB selector shape as
    the inst-var search, so the dialog can reuse the same navigation handling."""
    fixture.browser_session.canned_run_code_result = PlainResult(
        'Date\tinstance\tmonthName\nDate\tclass\tnameOfMonth:'
    )

    result = fixture.browser_session.find_classvar_references('Date', 'MonthNames')

    assert result['total_count'] == 2
    by_selector = {r['method_selector']: r for r in result['references']}
    assert by_selector['monthName']['show_instance_side'] is True
    assert by_selector['nameOfMonth:']['show_instance_side'] is False


@with_fixtures(InstVarReferenceFixture)
def test_classvar_reference_returns_empty_when_names_blank(fixture):
    """AI: A blank class or variable name must short-circuit without querying GemStone."""
    assert fixture.browser_session.find_classvar_references('', 'MonthNames')['references'] == []
    assert fixture.browser_session.find_classvar_references('Date', '')['references'] == []
    assert fixture.browser_session.recorded_run_code_source is None


@with_fixtures(InstVarReferenceFixture)
def test_instvar_reference_empty_result_when_no_methods_access_the_var(fixture):
    """AI: When no methods access the named inst var GemStone returns an empty
    string. The result dict must report zero references, not an error."""
    fixture.browser_session.canned_run_code_result = PlainResult('')

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


@with_fixtures(InstVarReferenceFixture)
def test_accessible_var_names_returns_all_three_kinds(fixture):
    """AI: accessible_var_names splits variables into instance, class-instance and
    class kinds. GemStone emits one 'kind TAB name TAB own|inherited' line per
    variable, which must be parsed into per-kind lists of name/inherited dicts."""
    fixture.browser_session.canned_run_code_result = PlainResult(
        'inst\tamount\town\n'
        'inst\tcurrency\town\n'
        'classInst\tmanager\town\n'
        'classVar\tTotal\town'
    )

    result = fixture.browser_session.accessible_var_names('Amount')

    assert result['inst_var_names'] == [
        {'name': 'amount', 'inherited': False},
        {'name': 'currency', 'inherited': False},
    ]
    assert result['class_inst_var_names'] == [
        {'name': 'manager', 'inherited': False},
    ]
    assert result['class_var_names'] == [{'name': 'Total', 'inherited': False}]


@with_fixtures(InstVarReferenceFixture)
def test_accessible_var_names_marks_inherited_variables(fixture):
    """AI: A variable defined on a superclass is flagged inherited so the UI can
    distinguish it from variables the class itself introduces."""
    fixture.browser_session.canned_run_code_result = PlainResult(
        'inst\tamount\town\n'
        'inst\tcurrency\tinherited'
    )

    result = fixture.browser_session.accessible_var_names('Amount')

    assert result['inst_var_names'] == [
        {'name': 'amount', 'inherited': False},
        {'name': 'currency', 'inherited': True},
    ]


@with_fixtures(InstVarReferenceFixture)
def test_accessible_var_names_returns_empty_groups_when_result_is_empty(fixture):
    """AI: A class with no variables returns empty lists for all three kinds."""
    fixture.browser_session.canned_run_code_result = PlainResult('')

    result = fixture.browser_session.accessible_var_names('Amount')

    assert result['inst_var_names'] == []
    assert result['class_inst_var_names'] == []
    assert result['class_var_names'] == []


@with_fixtures(InstVarReferenceFixture)
def test_accessible_var_names_returns_empty_when_class_name_is_blank(fixture):
    """AI: A blank class name must short-circuit without querying GemStone."""
    result = fixture.browser_session.accessible_var_names('')

    assert result['inst_var_names'] == []
    assert fixture.browser_session.recorded_run_code_source is None
