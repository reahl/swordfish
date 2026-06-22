from unittest.mock import Mock, patch

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.session_activity import ForegroundActivity
from reahl.swordfish.test_execution import TestExecution


class FakeGemstoneError(GemstoneError):
    """AI: Minimal GemstoneError for testing - bypasses the real constructor which requires an
    active session and a C error structure."""

    def __init__(self):
        pass


def test_running_tests_is_an_interruptible_foreground_activity():
    """AI: Running tests goes through the foreground-activity runner, so the single menu-bar Stop
    can abandon a long suite; the result reporter is the activity's completion handler."""
    application = Mock()
    reporter = Mock()
    execution = TestExecution(
        application,
        'Running...',
        lambda should_stop: 'result',
        reporter,
        'Run Test',
    )

    execution.start()

    application.run_foreground_activity.assert_called_once()
    activity = application.run_foreground_activity.call_args[0][0]
    assert isinstance(activity, ForegroundActivity)
    assert activity.on_finished is reporter


def test_a_test_error_trap_opens_the_debugger():
    """AI: A genuine error raised while running tests (a GemstoneError) is a trap the user must
    inspect on the stack, so it opens the debugger rather than a dialog."""
    application = Mock()
    execution = TestExecution(
        application, 'Running...', lambda should_stop: None, Mock(), 'Run Test'
    )
    error = FakeGemstoneError()

    execution.report_failure(error)

    application.open_debugger.assert_called_once_with(error)


def test_a_non_trap_test_failure_is_shown_as_a_dialog_not_the_debugger():
    """AI: A non-trap failure (e.g. an invalid request) is shown as an error dialog, leaving the
    debugger reserved for genuine runtime traps."""
    application = Mock()
    execution = TestExecution(
        application, 'Running...', lambda should_stop: None, Mock(), 'Run All Tests'
    )

    with patch('reahl.swordfish.test_execution.messagebox') as messagebox:
        execution.report_failure(DomainException('bad'))

    application.open_debugger.assert_not_called()
    messagebox.showerror.assert_called_once()
