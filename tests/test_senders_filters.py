from reahl.stubble import stubclass
from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class FilteringSession(GemstoneBrowserSession):
    """AI: Stubs the occurrence query with a fixed, category-tagged candidate set so a
    test can prove find_senders narrows it by the requested facets before counting or
    slicing - without a live image. granularity='identifier' keeps the candidate summary
    as the result, so no source is fetched."""

    canned_summaries = []

    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        return list(self.canned_summaries)


CANNED = [
    {'class_name': 'Account', 'show_instance_side': True,
     'method_selector': 'post', 'class_category': 'Banking',
     'method_category': 'actions'},
    {'class_name': 'AccountTest', 'show_instance_side': True,
     'method_selector': 'testPost', 'class_category': 'Banking-Tests',
     'method_category': 'tests'},
    {'class_name': 'Ledger', 'show_instance_side': False,
     'method_selector': 'reset', 'class_category': 'Banking',
     'method_category': 'actions'},
    {'class_name': 'Widget', 'show_instance_side': True,
     'method_selector': 'draw', 'class_category': 'UI',
     'method_category': 'rendering'},
]


class SenderFilterFixture(Fixture):
    def new_browser_session(self):
        session = FilteringSession(None)
        session.canned_summaries = CANNED
        return session


class SenderFilterScenarios(Fixture):
    @scenario
    def by_class_category(self):
        """AI: Narrowing to a class category keeps only senders whose class lives there."""
        self.filters = {'class_categories': ['Banking']}
        self.expected_classes = ['Account', 'Ledger']

    @scenario
    def by_method_category(self):
        """AI: Narrowing to a method category keeps only senders filed under it - the way
        to exclude e.g. test methods from the result."""
        self.filters = {'method_categories': ['actions']}
        self.expected_classes = ['Account', 'Ledger']

    @scenario
    def by_side(self):
        """AI: Narrowing to instance side drops class-side senders."""
        self.filters = {'side': 'instance'}
        self.expected_classes = ['Account', 'AccountTest', 'Widget']

    @scenario
    def by_class_name_pattern(self):
        """AI: A class-name regex narrows to matching classes, e.g. excluding *Test."""
        self.filters = {'class_name_pattern': '^Account$'}
        self.expected_classes = ['Account']


@with_fixtures(SenderFilterFixture, SenderFilterScenarios)
def test_find_senders_narrows_candidates_by_facet_before_listing(fixture, scenario):
    """AI: Filters apply to the candidate summaries before counting and slicing, so the
    listed senders - and the reported total - reflect only the requested facet. This is
    what makes a selector with thousands of senders usable: ask for just the ones in the
    categories or side you care about."""
    result = fixture.browser_session.find_senders(
        'balance', granularity='identifier', **scenario.filters
    )

    listed_classes = sorted(sender['class_name'] for sender in result['senders'])
    assert listed_classes == scenario.expected_classes
    assert result['total_count'] == len(scenario.expected_classes)


@with_fixtures(SenderFilterFixture)
def test_empty_filter_lists_mean_no_constraint_not_match_nothing(fixture):
    """AI: The MCP validator turns an omitted category filter into an empty list, so an
    empty list must mean 'do not constrain', not 'must be in the empty set'. Otherwise an
    unfiltered request would silently drop every candidate (the gs_find_senders total=0
    regression)."""
    result = fixture.browser_session.find_senders(
        'balance', granularity='identifier', class_categories=[], method_categories=[]
    )

    assert result['total_count'] == 4
    assert result['returned_count'] == 4


@with_fixtures(SenderFilterFixture)
def test_find_senders_pages_with_offset_and_keeps_the_full_total(fixture):
    """AI: A page is a window over the candidates: offset skips earlier ones and
    max_results bounds how many come back, while total_count still reports the full
    matching count so a caller knows there is more and where the next page starts."""
    result = fixture.browser_session.find_senders(
        'balance', granularity='identifier', offset=1, max_results=2
    )

    assert [sender['class_name'] for sender in result['senders']] == [
        'AccountTest',
        'Ledger',
    ]
    assert result['total_count'] == 4
    assert result['offset'] == 1
