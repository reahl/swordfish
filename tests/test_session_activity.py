import threading

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.session_activity import ForegroundActivity, McpActivity


class FakeGemstoneError(GemstoneError):
    """AI: Minimal GemstoneError for testing - bypasses the real constructor which
    requires an active session and a C error structure."""

    def __init__(self):
        pass


def run_to_completion(activity):
    """AI: Drive an activity through its worker thread exactly as the app's runner does -
    start, join, then deliver the outcome - so a test sees the same lifecycle the IDE does
    without needing a Tk event loop."""
    worker = threading.Thread(target=activity.run_work)
    worker.start()
    worker.join()
    activity.deliver_outcome()


def test_completed_work_reports_its_result_as_finished():
    """AI: Work that runs to the end without a stop request is a finished activity, and its
    return value is handed to the finished handler - this is the ordinary success path the
    launching context renders as a full result."""
    delivered = {}
    activity = ForegroundActivity(
        'Searching...',
        work=lambda should_stop: ['Order', 'OrderLine'],
        on_finished=lambda result: delivered.update(finished=result),
    )

    run_to_completion(activity)

    assert delivered['finished'] == ['Order', 'OrderLine']


def test_work_that_returns_after_a_stop_request_is_interrupted_with_its_partial():
    """AI: When the cooperative flag is set, work that notices it and returns early hands its
    accumulated results to the interrupted handler, not the finished one - this is the Find
    contract: a stopped incremental search keeps whatever it had gathered."""
    delivered = {}

    def gather_until_stopped(should_stop):
        gathered = ['Order']
        if should_stop():
            return gathered
        gathered.append('OrderLine')
        return gathered

    activity = ForegroundActivity(
        'Searching...',
        work=gather_until_stopped,
        on_finished=lambda result: delivered.update(finished=result),
        on_interrupted=lambda partial: delivered.update(interrupted=partial),
    )
    activity.should_stop.set()

    run_to_completion(activity)

    assert 'finished' not in delivered
    assert delivered['interrupted'] == ['Order']


def test_a_break_raised_after_a_stop_request_is_interrupted_not_failed():
    """AI: A forceful session break surfaces in the worker as a GemstoneError. Because the
    stop flag is set, that is an interruption (no partial available, so None), never a
    failure - the user asked to stop, so they must not see an error dialog."""
    delivered = {}

    def break_when_stopped(should_stop):
        raise FakeGemstoneError()

    activity = ForegroundActivity(
        'Searching...',
        work=break_when_stopped,
        on_interrupted=lambda partial: delivered.update(interrupted=partial),
        on_failed=lambda error: delivered.update(failed=error),
    )
    activity.should_stop.set()

    run_to_completion(activity)

    assert 'failed' not in delivered
    assert delivered['interrupted'] is None


def test_an_unrequested_failure_is_reported_to_the_failure_handler():
    """AI: A genuine error - one that arises with no stop pending - is a failure the launching
    context must surface, distinct from a user-requested interruption."""
    delivered = {}

    def fail(should_stop):
        raise DomainException('Invalid search pattern')

    activity = ForegroundActivity(
        'Searching...',
        work=fail,
        on_interrupted=lambda partial: delivered.update(interrupted=partial),
        on_failed=lambda error: delivered.update(failed=str(error)),
    )

    run_to_completion(activity)

    assert 'interrupted' not in delivered
    assert delivered['failed'] == 'Invalid search pattern'


def test_requesting_stop_sets_the_flag_and_breaks_the_session():
    """AI: One Stop gesture must do both halves of the agreed semantics: raise the cooperative
    flag (so looping work can return partial) and forcefully break the session (so work stuck
    in a single long call is abandoned)."""
    breaks = []
    activity = ForegroundActivity(
        'Searching...',
        work=lambda should_stop: None,
        interrupt_session=lambda: breaks.append('broken'),
    )

    activity.request_stop()

    assert activity.stop_requested() is True
    assert breaks == ['broken']


def test_mcp_activity_stop_only_breaks_the_session():
    """AI: An MCP tool exposes no cooperative token, so stopping it is purely a forceful
    session break; the interrupted tool reports its own error to its caller."""
    breaks = []
    activity = McpActivity(
        'gs_run_tests',
        interrupt_session=lambda: breaks.append('broken'),
    )

    activity.request_stop()

    assert breaks == ['broken']
