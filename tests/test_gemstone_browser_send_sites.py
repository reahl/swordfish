from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class StubbedSenderSession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession with its two live dependencies for sender
    analysis stubbed - the occurrence query and source fetch - so the real
    find_senders/send-site slicing runs against fixed data. stubclass checks both
    overrides still match the real signatures."""

    senders = []
    sources = {}

    def selector_occurrence_summaries(
        self, method_name, occurrence_type, include_category_details=False
    ):
        return list(self.senders)

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.sources[(class_name, method_selector)]


class SenderSliceFixture(Fixture):
    def new_browser_session(self):
        return StubbedSenderSession(None)

    def given_senders(self, senders, sources):
        self.browser_session.senders = senders
        self.browser_session.sources = sources


@with_fixtures(SenderSliceFixture)
def test_send_site_granularity_returns_the_precise_call_not_the_whole_method(fixture):
    """AI: gs_find_senders defaults to returning each caller's exact send-site - the node_path and source of the call itself - so a caller sees how a selector is used without paying for whole method bodies (the find_referencing_symbols snippet analog)."""
    source = (
        'refresh\n'
        '    self balance isNil ifTrue: [^self].\n'
        '    ^dictionary at: #key put: self balance'
    )
    fixture.given_senders(
        [
            {
                'class_name': 'Account',
                'show_instance_side': True,
                'method_selector': 'refresh',
            }
        ],
        {('Account', 'refresh'): source},
    )
    sender = fixture.browser_session.find_senders('at:put:', granularity='send_site')[
        'senders'
    ][0]

    assert len(sender['send_sites']) == 1
    site = sender['send_sites'][0]
    assert site['node_path'] == 'method/statements[1]/expression'
    assert site['source'] == 'dictionary at: #key put: self balance'
    assert source[site['start'] : site['end']] == site['source']


@with_fixtures(SenderSliceFixture)
def test_a_selector_appearing_inside_a_string_is_not_reported_as_a_send(fixture):
    """AI: send-site detection runs on the AST, where a selector that merely appears inside a string literal is a LiteralNode and not a MessageSendNode - so it is correctly excluded, the accuracy a plain text search cannot give."""
    fixture.given_senders(
        [
            {
                'class_name': 'Logger',
                'show_instance_side': True,
                'method_selector': 'report',
            }
        ],
        {('Logger', 'report'): "report\n    ^'please at:put: into the log' size"},
    )
    sender = fixture.browser_session.find_senders('at:put:', granularity='send_site')[
        'senders'
    ][0]

    assert sender['send_sites'] == []


@with_fixtures(SenderSliceFixture)
def test_an_unparseable_sender_falls_back_to_the_whole_method_source(fixture):
    """AI: if a sender's source will not parse, send-site slicing degrades to the whole method source rather than dropping the sender, so a half-typed caller is still reported."""
    fixture.given_senders(
        [
            {
                'class_name': 'Broken',
                'show_instance_side': True,
                'method_selector': 'oops',
            }
        ],
        {('Broken', 'oops'): 'oops\n    ^[ '},
    )
    sender = fixture.browser_session.find_senders('at:put:', granularity='send_site')[
        'senders'
    ][0]

    assert sender['send_sites_unavailable'] == 'parse_error'
    assert sender['method_source'] == 'oops\n    ^[ '


@with_fixtures(SenderSliceFixture)
def test_method_granularity_returns_the_full_source_of_each_sender(fixture):
    """AI: granularity 'method' returns each sender's whole source - the explicit opt-out for callers that genuinely need the entire calling method."""
    fixture.given_senders(
        [
            {
                'class_name': 'Account',
                'show_instance_side': True,
                'method_selector': 'refresh',
            }
        ],
        {('Account', 'refresh'): 'refresh\n    ^dictionary at: #key put: 1'},
    )
    sender = fixture.browser_session.find_senders('at:put:', granularity='method')[
        'senders'
    ][0]

    assert sender['method_source'] == 'refresh\n    ^dictionary at: #key put: 1'
    assert 'send_sites' not in sender


@with_fixtures(SenderSliceFixture)
def test_identifier_granularity_keeps_the_lightweight_summary_without_source(fixture):
    """AI: the internal default granularity stays identifier-only - no source is fetched or returned - so existing in-process callers (impact analysis, tracing) pay no per-sender source round-trip."""
    fixture.given_senders(
        [
            {
                'class_name': 'Account',
                'show_instance_side': True,
                'method_selector': 'refresh',
            }
        ],
        {('Account', 'refresh'): 'refresh\n    ^dictionary at: #key put: 1'},
    )
    sender = fixture.browser_session.find_senders('at:put:')['senders'][0]

    assert sender == {
        'class_name': 'Account',
        'show_instance_side': True,
        'method_selector': 'refresh',
    }
