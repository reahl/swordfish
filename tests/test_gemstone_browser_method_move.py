from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


@stubclass(GemstoneBrowserSession)
class RecordingMoveBrowserSession(GemstoneBrowserSession):
    """AI: A GemstoneBrowserSession whose plan and compile entry points are recorded
    so we can prove apply_method_move routes the target-class recompile through
    compile_method_with_edits, not the legacy compile_method bypass. Even though
    move has no source edits today, going through compile_method_with_edits keeps
    every refactoring on the same apply primitive - which is the contract the
    universal edit-checklist dialog will read uniformly."""

    move_plan_stub = None
    recorded_compile_with_edits_calls = None
    recorded_compile_method_calls = None
    recorded_delete_method_calls = None

    def ensure_refactoring_uses_real_ast(self, refactoring_name):
        return None

    def method_move_plan(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        return dict(self.move_plan_stub)

    def method_move_summary(self, move_plan):
        return {'move_plan': move_plan}

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


class MethodMoveFixture(Fixture):
    def new_browser_session(self):
        browser_session = RecordingMoveBrowserSession(None)
        browser_session.recorded_compile_with_edits_calls = []
        browser_session.recorded_compile_method_calls = []
        browser_session.recorded_delete_method_calls = []
        return browser_session


@with_fixtures(MethodMoveFixture)
def test_apply_method_move_routes_target_recompile_through_compile_method_with_edits(
    fixture,
):
    """AI: method move currently has no source rewriting - the target-class compile is the source method's text verbatim. Even so, the apply path goes through compile_method_with_edits with an empty edit list, so every refactoring shares one apply primitive and any future move-time edits (adjusting self-sends, super-references etc.) can slot in without bypassing the node-path-addressed apply path."""
    fixture.browser_session.move_plan_stub = {
        'source_class_name': 'Account',
        'source_show_instance_side': True,
        'target_class_name': 'Customer',
        'target_show_instance_side': True,
        'method_selector': 'balance',
        'source_method_category': 'accessing',
        'source_method_source': 'balance\n    ^balance',
        'target_has_method': False,
    }

    fixture.browser_session.apply_method_move(
        'Account', True, 'Customer', True, 'balance',
    )

    assert len(fixture.browser_session.recorded_compile_with_edits_calls) == 1
    recorded = fixture.browser_session.recorded_compile_with_edits_calls[0]
    assert recorded['class_name'] == 'Customer'
    assert recorded['show_instance_side'] is True
    assert recorded['original_source'] == 'balance\n    ^balance'
    assert recorded['source_edits'] == []
    assert recorded['method_category'] == 'accessing'
    assert fixture.browser_session.recorded_compile_method_calls == []
