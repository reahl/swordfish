from reahl.tofu import Fixture
from reahl.tofu import with_fixtures
from unittest.mock import call
from unittest.mock import Mock

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException


class TracerSourceFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None)


@with_fixtures(TracerSourceFixture)
def test_binary_selector_tracer_alias_is_valid_binary_selector(
    tracer_source_fixture,
):
    """AI: Tracer aliases for binary selectors must remain valid binary selectors so instrumentation compiles."""
    alias_selector = tracer_source_fixture.browser_session.tracer_alias_selector(
        '+'
    )
    assert alias_selector != '+'
    assert tracer_source_fixture.browser_session.is_binary_selector(
        alias_selector
    )


@with_fixtures(TracerSourceFixture)
def test_binary_selector_tracer_wrapper_uses_binary_method_header_shape(
    tracer_source_fixture,
):
    """AI: Binary sender wrappers must include the binary argument in both header and alias send."""
    alias_selector = tracer_source_fixture.browser_session.tracer_alias_selector(
        '+'
    )
    wrapper_source = (
        tracer_source_fixture.browser_session.tracer_sender_wrapper_source(
            '+',
            alias_selector,
            'total',
            'OrderLine',
            True,
        )
    )
    assert wrapper_source.startswith('+ argument1\n')
    assert ('^self %s argument1' % alias_selector) in wrapper_source


@with_fixtures(TracerSourceFixture)
def test_unary_selector_tracer_wrapper_keeps_unary_header_shape(
    tracer_source_fixture,
):
    """AI: Unary sender wrappers should remain unary methods and invoke the unary alias send."""
    alias_selector = tracer_source_fixture.browser_session.tracer_alias_selector(
        'total'
    )
    wrapper_source = (
        tracer_source_fixture.browser_session.tracer_sender_wrapper_source(
            'total',
            alias_selector,
            'subtotal',
            'OrderLine',
            True,
        )
    )
    assert wrapper_source.startswith('total\n')
    assert ('^self %s' % alias_selector) in wrapper_source


@with_fixtures(TracerSourceFixture)
def test_trace_selector_skips_compile_failures_and_continues(
    tracer_source_fixture,
):
    """AI: Tracing should skip uninstrumentable senders instead of aborting the full tracing run."""
    browser_session = tracer_source_fixture.browser_session
    browser_session.run_code = Mock(return_value=Mock(to_py=''))
    browser_session.find_senders = Mock(
        return_value={
            'total_count': 2,
            'senders': [
                {
                    'class_name': 'PrimitiveHost',
                    'show_instance_side': True,
                    'method_selector': '+',
                },
                {
                    'class_name': 'OrderLine',
                    'show_instance_side': True,
                    'method_selector': 'total',
                },
            ],
        }
    )
    browser_session.list_methods = Mock(return_value=[])
    browser_session.get_method_source = Mock(
        side_effect=[
            '+ argument1\n    ^self primitiveFailed',
            'total\n    ^amount * quantity',
        ],
    )
    browser_session.get_method_category = Mock(return_value='accessing')

    def compile_with_primitive_failure(
        class_name,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        if class_name == 'PrimitiveHost':
            raise DomainException(
                'compiling a primitive method requires CompilePrimitives privilege'
            )
        return Mock()

    browser_session.compile_method = Mock(
        side_effect=compile_with_primitive_failure
    )
    browser_session.delete_method = Mock()

    trace_result = browser_session.trace_selector('ifTrue:')

    assert trace_result['traced_sender_count'] == 1
    assert trace_result['skipped_sender_count'] == 1
    assert trace_result['traced_senders'] == [
        {
            'class_name': 'OrderLine',
            'show_instance_side': True,
            'method_selector': 'total',
            'alias_selector': 'swordfishMcpTracerOriginal__total',
        },
    ]
    skipped_sender = trace_result['skipped_senders'][0]
    assert skipped_sender['class_name'] == 'PrimitiveHost'
    assert skipped_sender['method_selector'] == '+'
    assert 'CompilePrimitives privilege' in skipped_sender['error_message']

    register_calls = [
        run_code_call
        for run_code_call in browser_session.run_code.call_args_list
        if 'registerInstrumentationForTarget:' in run_code_call.args[0]
    ]
    assert len(register_calls) == 1
    assert browser_session.find_senders.call_args_list == [
        call(
            'ifTrue:',
            max_results=None,
            count_only=False,
        )
    ]
