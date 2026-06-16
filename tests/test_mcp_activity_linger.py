'''AI: Tests for ActivityLinger - the minimum visible time the MCP activity indicator owes every
operation. A fast MCP tool call begins and ends before the Tk thread renders its busy state, so an
indicator driven by raw busy-state edges shows nothing for exactly the workloads - bursts of small,
quick calls - a user most wants reassurance about. The linger is the pure decision object; the Tk
wiring stays thin around it.'''

from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.main import ActivityLinger


class SteppableClock:
    '''AI: A clock the test advances by hand, so linger expiry is asserted exactly rather than
    raced against real time.'''

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + seconds


class LingerScenarios(Fixture):
    @scenario
    def fast_operation_remains_visible(self):
        '''AI: An operation that finished instantly still earns the minimum visible time - the
        point of the linger: raw busy edges render nothing for sub-second tool calls.'''
        self.advance_before_check = 0.3
        self.expected_lingering = True

    @scenario
    def linger_expires_after_minimum(self):
        '''AI: Once the minimum has passed the indicator owes nothing more - it must go dark
        rather than suggest activity that is no longer happening.'''
        self.advance_before_check = 0.6
        self.expected_lingering = False


@with_fixtures(LingerScenarios)
def test_linger_holds_for_minimum_visible_time(linger_scenario):
    clock = SteppableClock()
    linger = ActivityLinger(minimum_visible_seconds=0.5, clock=clock)

    linger.note_activity()
    clock.advance(linger_scenario.advance_before_check)

    assert linger.is_lingering() == linger_scenario.expected_lingering


def test_burst_of_activity_reads_as_one_steady_period():
    '''AI: Each busy signal restarts the hold, so a burst of quick operations shows as one
    continuous period of activity ending a minimum time after the last call - not a flicker
    per call and not a gap in the middle.'''
    clock = SteppableClock()
    linger = ActivityLinger(minimum_visible_seconds=0.5, clock=clock)

    linger.note_activity()
    clock.advance(0.4)
    linger.note_activity()
    clock.advance(0.4)
    assert linger.is_lingering()

    clock.advance(0.2)
    assert not linger.is_lingering()


def test_fresh_linger_owes_nothing():
    '''AI: Before any operation has run the indicator must be dark - the linger starts inert,
    it does not invent activity at startup.'''
    clock = SteppableClock()
    linger = ActivityLinger(minimum_visible_seconds=0.5, clock=clock)

    assert not linger.is_lingering()
