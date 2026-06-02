from reahl.stubble import stubclass
from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class ClassifyingSession(GemstoneBrowserSession):
    """AI: Stubs the candidate query and the per-method source fetch so the real AST
    classification runs against fixed sources - proving how a send is told apart from a
    bare #selector reference, without a live image."""

    candidates = []
    sources = {}

    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        return [dict(candidate) for candidate in self.candidates]

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.sources[class_name]


def candidate(class_name):
    return {
        'class_name': class_name,
        'show_instance_side': True,
        'method_selector': 'caller',
    }


class ClassificationFixture(Fixture):
    def session_with(self, class_name, source):
        session = ClassifyingSession(None)
        session.candidates = [candidate(class_name)]
        session.sources = {class_name: source}
        return session


class ClassificationScenarios(Fixture):
    @scenario
    def real_send_to_self(self):
        """AI: A message_send node for the selector is a genuine send."""
        self.source = 'caller\n    ^self foo: 1'
        self.expected_kind = 'direct_send'

    @scenario
    def reflective_send_via_perform(self):
        """AI: A #selector handed to perform: is a real dynamic send, not mere data, so
        it must be kept (as reflective) rather than dropped."""
        self.source = 'caller\n    ^self perform: #foo: with: 1'
        self.expected_kind = 'reflective_send'

    @scenario
    def symbol_reference_elsewhere(self):
        """AI: A #selector literal used anywhere other than a perform: arg is only a
        reference - flagged, not treated as a send."""
        self.source = 'caller\n    ^self register: #foo:'
        self.expected_kind = 'reference_only'


@with_fixtures(ClassificationFixture, ClassificationScenarios)
def test_send_site_classification_distinguishes_send_from_reference(fixture, scenario):
    """AI: Senders come from the symbol-reference index, which cannot tell a real send
    from a #selector literal. The AST pass classifies each candidate so the noise can be
    told apart - while a perform: literal is preserved as a real (dynamic) send."""
    session = fixture.session_with('Caller', scenario.source)

    sender = session.find_senders('foo:', granularity='send_site')['senders'][0]

    assert sender['kind'] == scenario.expected_kind


@stubclass(GemstoneBrowserSession)
class ThreeKindSession(GemstoneBrowserSession):
    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        return [candidate('Direct'), candidate('Reflective'), candidate('RefOnly')]

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return {
            'Direct': 'caller\n    ^self foo: 1',
            'Reflective': 'caller\n    ^self perform: #foo: with: 1',
            'RefOnly': 'caller\n    ^self register: #foo:',
        }[class_name]


class RealSendsFixture(Fixture):
    def new_session(self):
        return ThreeKindSession(None)


@with_fixtures(RealSendsFixture)
def test_real_sends_only_drops_references_but_keeps_perform_sends(fixture):
    """AI: real_sends_only removes the symbol-reference noise (reference_only) while
    keeping both direct and reflective (perform:) sends, and reports how many references
    it set aside so nothing is silently lost."""
    result = fixture.session.find_senders(
        'foo:', granularity='send_site', real_sends_only=True
    )

    kinds = sorted(sender['kind'] for sender in result['senders'])
    assert kinds == ['direct_send', 'reflective_send']
    assert result['reference_only_omitted'] == 1
    assert result['total_count'] == 3


@stubclass(GemstoneBrowserSession)
class BigSendSession(GemstoneBrowserSession):
    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        return [candidate('Big%s' % index) for index in range(5)]

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return "caller\n    ^self foo: '%s'" % ('x' * 400)


class BudgetFixture(Fixture):
    def new_session(self):
        return BigSendSession(None)


@with_fixtures(BudgetFixture)
def test_find_senders_stops_at_the_response_budget_and_pages_the_rest(fixture):
    """AI: However large each send-site slice is, the page is held under the char budget:
    entries are kept until the next would exceed it, then it stops with budget_reached and
    a next_offset that resumes exactly where it left off - so a single hot selector can
    never overflow the token limit, but nothing is skipped."""
    result = fixture.session.find_senders(
        'foo:', granularity='send_site', max_response_chars=600
    )

    assert result['budget_reached'] is True
    assert result['returned_count'] < 5
    assert result['truncated'] is True
    assert result['next_offset'] == result['returned_count']
    assert result['total_count'] == 5
