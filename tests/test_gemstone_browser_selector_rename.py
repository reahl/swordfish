from reahl.stubble import stubclass
from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException
from reahl.swordfish.gemstone.smalltalk_method_parser import (
    SmalltalkSyntaxError,
    SourceEdit,
)


class SelectorRenameFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None)


@with_fixtures(SelectorRenameFixture)
def test_keyword_selector_rename_keeps_unrelated_messages_unchanged(
    selector_rename_fixture,
):
    """AI: Renaming one keyword selector should not rewrite other selectors that share a keyword."""
    source = (
        'exercise\n'
        '    self oldSelector: 1 with: 2.\n'
        '    self otherSelector: 3 with: 4'
    )
    updated_source = selector_rename_fixture.browser_session.renamed_selector_source(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )
    assert 'self newSelector: 1 and: 2' in updated_source
    assert 'self otherSelector: 3 with: 4' in updated_source


@with_fixtures(SelectorRenameFixture)
def test_keyword_selector_rename_ignores_nested_keyword_messages(
    selector_rename_fixture,
):
    """AI: Renaming should target the selector occurrence, not nested keyword sends inside arguments."""
    source = 'exercise\n    self oldSelector: (self with: 1) with: 2'
    updated_source = selector_rename_fixture.browser_session.renamed_selector_source(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )
    assert 'self newSelector: (self with: 1) and: 2' in updated_source


@with_fixtures(SelectorRenameFixture)
def test_keyword_selector_rename_does_not_change_strings_or_comments(
    selector_rename_fixture,
):
    """AI: Selector rewrites should apply only to code, not string literals or Smalltalk comments."""
    source = (
        'exercise\n'
        '    self oldSelector: 1 with: 2.\n'
        "    'oldSelector: 3 with: 4'.\n"
        '    "oldSelector: 5 with: 6"'
    )
    updated_source = selector_rename_fixture.browser_session.renamed_selector_source(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )
    assert 'self newSelector: 1 and: 2' in updated_source
    assert "'oldSelector: 3 with: 4'" in updated_source
    assert '"oldSelector: 5 with: 6"' in updated_source


@with_fixtures(SelectorRenameFixture)
def test_keyword_selector_rename_handles_multiline_send_layout(
    selector_rename_fixture,
):
    """AI: Keyword selector rewrites should preserve multiline message layouts while changing selector tokens."""
    source = 'exercise\n    ^self\n        oldSelector: 1\n        with: 2'
    updated_source = selector_rename_fixture.browser_session.renamed_selector_source(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )
    assert 'newSelector: 1' in updated_source
    assert 'and: 2' in updated_source
    assert 'oldSelector:' not in updated_source
    assert 'with: 2' not in updated_source


@with_fixtures(SelectorRenameFixture)
def test_keyword_selector_rename_keeps_other_cascade_messages_unchanged(
    selector_rename_fixture,
):
    """AI: Rewriting one keyword send in a cascade should not alter subsequent cascade messages."""
    source = (
        'exercise\n'
        '    ^self\n'
        '        oldSelector: 1 with: 2;\n'
        '        yourself'
    )
    updated_source = selector_rename_fixture.browser_session.renamed_selector_source(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )
    assert 'newSelector: 1 and: 2;' in updated_source
    assert 'yourself' in updated_source


@with_fixtures(SelectorRenameFixture)
def test_selector_rename_source_edits_emits_one_edit_per_selector_token(
    selector_rename_fixture,
):
    """AI: selector_rename_source_edits is the AST-backed engine that the rename refactorings build on; each matching MessageSendNode contributes one SourceEdit per keyword piece of its selector, so the apply path can route those edits through compile_method_with_edits instead of recompiling a whole rewritten body."""
    source = 'exercise\n    self oldSelector: 1 with: 2'
    edits = selector_rename_fixture.browser_session.selector_rename_source_edits(
        source,
        'oldSelector:with:',
        'newSelector:and:',
    )

    assert len(edits) == 2
    assert [edit.replacement for edit in edits] == ['newSelector:', 'and:']
    assert [source[edit.start_offset:edit.end_offset] for edit in edits] == [
        'oldSelector:',
        'with:',
    ]


@with_fixtures(SelectorRenameFixture)
def test_selector_rename_source_edits_raises_when_keyword_counts_do_not_match(
    selector_rename_fixture,
):
    """AI: renaming a unary selector to a keyword selector (or any rename across different keyword counts) is structurally undefined; the engine raises rather than silently leaving the source unchanged - the old regex engine swallowed this and made the inconsistency invisible to the caller."""
    source = 'compute\n    ^self balance'
    with expected(DomainException):
        selector_rename_fixture.browser_session.selector_rename_source_edits(
            source,
            'balance',
            'totalAt:',
        )


@with_fixtures(SelectorRenameFixture)
def test_selector_rename_source_edits_raises_when_source_cannot_be_parsed(
    selector_rename_fixture,
):
    """AI: the AST-driven engine refuses to operate on unparseable source - without an AST it cannot tell a code occurrence from one inside a string literal, so silent fallback would be a correctness regression. Callers must hand it parseable source or surface the SmalltalkSyntaxError to the user."""
    source = 'compute\n    ^self balance +'
    with expected(SmalltalkSyntaxError):
        selector_rename_fixture.browser_session.selector_rename_source_edits(
            source,
            'balance',
            'currentBalance',
        )


@stubclass(GemstoneBrowserSession)
class RecordingApplyBrowserSession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession whose plan, compile, and delete entry points are
    replaced with recorders so we can prove that apply_selector_rename hands each
    per-method change to compile_method_with_edits with its AST-derived source_edits
    instead of recompiling a whole rewritten body via compile_method. The class lock
    against signature drift is what stubclass buys us here."""

    planned_changes_stub = None
    recorded_compile_with_edits_calls = None
    recorded_compile_method_calls = None
    recorded_delete_method_calls = None

    def ensure_refactoring_uses_real_ast(self, refactoring_name):
        return None

    def selector_rename_plan(self, old_selector, new_selector):
        return list(self.planned_changes_stub)

    def compile_method_with_edits(
        self,
        class_name,
        show_instance_side,
        original_source,
        source_edits,
        method_category='as yet unclassified',
    ):
        self.recorded_compile_with_edits_calls.append(
            {
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'original_source': original_source,
                'source_edits': list(source_edits),
                'method_category': method_category,
            }
        )

    def compile_method(
        self,
        class_name,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        self.recorded_compile_method_calls.append(
            {
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'source': source,
                'method_category': method_category,
            }
        )

    def delete_method(self, class_name, method_selector, show_instance_side):
        self.recorded_delete_method_calls.append(
            {
                'class_name': class_name,
                'method_selector': method_selector,
                'show_instance_side': show_instance_side,
            }
        )


class SelectorRenameApplyFixture(Fixture):
    def new_browser_session(self):
        browser_session = RecordingApplyBrowserSession(None)
        browser_session.recorded_compile_with_edits_calls = []
        browser_session.recorded_compile_method_calls = []
        browser_session.recorded_delete_method_calls = []
        return browser_session


@with_fixtures(SelectorRenameApplyFixture)
def test_apply_selector_rename_routes_each_change_through_compile_method_with_edits(
    fixture,
):
    """AI: rename apply hands each per-method change to compile_method_with_edits with the AST-derived SourceEdits, not to compile_method with a whole rewritten source string - that is what locks the rename onto the node-path apply mechanism so future per-edit deselection can filter the edits before they reach the image."""
    planned_changes = [
        {
            'class_name': 'Account',
            'show_instance_side': True,
            'method_selector': 'balance',
            'method_category': 'accessing',
            'change_type': 'implementor',
            'original_source': 'balance\n    ^balance',
            'source_edits': [SourceEdit(0, len('balance'), 'currentBalance')],
            'updated_source': 'currentBalance\n    ^balance',
        },
    ]
    fixture.browser_session.planned_changes_stub = planned_changes

    fixture.browser_session.apply_selector_rename('balance', 'currentBalance')

    assert len(fixture.browser_session.recorded_compile_with_edits_calls) == 1
    recorded = fixture.browser_session.recorded_compile_with_edits_calls[0]
    assert recorded['class_name'] == 'Account'
    assert recorded['original_source'] == 'balance\n    ^balance'
    assert len(recorded['source_edits']) == 1
    assert recorded['source_edits'][0].replacement == 'currentBalance'
    assert fixture.browser_session.recorded_compile_method_calls == []
