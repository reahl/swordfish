from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


# AI: After issue #14: 'find senders' / 'find implementors' used to have a fast path
# AI: that ignored category details and a slow path that supplied them - so the IDE's
# AI: category filter accidentally depended on the fast path failing. The corrected
# AI: shape is a single server-side query that emits class<tab>side<tab>selector<tab>
# AI: method-category per match, and category enrichment happens in Python.


@stubclass(GemstoneBrowserSession)
class RecordingBrowserSession(GemstoneBrowserSession):
    """AI: Replaces the only live leaves - run_code (the Smalltalk query) and
    class_categories_by_class_name (the per-class category index) - so we can
    prove the collapsed selector_occurrence_summaries shape end-to-end."""

    recorded_run_code_source = None
    canned_run_code_result = None
    canned_class_categories = None

    def run_code(self, source):
        self.recorded_run_code_source = source
        return self.canned_run_code_result

    def class_categories_by_class_name(self):
        return dict(self.canned_class_categories or {})


class TabDelimitedResult:
    """AI: parseltongue's run_code returns a GemStone object whose .to_py is the
    Python value; the path under test reads .to_py."""

    def __init__(self, to_py):
        self.to_py = to_py


class SelectorOccurrenceFixture(Fixture):
    def new_browser_session(self):
        return RecordingBrowserSession(None)


@with_fixtures(SelectorOccurrenceFixture)
def test_implementors_query_asks_class_organizer_for_implementors_of_symbol(fixture):
    """AI: 'find implementors of selector S' must ask ClassOrganizer>>implementorsOf:
    against the selector's Symbol. The historical split sent the same query twice
    (once fast, once slow); the single path is what makes the call cost predictable."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult('')

    fixture.browser_session.selector_occurrence_summaries('printOn:', 'implementors')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'implementorsOf:' in source
    assert "'printOn:' asSymbol" in source
    assert 'sendersOf:' not in source


@with_fixtures(SelectorOccurrenceFixture)
def test_senders_query_asks_class_organizer_for_senders_of_symbol(fixture):
    """AI: 'find senders of selector S' must ask ClassOrganizer>>sendersOf: -
    the mirror of the implementors query, so the same parsing covers both."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult('')

    fixture.browser_session.selector_occurrence_summaries('printOn:', 'senders')

    source = fixture.browser_session.recorded_run_code_source
    assert source is not None
    assert 'sendersOf:' in source
    assert "'printOn:' asSymbol" in source
    assert 'implementorsOf:' not in source


@with_fixtures(SelectorOccurrenceFixture)
def test_method_category_arrives_per_line_so_category_filtering_does_not_need_a_second_round_trip(
    fixture,
):
    """AI: The Smalltalk loop now emits a 4th tab-delimited field - the method's
    category/protocol - so 'include_category_details=True' only requires one bulk
    class-categories lookup in Python afterwards, not one round-trip per result. This
    is the change that makes the IDE's sender category filter stop depending on the
    old slow path."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult(
        '\n'.join([
            'Account\ttrue\tprintOn:\tprinting',
            'Order\ttrue\tprintOn:\t*reports-extension',
        ])
    )
    fixture.browser_session.canned_class_categories = {
        'Account': 'Banking',
        'Order': 'Sales',
    }

    summaries = fixture.browser_session.selector_occurrence_summaries(
        'printOn:',
        'senders',
        include_category_details=True,
    )

    account_summary = next(s for s in summaries if s['class_name'] == 'Account')
    order_summary = next(s for s in summaries if s['class_name'] == 'Order')
    assert account_summary['method_category'] == 'printing'
    assert account_summary['class_category'] == 'Banking'
    assert account_summary['method_category_is_extension'] is False
    assert account_summary['extension_category_name'] is None
    assert order_summary['method_category'] == '*reports-extension'
    assert order_summary['method_category_is_extension'] is True
    assert order_summary['extension_category_name'] == 'reports-extension'


@with_fixtures(SelectorOccurrenceFixture)
def test_without_category_details_the_summary_carries_only_navigation_keys(fixture):
    """AI: When the caller does not opt in to category details, the result must stay
    a clean three-key navigation summary - the IDE's identifier-granularity sender
    listing depends on that minimal shape (test_gemstone_browser_send_sites
    pins this contract from the other side)."""
    fixture.browser_session.canned_run_code_result = TabDelimitedResult(
        'Account\ttrue\tprintOn:\tprinting'
    )

    summaries = fixture.browser_session.selector_occurrence_summaries(
        'printOn:',
        'implementors',
    )

    assert summaries == [
        {
            'class_name': 'Account',
            'show_instance_side': True,
            'method_selector': 'printOn:',
        }
    ]
