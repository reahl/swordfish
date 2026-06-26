from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.smalltalk_source_scanner import (
    SmalltalkSourceScanner,
    SmalltalkTokenKind,
)
from reahl.swordfish.text_editing import CodePanel


class RecordingTextEditor:
    """AI: Stands in for the Tk Text widget, recording the tag operations highlighting performs."""

    def __init__(self):
        self.added = []
        self.removed = []
        self.source_text = ''

    def tag_add(self, tag_name, start, end):
        self.added.append((tag_name, start, end))

    def tag_remove(self, tag_name, start, end):
        self.removed.append((tag_name, start, end))

    def get(self, start, end):
        return self.source_text


class HighlightingCodePanel:
    """AI: A CodePanel stripped of Tk construction, reusing the real highlighting methods against a recording editor."""

    token_tag_for_kind = CodePanel.token_tag_for_kind
    syntax_tag_names = CodePanel.syntax_tag_names
    apply_syntax_highlighting = CodePanel.apply_syntax_highlighting
    apply_occurrence_highlight = CodePanel.apply_occurrence_highlight
    clear_occurrence_highlight = CodePanel.clear_occurrence_highlight

    def __init__(self):
        self.source_scanner = SmalltalkSourceScanner()
        self.text_editor = RecordingTextEditor()


class HighlightingFixture(Fixture):
    def new_code_panel(self):
        return HighlightingCodePanel()

    def added_tags(self):
        return [tag_name for tag_name, _, _ in self.code_panel.text_editor.added]

    def removed_tags(self):
        return [tag_name for tag_name, _, _ in self.code_panel.text_editor.removed]


@with_fixtures(HighlightingFixture)
def test_token_kinds_map_to_their_colour_tags(highlighting_fixture):
    """AI: Highlighting is driven by token kind, so a pseudo-variable colours as a keyword and a string literal as a string, while structural tokens stay uncoloured."""
    code_panel = highlighting_fixture.code_panel

    assert (
        code_panel.token_tag_for_kind(SmalltalkTokenKind.pseudo_variable)
        == 'smalltalk_keyword'
    )
    assert (
        code_panel.token_tag_for_kind(SmalltalkTokenKind.string_literal)
        == 'smalltalk_string'
    )
    assert code_panel.token_tag_for_kind(SmalltalkTokenKind.whitespace) is None


@with_fixtures(HighlightingFixture)
def test_rehighlighting_clears_a_now_obsolete_string_tag(highlighting_fixture):
    """AI: Each highlight pass first clears the syntax tags, so a string colour left from earlier text does not linger once the string is gone."""
    code_panel = highlighting_fixture.code_panel

    code_panel.apply_syntax_highlighting("'a string'")
    assert 'smalltalk_string' in highlighting_fixture.added_tags()

    code_panel.text_editor.added.clear()
    code_panel.text_editor.removed.clear()
    code_panel.apply_syntax_highlighting('plainIdentifier')

    assert 'smalltalk_string' in highlighting_fixture.removed_tags()
    assert 'smalltalk_string' not in highlighting_fixture.added_tags()


@with_fixtures(HighlightingFixture)
def test_apply_occurrence_highlight_tags_all_occurrences_of_the_variable(highlighting_fixture):
    """AI: apply_occurrence_highlight must add the occurrence_highlight tag at every token
    position where the variable name appears, ignoring string literals and comments
    that happen to contain the same text."""
    code_panel = highlighting_fixture.code_panel
    source = 'printOn: aStream\n    currency printString\n    ^ currency'
    code_panel.text_editor.source_text = source

    code_panel.apply_occurrence_highlight('currency')

    tagged_ranges = [
        (start, end)
        for tag, start, end in code_panel.text_editor.added
        if tag == 'occurrence_highlight'
    ]
    # AI: Two occurrences of 'currency' as identifiers in the source.
    assert len(tagged_ranges) == 2
    for start, end in tagged_ranges:
        offset = int(start.split('+ ')[1].split(' chars')[0])
        assert source[offset:offset + len('currency')] == 'currency'


@with_fixtures(HighlightingFixture)
def test_apply_occurrence_highlight_marks_keyword_selector_sends(highlighting_fixture):
    """AI: The same highlight serves senders, so a keyword selector (a
    keyword_message_part token, not an identifier) must be marked where it is sent."""
    code_panel = highlighting_fixture.code_panel
    source = 'store: anItem\n    collection printOn: aStream'
    code_panel.text_editor.source_text = source

    code_panel.apply_occurrence_highlight('printOn:')

    tagged_ranges = [
        (start, end)
        for tag, start, end in code_panel.text_editor.added
        if tag == 'occurrence_highlight'
    ]
    assert len(tagged_ranges) == 1
    start, end = tagged_ranges[0]
    offset = int(start.split('+ ')[1].split(' chars')[0])
    assert source[offset:offset + len('printOn:')] == 'printOn:'


@with_fixtures(HighlightingFixture)
def test_apply_occurrence_highlight_marks_class_name_references(highlighting_fixture):
    """AI: The same highlight serves class-reference searches, so a class name is marked
    where it is referenced (and not where a same-named keyword/comment text appears)."""
    code_panel = highlighting_fixture.code_panel
    source = 'build\n    ^ OrderLine new register: OrderLine'
    code_panel.text_editor.source_text = source

    code_panel.apply_occurrence_highlight('OrderLine')

    tagged_ranges = [
        (start, end)
        for tag, start, end in code_panel.text_editor.added
        if tag == 'occurrence_highlight'
    ]
    assert len(tagged_ranges) == 2


@with_fixtures(HighlightingFixture)
def test_apply_occurrence_highlight_clears_previous_before_reapplying(highlighting_fixture):
    """AI: Calling apply_occurrence_highlight twice must remove the previous tag before
    adding new ranges, so stale highlights from an earlier method do not accumulate."""
    code_panel = highlighting_fixture.code_panel
    code_panel.text_editor.source_text = 'currency\n    ^ currency'

    code_panel.apply_occurrence_highlight('currency')
    code_panel.text_editor.removed.clear()
    code_panel.text_editor.added.clear()
    code_panel.apply_occurrence_highlight('currency')

    assert any(tag == 'occurrence_highlight' for tag, _, _ in code_panel.text_editor.removed)
