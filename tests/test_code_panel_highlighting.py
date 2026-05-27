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

    def tag_add(self, tag_name, start, end):
        self.added.append((tag_name, start, end))

    def tag_remove(self, tag_name, start, end):
        self.removed.append((tag_name, start, end))


class HighlightingCodePanel:
    """AI: A CodePanel stripped of Tk construction, reusing the real highlighting methods against a recording editor."""

    token_tag_for_kind = CodePanel.token_tag_for_kind
    syntax_tag_names = CodePanel.syntax_tag_names
    apply_syntax_highlighting = CodePanel.apply_syntax_highlighting

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
