from reahl.swordfish.gemstone.debugging import GemstoneDebugSession, GemstoneStackFrame


class FakeGemstoneNumber:
    def __init__(self, value):
        self.to_py = value

    def min(self, other):
        return FakeGemstoneNumber(min(self.to_py, other.to_py))


class FakeGemstoneArray:
    def __init__(self, values):
        self.values = values

    def size(self):
        return FakeGemstoneNumber(len(self.values))

    def at(self, index):
        numeric_index = index.to_py if hasattr(index, "to_py") else index
        return FakeGemstoneNumber(self.values[numeric_index - 1])


class FakeGemstoneString:
    def __init__(self, value):
        self.to_py = value


class FakeGemstoneSession:
    def from_py(self, value):
        return value


class FakeGemstoneMethod:
    def __init__(self, source, source_offsets, step_point_for_ip):
        self.source = source
        self.source_offsets = source_offsets
        self.step_point_for_ip = step_point_for_ip

    def perform(self, selector, *args):
        if selector == "_sourceOffsets":
            return FakeGemstoneArray(self.source_offsets)
        if selector == "_stepPointForIp:level:useNext:":
            return FakeGemstoneNumber(self.step_point_for_ip)
        raise AssertionError("AI: Unexpected selector: %s" % selector)

    def fullSource(self):
        return FakeGemstoneString(self.source)


def test_step_point_offset_uses_ip_and_level_to_find_source_position():
    """AI: The source marker position is found by delegating to GemStone's own
    _stepPointForIp:level:useNext: which handles the next-vs-previous distinction
    between the top frame and deeper frames."""
    source = (
        "ifTrue: [ accounts halt addAll: (accounts select: [ :each | each == self ]) ]"
    )
    frame = GemstoneStackFrame.__new__(GemstoneStackFrame)
    frame.gemstone_session = FakeGemstoneSession()
    frame.level = 2
    frame.gemstone_method = FakeGemstoneMethod(
        source=source,
        source_offsets=[10, 11, 90, 20, 31, 76],
        step_point_for_ip=4,
    )
    frame.ip_offset = FakeGemstoneNumber(96)

    assert frame.step_point_offset == source.find("halt") + 1


class FakeRestartFrameSession:
    def __init__(self):
        self.from_py_calls = []

    def from_py(self, value):
        wrapped_level = ("wrapped-level", value)
        self.from_py_calls.append(value)
        return wrapped_level


class FakeRestartFrameContext:
    def __init__(self, session):
        self.session = session
        self.perform_calls = []

    def perform(self, selector, wrapped_level):
        self.perform_calls.append((selector, wrapped_level))
        return "trimmed"


class FakeRestartFrameException:
    def __init__(self, context):
        self.context = context


def test_restart_frame_result_trims_stack_to_requested_level():
    """AI: Restart frame should trim the stack at the selected level using keyword perform with converted level."""
    session = FakeRestartFrameSession()
    context = FakeRestartFrameContext(session)
    debug_session = GemstoneDebugSession(FakeRestartFrameException(context))

    result = debug_session.restart_frame_result(3)

    assert result == "trimmed"
    assert session.from_py_calls == [3]
    assert context.perform_calls == [
        ("_trimStackToLevel:", ("wrapped-level", 3)),
    ]


def test_restart_frame_keeps_debug_session_active_when_trim_succeeds():
    """AI: Restart frame should keep debugger interaction active after trimming to a selected frame."""
    session = FakeRestartFrameSession()
    context = FakeRestartFrameContext(session)
    debug_session = GemstoneDebugSession(FakeRestartFrameException(context))

    outcome = debug_session.restart_frame(2)

    assert not outcome.has_completed
