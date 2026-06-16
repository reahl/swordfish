import tkinter as tk

from reahl.tofu import Fixture, set_up, tear_down, with_fixtures

from reahl.swordfish.main import EventQueue


class Recorder:
    """AI: Records how many times the drain actually invoked the handler."""

    def __init__(self):
        self.calls = 0

    def note(self):
        self.calls = self.calls + 1


class GatedAdmission:
    """AI: Stand-in for SessionOperationAdmission whose admit/deny we flip by hand, so the test
    pins the drain's decision rather than racing a real MCP operation. A token means admitted; None
    means an operation holds the session."""

    def __init__(self):
        self.admits = True

    def try_admit(self):
        if self.admits:
            return ('ide-token',)
        return None

    def release(self, operation_token):
        pass


class DrainFixture(Fixture):
    @set_up
    def set_up_event_queue(self):
        self.root = tk.Tk()
        self.event_queue = EventQueue(self.root)
        self.admission = GatedAdmission()
        self.event_queue.session_admission = self.admission
        self.recorder = Recorder()
        self.event_queue.subscribe('ProbeEvent', self.recorder.note)

    @tear_down
    def tear_down_event_queue(self):
        self.root.destroy()


@with_fixtures(DrainFixture)
def test_drain_runs_handlers_when_the_session_is_free(fixture):
    """AI: With nothing holding the session the drain admits immediately and runs its handlers in
    line, so ordinary IDE work is not slowed when no MCP operation competes for the session."""
    fixture.event_queue.publish('ProbeEvent')

    assert fixture.recorder.calls == 1


@with_fixtures(DrainFixture)
def test_drain_defers_handlers_while_an_operation_holds_the_session(fixture):
    """AI: The IDE event drain must not run its GCI-bearing handlers while an MCP operation holds
    the session - their GCI would collide with the operation's (error 2203, the crash). While the
    session is busy the drain defers and the event is not lost; once the session is free the same
    handlers run."""
    fixture.admission.admits = False
    fixture.event_queue.publish('ProbeEvent')
    assert fixture.recorder.calls == 0

    fixture.admission.admits = True
    fixture.event_queue.process_events()
    assert fixture.recorder.calls == 1
