"""Activities the user can abandon while they run against the shared GemStone session.

The GemStone session executes one call at a time, so at any moment there is at most
one activity using it. This module models that single running activity as something the
user can stop with one gesture, regardless of who launched it: a foreground activity the
IDE started on a worker thread, or an MCP tool running on the MCP server thread. Both
expose the same ``request_stop`` so a single Stop control can govern either."""

import threading

from reahl.ptongue import GemstoneApiError, GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException


# AI: Failures we expect a unit of GemStone work to raise. We capture these at the
# worker-thread boundary so every activity ends with a recorded outcome (the UI thread
# would otherwise wait forever for a thread that died with an unreported exception). A
# hard_break delivered mid-call also surfaces as a GemstoneError, which is why an
# interrupted activity and a genuine failure can arrive through the same except clause -
# the should_stop flag is what tells them apart.
EXPECTED_ACTIVITY_FAILURES = (
    GemstoneError,
    GemstoneApiError,
    DomainException,
    GemstoneDomainException,
)


class ForegroundActivity:
    """A unit of GemStone work the IDE launched on the user's behalf and may abandon.

    The work runs on a worker thread so the UI thread stays free to interrupt it. A stop
    is cooperative first - the work polls ``stop_requested`` between round-trips and can
    return whatever it has gathered so far - and then forceful, hard-breaking the session
    so a single long call still ends. The recorded outcome is delivered back on the UI
    thread, where the launching context decides what a finished, interrupted or failed
    activity means (a search renders its partial results; a run reports it was stopped)."""

    def __init__(
        self,
        message,
        work,
        on_finished=None,
        on_interrupted=None,
        on_failed=None,
        interrupt_session=None,
    ):
        self.message = message
        self.work = work
        self.on_finished = on_finished
        self.on_interrupted = on_interrupted
        self.on_failed = on_failed
        self.interrupt_session = interrupt_session
        self.should_stop = threading.Event()
        self.outcome_kind = None
        self.outcome_value = None

    def stop_requested(self):
        return self.should_stop.is_set()

    def request_stop(self):
        """AI: Cooperative flag first so work already looping can return clean partial
        results; then a forceful session interrupt so work parked inside one long call is
        abandoned too. The interrupt raises GemstoneError in the worker, which run_work
        reads as an interruption because the flag is set."""
        self.should_stop.set()
        if self.interrupt_session is not None:
            self.interrupt_session()

    def run_work(self):
        """AI: Runs on the worker thread. Always records an outcome for the expected
        failure modes so the UI thread is never left waiting on an unreported result."""
        try:
            result = self.work(self.stop_requested)
            self.record_outcome_from_result(result)
        except EXPECTED_ACTIVITY_FAILURES as activity_failure:
            self.record_outcome_from_failure(activity_failure)

    def record_outcome_from_result(self, result):
        if self.should_stop.is_set():
            self.outcome_kind = 'interrupted'
            self.outcome_value = result
        else:
            self.outcome_kind = 'finished'
            self.outcome_value = result

    def record_outcome_from_failure(self, activity_failure):
        if self.should_stop.is_set():
            self.outcome_kind = 'interrupted'
            self.outcome_value = None
        else:
            self.outcome_kind = 'failed'
            self.outcome_value = activity_failure

    def deliver_outcome(self):
        """AI: Runs on the UI thread once the worker has finished. Routes the recorded
        outcome to the launching context's handler."""
        if self.outcome_kind == 'finished' and self.on_finished is not None:
            self.on_finished(self.outcome_value)
        if self.outcome_kind == 'interrupted' and self.on_interrupted is not None:
            self.on_interrupted(self.outcome_value)
        if self.outcome_kind == 'failed' and self.on_failed is not None:
            self.on_failed(self.outcome_value)


class McpActivity:
    """The running activity when an MCP tool is doing GemStone work on the shared session.

    MCP tools run on the MCP server thread and expose no cooperative stop token, so a stop
    is purely a forceful hard-break of the session. The interrupted tool's own
    GemstoneError handling turns that into an error answer to its caller, so the IDE need
    do nothing further than break the session."""

    def __init__(self, message, interrupt_session):
        self.message = message
        self.interrupt_session = interrupt_session

    def request_stop(self):
        self.interrupt_session()
