from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException


class EditNodeFixture(Fixture):
    """AI: Drives edit_method_node_plan / apply_edit_method_node against a
    browser session whose I/O leaves are deterministic stubs, so the
    parser-backed node lookup and source splicing logic runs end-to-end
    without GemStone."""

    def new_browser_session(self):
        return GemstoneBrowserSession(None)

    def given_method(self, source):
        self.method_source = source
        self.compiled_sources = []

        def fake_get_method_source(class_name, method_selector, show_instance_side):
            return self.method_source

        def fake_get_method_category(class_name, method_selector, show_instance_side):
            return 'editing'

        def fake_compile_method(**kwargs):
            self.method_source = kwargs['source']
            self.compiled_sources.append(kwargs)

        self.browser_session.get_method_source = fake_get_method_source
        self.browser_session.get_method_category = fake_get_method_category
        self.browser_session.compile_method = fake_compile_method


@with_fixtures(EditNodeFixture)
def test_edit_node_plan_returns_new_source_with_leaf_literal_replaced(fixture):
    """AI: The atomic value proposition: feed in a node_path and a
    replacement fragment, get back the new full method source with that
    one node's source range substituted. No client-side offset
    arithmetic; the parser is the single source of truth for where the
    node sits."""
    fixture.given_method(
        'classify: aNumber\n'
        '\taNumber < 0 ifTrue: [ ^ #negative ].\n'
        '\t^ #large'
    )

    plan = fixture.browser_session.edit_method_node_plan(
        'Probe',
        True,
        'classify:',
        'method/statements[0]/arguments[0]/statements[0]/expression',
        '#tiny',
    )

    assert '#tiny' in plan['new_method_source']
    assert '#negative' not in plan['new_method_source']
    # AI: The rest of the method is untouched.
    assert '^ #large' in plan['new_method_source']
    assert plan['new_method_compile_warning'] is None


@with_fixtures(EditNodeFixture)
def test_edit_node_plan_rejects_unknown_node_path(fixture):
    """AI: A node_path that does not address any node in the parsed
    method must fail loudly with a clear error, not silently leave the
    method unchanged or splice an empty range."""
    fixture.given_method('describe\n\t^ #self')

    with expected(DomainException):
        fixture.browser_session.edit_method_node_plan(
            'Probe',
            True,
            'describe',
            'method/statements[9]/expression',
            '#other',
        )


@with_fixtures(EditNodeFixture)
def test_edit_node_plan_surfaces_candidate_parse_warning_when_spliced_source_is_invalid(
    fixture,
):
    """AI: A replacement fragment that makes the resulting method source
    no longer parse must surface as a warning on the plan (same shape as
    Tier B's extract preview), so callers can refuse before commit."""
    fixture.given_method('describe\n\t^ #self')

    plan = fixture.browser_session.edit_method_node_plan(
        'Probe',
        True,
        'describe',
        'method/statements[0]/expression',
        '#%%bogus%%',
    )

    assert plan['new_method_compile_warning'] is not None
    assert 'did not parse' in plan['new_method_compile_warning']


@with_fixtures(EditNodeFixture)
def test_apply_edit_method_node_compiles_the_spliced_source(fixture):
    """AI: apply_edit_method_node should run the plan, refuse if the
    candidate did not parse, and otherwise recompile the method against
    the spliced source. The fixture's recorded compile source is the
    final shape."""
    fixture.given_method(
        'classify: aNumber\n'
        '\taNumber < 0 ifTrue: [ ^ #negative ].\n'
        '\t^ #large'
    )

    result = fixture.browser_session.apply_edit_method_node(
        'Probe',
        True,
        'classify:',
        'method/statements[0]/arguments[0]/statements[0]/expression',
        '#tiny',
    )

    assert result['applied'] is True
    assert fixture.compiled_sources, fixture.compiled_sources
    final_source = fixture.compiled_sources[0]['source']
    assert '#tiny' in final_source
    assert '#negative' not in final_source


@with_fixtures(EditNodeFixture)
def test_apply_edit_method_node_refuses_to_compile_unparseable_candidate(fixture):
    """AI: When the spliced source does not parse, apply must raise
    rather than recompile a broken method. The browser's compile_method
    is never called."""
    fixture.given_method('describe\n\t^ #self')

    with expected(DomainException):
        fixture.browser_session.apply_edit_method_node(
            'Probe',
            True,
            'describe',
            'method/statements[0]/expression',
            '#%%bogus%%',
        )

    assert fixture.compiled_sources == [], fixture.compiled_sources
