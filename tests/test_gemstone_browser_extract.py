from reahl.tofu import Fixture
from reahl.tofu import expected
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException


class ExtractPlanningFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None)

    def set_method_source(self, method_source):
        self.method_source = method_source
        self.browser_session.get_method_source = (
            lambda class_name, method_selector, show_instance_side: self.method_source
        )
        self.browser_session.method_ast = (
            lambda class_name, method_selector, show_instance_side: (
                self.browser_session.source_method_ast(
                    self.method_source,
                    method_selector,
                )
            )
        )
        self.browser_session.method_argument_names_for_method = (
            lambda class_name, show_instance_side, method_selector: (
                self.browser_session.method_argument_names(
                    self.method_source,
                    method_selector,
                )
            )
        )
        self.browser_session.get_method_category = (
            lambda class_name, method_selector, show_instance_side: 'testing'
        )
        self.browser_session.method_exists = (
            lambda class_name, method_selector, show_instance_side: False
        )


@with_fixtures(ExtractPlanningFixture)
def test_extract_plan_keyword_selector_infers_argument_names_and_rewrites_call(
    extract_planning_fixture,
):
    """AI: Keyword extract should infer caller-scoped argument names and build matching keyword call/send headers."""
    extract_planning_fixture.set_method_source(
        'buildFrom: input\n'
        '    | tmp |\n'
        '    tmp := input + 1.\n'
        '    ^tmp'
    )

    extract_plan = extract_planning_fixture.browser_session.method_extract_plan(
        'OrderLine',
        True,
        'buildFrom:',
        'extractedComputeTmp:',
        [1],
    )

    assert extract_plan['extracted_argument_names'] == ['input']
    assert extract_plan['new_method_source'].startswith(
        'extractedComputeTmp: input\n'
    )
    assert 'self extractedComputeTmp: input' in extract_plan[
        'updated_method_source'
    ]


@with_fixtures(ExtractPlanningFixture)
def test_extract_plan_unary_selector_rejected_when_caller_variables_are_needed(
    extract_planning_fixture,
):
    """AI: Extract should fail fast when a unary selector is chosen but selected statements depend on caller variables."""
    extract_planning_fixture.set_method_source(
        'buildFrom: input\n'
        '    | tmp |\n'
        '    tmp := input + 1.\n'
        '    ^tmp'
    )

    with expected(DomainException):
        extract_planning_fixture.browser_session.method_extract_plan(
            'OrderLine',
            True,
            'buildFrom:',
            'extractedComputeTmp',
            [1],
        )


@with_fixtures(ExtractPlanningFixture)
def test_extract_plan_unary_selector_still_works_when_no_arguments_are_needed(
    extract_planning_fixture,
):
    """AI: Unary extract remains valid for statement selections that do not capture caller-scoped variables."""
    extract_planning_fixture.set_method_source(
        'exampleMethod\n'
        '    self yourself.\n'
        '    self class.\n'
        '    ^7'
    )

    extract_plan = extract_planning_fixture.browser_session.method_extract_plan(
        'OrderLine',
        True,
        'exampleMethod',
        'extractedFirstStep',
        [1],
    )

    assert extract_plan['extracted_argument_names'] == []
    assert extract_plan['new_method_source'].startswith('extractedFirstStep\n')
    assert 'self extractedFirstStep' in extract_plan['updated_method_source']
