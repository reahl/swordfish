from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class MoveAndParamPreviewFixture(Fixture):
    """AI: Drives method_move_plan/apply_method_move and the
    add/remove parameter plans against a browser session whose I/O leaves
    (get_method_source, selector_occurrence_summaries, etc.) are replaced
    with deterministic recordings."""

    def new_browser_session(self):
        return GemstoneBrowserSession(None)

    def given_method(self, class_name, selector, source, instance_side=True):
        if not hasattr(self, 'method_sources_by_key'):
            self.method_sources_by_key = {}
            self.method_categories_by_key = {}
            self.recompiled_methods = []
            self.deleted_methods = []
            self.sender_summaries = []

            def fake_get_method_source(class_name, method_selector, show_instance_side):
                return self.method_sources_by_key[
                    (class_name, method_selector, show_instance_side)
                ]

            def fake_get_method_category(class_name, method_selector, show_instance_side):
                return self.method_categories_by_key.get(
                    (class_name, method_selector, show_instance_side),
                    'testing',
                )

            def fake_compile_method(**kwargs):
                self.recompiled_methods.append(kwargs)

            def fake_delete_method(class_name, method_selector, show_instance_side):
                self.deleted_methods.append(
                    (class_name, method_selector, show_instance_side)
                )

            def fake_selector_occurrence_summaries(method_name, occurrence_type, include_category_details=False):
                return [
                    sender_summary
                    for sender_summary in self.sender_summaries
                    if sender_summary['method_selector_target'] == method_name
                ]

            def fake_method_exists(class_name, method_selector, show_instance_side):
                return (
                    (class_name, method_selector, show_instance_side)
                    in self.method_sources_by_key
                )

            def fake_method_argument_names_for_method(class_name, show_instance_side, method_selector):
                method_source = self.method_sources_by_key[
                    (class_name, method_selector, show_instance_side)
                ]
                return self.browser_session.method_argument_names(
                    method_source,
                    method_selector,
                )

            def fake_class_to_query(class_name, show_instance_side):
                class FakeQueryHandle:
                    pass

                return FakeQueryHandle()

            def fake_sorted_selectors(class_to_query):
                return []

            self.browser_session.get_method_source = fake_get_method_source
            self.browser_session.get_method_category = fake_get_method_category
            self.browser_session.compile_method = fake_compile_method
            self.browser_session.delete_method = fake_delete_method
            self.browser_session.selector_occurrence_summaries = (
                fake_selector_occurrence_summaries
            )
            self.browser_session.method_exists = fake_method_exists
            self.browser_session.method_argument_names_for_method = (
                fake_method_argument_names_for_method
            )
            self.browser_session.class_to_query = fake_class_to_query
            self.browser_session.sorted_selectors = fake_sorted_selectors

        self.method_sources_by_key[(class_name, selector, instance_side)] = source

    def given_sender(self, sender_class, sender_selector, target_selector):
        self.sender_summaries.append(
            {
                'class_name': sender_class,
                'show_instance_side': True,
                'method_selector': sender_selector,
                'method_selector_target': target_selector,
            }
        )


@with_fixtures(MoveAndParamPreviewFixture)
def test_add_parameter_preview_includes_new_signature_and_compatibility_wrapper(
    fixture,
):
    """AI: Callers need to show users the new method signature and the
    forwarder body before commit. The preview shape was metadata-only —
    no signature, no wrapper source. We expose both."""
    fixture.given_method(
        'OrderLine',
        'process:',
        'process: aValue\n    ^ aValue * 2',
    )

    add_parameter_plan = (
        fixture.browser_session.method_add_parameter_plan(
            'OrderLine',
            True,
            'process:',
            'factor:',
            'aFactor',
            '2',
        )
    )
    summary = fixture.browser_session.method_add_parameter_summary(
        add_parameter_plan
    )

    assert summary['new_method_header'] == 'process: aValue factor: aFactor'
    assert summary['compatibility_wrapper_source'].startswith('process: aValue\n')
    assert '^self process: aValue factor: 2' in summary['compatibility_wrapper_source']


@with_fixtures(MoveAndParamPreviewFixture)
def test_apply_method_move_rewrites_same_class_unary_sender_to_helper_receiver(
    fixture,
):
    """AI: When the user opts in to rewrite_source_senders with a helper
    receiver expression, every static same-class send-site of the moved
    selector has its receiver replaced. The source method can then be
    deleted without leaving callers stranded."""
    fixture.given_method(
        'Account',
        'middlePair',
        'middlePair\n    ^ 2 + 2',
    )
    fixture.given_method(
        'Account',
        'caller',
        'caller\n    self middlePair.\n    ^ self',
    )
    fixture.given_method(
        'AccountHelper',
        'describe',
        "describe\n    ^ 'helper'",
        instance_side=True,
    )
    fixture.given_sender('Account', 'caller', 'middlePair')

    apply_result = fixture.browser_session.apply_method_move(
        'Account',
        True,
        'AccountHelper',
        True,
        'middlePair',
        delete_source_method=True,
        rewrite_source_senders=True,
        helper_receiver_source='self helper',
    )

    recompiled_callers = [
        recompile
        for recompile in fixture.recompiled_methods
        if recompile.get('class_name') == 'Account'
    ]
    assert recompiled_callers, fixture.recompiled_methods
    rewritten_caller_source = recompiled_callers[0]['source']
    assert 'self helper middlePair' in rewritten_caller_source, (
        rewritten_caller_source
    )
    assert apply_result['rewritten_sender_count'] == 1
