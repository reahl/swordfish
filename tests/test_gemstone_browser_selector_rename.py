from reahl.tofu import Fixture
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


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
    source = (
        'exercise\n'
        '    self oldSelector: (self with: 1) with: 2'
    )
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
