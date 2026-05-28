from reahl.stubble import stubclass
from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException
from reahl.swordfish.gemstone.smalltalk_method_parser import SourceEdit


@stubclass(GemstoneBrowserSession)
class RecordingBrowserSession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession whose only live dependency for compilation - the
    GemStone-side compile_method call - is replaced with a recorder, so we can prove
    that compile_method_with_edits applies its edits in Python and then delegates the
    actual install to the same compile path everything else uses. stubclass checks
    compile_method still matches the real signature."""

    recorded_compile_call = None
    compile_return_value = None

    def compile_method(
        self,
        class_name,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        self.recorded_compile_call = {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'source': source,
            'method_category': method_category,
        }
        return self.compile_return_value


class CompileWithEditsFixture(Fixture):
    def new_browser_session(self):
        return RecordingBrowserSession(None)


@with_fixtures(CompileWithEditsFixture)
def test_compile_method_with_edits_applies_edits_then_routes_through_compile_method(fixture):
    """AI: compile_method_with_edits is the node-path-addressed front door to recompilation -
    it rewrites the source in Python according to the SourceEdits and then hands the rewritten
    text to the same compile_method everything else uses, so refactorings stay diffs against
    a known source and never reinvent the GemStone-side install path."""
    original_source = 'compute\n    ^self balance + 1'
    source_edits = [SourceEdit(len('compute\n    ^self '), len('compute\n    ^self balance'), 'total')]

    fixture.browser_session.compile_method_with_edits(
        'Account', True, original_source, source_edits
    )

    recorded = fixture.browser_session.recorded_compile_call
    assert recorded['class_name'] == 'Account'
    assert recorded['show_instance_side'] is True
    assert recorded['source'] == 'compute\n    ^self total + 1'
    assert recorded['method_category'] == 'as yet unclassified'


@with_fixtures(CompileWithEditsFixture)
def test_overlapping_edits_raise_domain_exception_and_do_not_compile(fixture):
    """AI: two edits that touch the same span have no canonical ordering - the browser must
    surface this as a DomainException and never run compile_method, because a half-applied
    rewrite would silently install one edit and drop the other, leaving the image in a state
    the caller never asked for."""
    original_source = 'compute\n    ^self balance + 1'
    overlapping_edits = [
        SourceEdit(len('compute\n    ^self '), len('compute\n    ^self balance'), 'total'),
        SourceEdit(len('compute\n    ^self ba'), len('compute\n    ^self balance + 1'), 'lance plus one'),
    ]

    with expected(DomainException):
        fixture.browser_session.compile_method_with_edits(
            'Account', True, original_source, overlapping_edits
        )

    assert fixture.browser_session.recorded_compile_call is None
