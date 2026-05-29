from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class ParsedSendsFixture(Fixture):
    """AI: Drives the source-only send/control-flow summary methods on
    GemstoneBrowserSession directly, since they're pure source analyses
    that need no GemStone session."""

    def new_browser_session(self):
        return GemstoneBrowserSession(None)


@with_fixtures(ParsedSendsFixture)
def test_method_sends_lists_cascade_messages_as_separate_sends(fixture):
    """AI: A cascade 'Transcript show: x; cr' is two sends — 'show:' and
    'cr' — sharing one receiver. The heuristic send detector used to merge
    them into a single 'show:cr' selector. The parser-backed analysis
    enumerates each cascade message as its own send entry."""
    source = (
        "announce\n"
        "    Transcript show: 'hello'; cr.\n"
        "    ^ self"
    )

    sends_summary = fixture.browser_session.source_method_sends(source)
    selectors = [send['selector'] for send in sends_summary['sends']]

    assert 'show:' in selectors, selectors
    assert 'cr' in selectors, selectors
    # AI: No merged 'show:cr' (or 'show:;cr') selectors leak through.
    merged_selectors = [
        selector for selector in selectors if ';' in selector
    ]
    assert merged_selectors == [], merged_selectors


@with_fixtures(ParsedSendsFixture)
def test_method_sends_does_not_merge_pragma_into_following_send(fixture):
    """AI: A '<primitive: 817>' pragma must not be glued onto the next
    keyword send. The heuristic detector reported 'primitive:ifTrue:' as
    a single selector on OrderedCollection >> copyFrom:to:. The
    parser-backed analysis sees them as the distinct sends they are."""
    source = (
        "boundsCheck: startIndex\n"
        "    <primitive: 817>\n"
        "    (startIndex < 1) ifTrue: [ ^ self error: startIndex ].\n"
        "    ^ self"
    )

    sends_summary = fixture.browser_session.source_method_sends(source)
    selectors = [send['selector'] for send in sends_summary['sends']]

    assert 'ifTrue:' in selectors, selectors
    merged_pragma_selectors = [
        selector for selector in selectors if 'primitive:' in selector
    ]
    assert merged_pragma_selectors == [], merged_pragma_selectors


@with_fixtures(ParsedSendsFixture)
def test_method_sends_does_not_double_record_cascade_messages(fixture):
    """AI: My first parser-backed walker recorded each cascade message
    twice — once via CascadeNode's explicit messages iteration (with
    receiver_hint='cascade'), and once via the recursive descent through
    labelled_child_nodes(), where the same messages also appear. Each
    cascade message is one send: descent through a CascadeNode must not
    re-enumerate its messages."""
    source = (
        "multiCascade\n"
        "    ^ Transcript show: 'a'; show: 'b'; show: 'c'"
    )

    sends_summary = fixture.browser_session.source_method_sends(source)
    show_entries = [
        send for send in sends_summary['sends'] if send['selector'] == 'show:'
    ]

    assert len(show_entries) == 3, sends_summary['sends']
    # AI: All three records belong to the cascade so all carry the
    # cascade receiver hint.
    cascade_hint_count = sum(
        1
        for send in show_entries
        if send['receiver_hint'] == 'cascade'
    )
    assert cascade_hint_count == 3, show_entries


@with_fixtures(ParsedSendsFixture)
def test_method_structure_summary_does_not_count_float_literal_dots_as_statement_terminators(
    fixture,
):
    """AI: The character-walking structure summary counted every '.' in
    the method body, including the period inside a float literal like
    '3.14'. A return of a single float-literal expression has zero
    terminators between statements; the parser-backed walk reports the
    real statement count and derives terminators from that."""
    source = "describePi\n    ^ 3.14 printString"

    summary = fixture.browser_session.source_method_structure_summary(source)

    assert summary['statement_terminator_count'] == 0, summary
    assert summary['return_count'] == 1


@with_fixtures(ParsedSendsFixture)
def test_method_structure_summary_counts_cascade_expressions_not_message_separators(
    fixture,
):
    """AI: One cascade expression with three messages used to report
    cascade_count = 2 (two ';' separators). The parser-backed walk
    reports one cascade — the count of CascadeNode instances — which is
    the conceptual unit a navigation heuristic actually wants."""
    source = (
        "summarize\n"
        "    ^ self\n"
        "        yourself;\n"
        "        yourself;\n"
        "        default"
    )

    summary = fixture.browser_session.source_method_structure_summary(source)

    assert summary['cascade_count'] == 1, summary


@with_fixtures(ParsedSendsFixture)
def test_method_control_flow_summary_counts_branches_under_parenthesised_receivers(
    fixture,
):
    """AI: The heuristic control-flow detector reported zero 'ifTrue:'
    when the receiver was a parenthesised expression like
    '(startIndex < 1) ifTrue: [...]'. The parser sees the message_send
    node regardless of receiver shape and counts it correctly."""
    source = (
        "boundsCheck: startIndex\n"
        "    (startIndex < 1) ifTrue: [ ^ self error: startIndex ].\n"
        "    ((startIndex > 10) or: [startIndex < 0]) ifTrue: [ ^ self ].\n"
        "    ^ self"
    )

    control_flow_summary = (
        fixture.browser_session.source_method_control_flow_summary(source)
    )
    control_selector_counts = control_flow_summary[
        'control_selector_counts'
    ]

    assert control_selector_counts['ifTrue:'] == 2, control_selector_counts
    assert control_flow_summary['branch_selector_count'] == 2
