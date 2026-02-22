from reahl.tofu import Fixture
from reahl.tofu import NoException
from reahl.tofu import expected
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException


class StrictAstEnforcementFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None, require_gemstone_ast=True)


@with_fixtures(StrictAstEnforcementFixture)
def test_strict_ast_guard_attempts_auto_install_when_possible(
    strict_ast_enforcement_fixture,
):
    """AI: Strict AST guard should auto-install image support before failing a refactoring action."""
    install_calls = []
    backend_state = {'available': False}

    strict_ast_enforcement_fixture.browser_session.can_attempt_ast_support_auto_install = (
        lambda: True
    )
    strict_ast_enforcement_fixture.browser_session.has_real_gemstone_ast_backend = (
        lambda: backend_state['available']
    )

    def install_or_refresh_ast_support():
        install_calls.append('attempted')
        backend_state['available'] = True

    strict_ast_enforcement_fixture.browser_session.install_or_refresh_ast_support = (
        install_or_refresh_ast_support
    )

    with expected(NoException):
        strict_ast_enforcement_fixture.browser_session.ensure_refactoring_uses_real_ast(
            'extract method preview'
        )

    assert install_calls == ['attempted']


@with_fixtures(StrictAstEnforcementFixture)
def test_strict_ast_guard_raises_when_auto_install_does_not_make_backend_available(
    strict_ast_enforcement_fixture,
):
    """AI: Strict AST guard should still fail fast when backend remains unavailable after auto-install attempt."""
    strict_ast_enforcement_fixture.browser_session.can_attempt_ast_support_auto_install = (
        lambda: True
    )
    strict_ast_enforcement_fixture.browser_session.has_real_gemstone_ast_backend = (
        lambda: False
    )

    def install_or_refresh_ast_support():
        raise DomainException('install failed')

    strict_ast_enforcement_fixture.browser_session.install_or_refresh_ast_support = (
        install_or_refresh_ast_support
    )

    with expected(DomainException):
        strict_ast_enforcement_fixture.browser_session.ensure_refactoring_uses_real_ast(
            'extract method preview'
        )
