from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


def counts_by(grouping, key):
    """AI: Turn a bounded grouping's {'top': [{key: value, 'count': n}], ...} into a
    plain {value: n} dict so a test can assert the tallies without pinning tie-order."""
    return {pair[key]: pair['count'] for pair in grouping['top']}


@stubclass(GemstoneBrowserSession)
class OverviewSession(GemstoneBrowserSession):
    """AI: Stubs the single occurrence query the overview aggregates, and flags any
    source fetch - so a test can prove the count and breakdown tiers summarise from the
    one cheap round-trip and never pull method source."""

    canned_summaries = []
    source_was_fetched = False

    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        assert occurrence_type == 'senders'
        assert include_category_details is True
        return list(self.canned_summaries)

    def get_method_source(self, class_name, method_selector, show_instance_side):
        self.source_was_fetched = True
        return ''


class SendersOverviewFixture(Fixture):
    def new_browser_session(self):
        session = OverviewSession(None)
        session.canned_summaries = [
            {'class_name': 'Account', 'show_instance_side': True,
             'method_selector': 'post', 'class_category': 'Banking',
             'method_category': 'actions'},
            {'class_name': 'Account', 'show_instance_side': False,
             'method_selector': 'new', 'class_category': 'Banking',
             'method_category': 'instance creation'},
            {'class_name': 'Ledger', 'show_instance_side': True,
             'method_selector': 'record', 'class_category': 'Banking',
             'method_category': 'actions'},
            {'class_name': 'Widget', 'show_instance_side': True,
             'method_selector': 'draw', 'class_category': 'UI',
             'method_category': None},
        ]
        return session


@with_fixtures(SendersOverviewFixture)
def test_senders_count_is_just_total_and_side_split(fixture):
    """AI: The cheapest tier answers only 'how many, and how do they split across
    instance/class side' - a handful of integers - without any grouping or source, so it
    is always safe to return however hot the selector is."""
    count = fixture.browser_session.senders_count('balance')

    assert count == {'total': 4, 'by_side': {'instance': 3, 'class': 1}}
    assert fixture.browser_session.source_was_fetched is False


@with_fixtures(SendersOverviewFixture)
def test_senders_overview_adds_grouped_tallies_without_fetching_source(fixture):
    """AI: The breakdown tier adds, on top of the count, where the senders cluster -
    grouped by class category, method category, and per class - so the model can choose
    a filter. It is built from the same single query and never pulls method source."""
    overview = fixture.browser_session.senders_overview('balance')

    assert overview['total'] == 4
    assert overview['by_side'] == {'instance': 3, 'class': 1}
    assert counts_by(overview['by_class_category'], 'class_category') == {
        'Banking': 3,
        'UI': 1,
    }
    assert counts_by(overview['by_method_category'], 'method_category') == {
        'actions': 2,
        'instance creation': 1,
        None: 1,
    }
    assert counts_by(overview['classes'], 'class_name') == {
        'Account': 2,
        'Ledger': 1,
        'Widget': 1,
    }
    assert overview['classes']['top'][0]['class_name'] == 'Account'
    assert overview['classes']['remaining_values'] == 0
    assert fixture.browser_session.source_was_fetched is False


@with_fixtures(SendersOverviewFixture)
def test_overview_groupings_are_bounded_to_top_n_with_a_remaining_tail(fixture):
    """AI: A grouping must stay small however many distinct values there are: it keeps
    only the top-N most frequent and folds the rest into a remaining tally, so a selector
    spread over hundreds of classes still returns a compact, ranked summary."""
    overview = fixture.browser_session.senders_overview('balance', top=2)

    classes = overview['classes']
    assert [entry['class_name'] for entry in classes['top']] == ['Account', 'Ledger']
    assert classes['remaining_values'] == 1
    assert classes['remaining_count'] == 1
