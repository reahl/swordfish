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


@with_fixtures(StrictAstEnforcementFixture)
def test_method_ast_attempts_support_install_before_analysis(
    strict_ast_enforcement_fixture,
):
    """AI: Method AST should attempt AST support installation so class support lands in Swordfish package."""
    install_checks = []
    browser_session = strict_ast_enforcement_fixture.browser_session

    browser_session.ensure_ast_support_installed_when_possible = (
        lambda: install_checks.append('checked')
    )
    browser_session.get_method_source = (
        lambda class_name, method_selector, show_instance_side: (
            '%s\n    ^self' % method_selector
        )
    )
    browser_session.source_method_ast = lambda source, method_selector: {
        'analysis_limitations': [],
        'temporaries': [],
    }
    browser_session.compiled_method_argument_and_temporary_names = (
        lambda class_name, method_selector, show_instance_side: {
            'argument_names': [],
            'temporary_names': [],
        }
    )

    method_ast = browser_session.method_ast('Object', 'yourself', True)

    assert install_checks == ['checked']
    assert method_ast['analysis_backend'] == 'gemstone_compiled_method_metadata'


@with_fixtures(StrictAstEnforcementFixture)
def test_ast_support_installation_is_attempted_when_any_requirement_missing(
    strict_ast_enforcement_fixture,
):
    """AI: AST support installation should run when package, class support, or manifest state is missing."""
    install_calls = []
    browser_session = strict_ast_enforcement_fixture.browser_session

    browser_session.can_attempt_ast_support_auto_install = lambda: True
    browser_session.package_exists = lambda package_name: False
    browser_session.ast_support_class_installed_in_swordfish = (
        lambda: False
    )
    browser_session.ast_support_manifest_matches_expected = lambda: False
    browser_session.install_or_refresh_ast_support = lambda: install_calls.append(
        'attempted'
    )

    with expected(NoException):
        browser_session.ensure_ast_support_installed_when_possible()

    assert install_calls == ['attempted']
