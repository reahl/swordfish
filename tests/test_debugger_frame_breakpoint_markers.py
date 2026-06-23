from reahl.swordfish.execution import DebuggerWindow


class RecordingCodePanel:
    """AI: Stands in for the debugger's CodePanel, recording the method context it adopts
    and the source it is asked to show, without any Tk construction."""

    def __init__(self):
        self.tab_key = None
        self.refreshed = []

    def refresh(self, source, mark=None):
        self.refreshed.append((source, mark))


class FakeStackFrame:
    def __init__(self, class_name, method_name, method_source, step_point_offset):
        self.class_name = class_name
        self.method_name = method_name
        self.method_source = method_source
        self.step_point_offset = step_point_offset


class FramePresentingDebugger:
    """AI: A DebuggerWindow stripped of Tk, reusing the real frame-presentation methods so a
    test can prove what method identity the source pane adopts for a given frame."""

    present_frame_source = DebuggerWindow.present_frame_source
    frame_method_context = DebuggerWindow.frame_method_context

    def __init__(self):
        self.code_panel = RecordingCodePanel()


def test_debugger_pane_adopts_the_frames_method_identity_so_breakpoint_markers_show():
    """AI: The debugger source pane is the shared CodePanel, which paints breakpoint markers
    only for the method named by its method context. So presenting a frame must make the pane
    adopt that frame's (class, instance-side, selector) identity - otherwise a method you set
    a breakpoint in shows none of its markers while you debug it."""
    debugger = FramePresentingDebugger()
    frame = FakeStackFrame('Account', 'deposit:', 'deposit: anAmount\n\t^anAmount', 12)

    debugger.present_frame_source(frame)

    assert debugger.code_panel.tab_key == ('Account', True, 'deposit:')
    assert debugger.code_panel.refreshed == [('deposit: anAmount\n\t^anAmount', 12)]


def test_class_side_frame_is_presented_on_the_class_side():
    """AI: A class-side activation shows up as 'Account class' in the stack; the pane must
    adopt the class side so a breakpoint set on the class-side method is the one whose markers
    appear, not an instance-side namesake."""
    debugger = FramePresentingDebugger()
    frame = FakeStackFrame('Account class', 'new', 'new\n\t^super new init', 5)

    debugger.present_frame_source(frame)

    assert debugger.code_panel.tab_key == ('Account', False, 'new')


def test_a_non_method_frame_clears_the_method_context():
    """AI: Executed code (a doIt) and other non-method activations have no method identity, so
    the pane must drop any context left from the previous frame - otherwise stale markers from
    an unrelated method would bleed onto code that has none."""
    debugger = FramePresentingDebugger()
    debugger.code_panel.tab_key = ('Account', True, 'deposit:')
    frame = FakeStackFrame('nil', None, '| x | x := 1', 3)

    debugger.present_frame_source(frame)

    assert debugger.code_panel.tab_key is None
