from reahl.stubble import stubclass
from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.browser import CoveringTestsDiscoveryWorkflow
from reahl.swordfish.main import GemstoneSessionRecord


@stubclass(GemstoneSessionRecord)
class InterruptRecordingSessionRecord(GemstoneSessionRecord):
    """AI: Records hard_break so a test can prove that stopping a search reaches
    through to interrupt the GemStone call in flight, rather than only raising the
    cooperative between-calls flag. stubclass keeps the recorded method honest against
    the real record's signature."""

    hard_break_count = 0

    def hard_break(self):
        self.hard_break_count = self.hard_break_count + 1


def keep_latest_plan(accumulated_plan, latest_plan):
    """AI: The workflow needs a plan combiner, but this unit never runs an actual
    search, so keeping the latest result is all the combiner has to do."""
    return latest_plan


class CoveringTestsStopFixture(Fixture):
    def new_session_record(self):
        return InterruptRecordingSessionRecord(None)

    def new_workflow(self):
        return CoveringTestsDiscoveryWorkflow(
            self.session_record,
            'doSomething',
            1000,
            keep_latest_plan,
        )


@with_fixtures(CoveringTestsStopFixture)
def test_stopping_a_search_interrupts_the_in_flight_gemstone_call(fixture):
    """AI: A covering-tests search can be parked inside a single long GemStone call
    (e.g. a referencesTo: scan) where the cooperative should_stop flag stays invisible
    until that call returns. Requesting cancellation must therefore hard_break the
    session so the blocked call is abandoned at once, while still raising the
    cooperative flag for the safe points between calls."""
    workflow = fixture.workflow

    workflow.request_cancel()

    assert fixture.session_record.hard_break_count == 1
    assert workflow.should_stop.is_set()
