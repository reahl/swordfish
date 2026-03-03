from reahl.swordfish.gemstone.debugging import GemstoneStackFrame


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
        numeric_index = index.to_py if hasattr(index, 'to_py') else index
        return FakeGemstoneNumber(self.values[numeric_index - 1])


class FakeGemstoneString:
    def __init__(self, value):
        self.to_py = value


class FakeGemstoneMethod:
    def __init__(self, source, source_offsets, previous_step_point, step_point_offset):
        self.source = source
        self.source_offsets = source_offsets
        self.previous_step_point = previous_step_point
        self.step_point_offset = step_point_offset

    def perform(self, selector, *args):
        if selector == '_sourceOffsets':
            return FakeGemstoneArray(self.source_offsets)
        if selector == '_previousStepPointForIp:':
            return FakeGemstoneNumber(self.previous_step_point)
        if selector == '_stepPointOffset':
            return FakeGemstoneNumber(self.step_point_offset)
        raise AssertionError('AI: Unexpected selector: %s' % selector)

    def fullSource(self):
        return FakeGemstoneString(self.source)


def test_step_point_offset_prefers_current_step_point_index_when_available():
    """AI: A block frame should highlight the active halt send instead of a later step point."""
    source = 'ifTrue: [ accounts halt addAll: (accounts select: [ :each | each == self ]) ]'
    frame = GemstoneStackFrame.__new__(GemstoneStackFrame)
    frame.gemstone_method = FakeGemstoneMethod(
        source=source,
        source_offsets=[10, 11, 90, 20, 31, 76],
        previous_step_point=6,
        step_point_offset=4,
    )
    frame.ip_offset = FakeGemstoneNumber(96)

    assert frame.step_point_offset == source.find('halt') + 1
