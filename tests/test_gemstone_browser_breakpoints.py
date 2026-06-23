from reahl.swordfish.gemstone.breakpoint_registry import clear_all_breakpoints
from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class FakeGemstoneNumber:
    def __init__(self, value):
        self.to_py = value


class FakeGemstoneArray:
    def __init__(self, values):
        self.values = list(values)

    def size(self):
        return FakeGemstoneNumber(len(self.values))

    def at(self, index):
        numeric_index = index.to_py if hasattr(index, "to_py") else index
        return FakeGemstoneNumber(self.values[numeric_index - 1])


class FakeCompiledMethod:
    def __init__(self, source_offsets):
        self.source_offsets = list(source_offsets)
        self.breakpoints_set = []
        self.breakpoints_cleared = []

    def perform(self, selector, *args):
        if selector == "_sourceOffsets":
            return FakeGemstoneArray(self.source_offsets)
        if selector == "setBreakAtStepPoint:":
            self.breakpoints_set.append(args[0].to_py)
            return FakeGemstoneNumber(1)
        if selector == "disableBreakAtStepPoint:":
            self.breakpoints_cleared.append(args[0].to_py)
            return FakeGemstoneNumber(1)
        raise AssertionError("AI: Unexpected selector: %s" % selector)


class FakeGemstoneClass:
    def __init__(self, compiled_method):
        self.compiled_method = compiled_method

    def compiledMethodAt(self, selector):
        return self.compiled_method

    def gemstone_class(self):
        return self


class FakeGemstoneSession:
    def __init__(self, classes_by_name):
        self.classes_by_name = classes_by_name

    def resolve_symbol(self, class_name):
        return self.classes_by_name[class_name]

    def from_py(self, value):
        return FakeGemstoneNumber(value)


def test_set_breakpoint_uses_closest_source_offset_step_point():
    clear_all_breakpoints()
    compiled_method = FakeCompiledMethod([5, 14, 30])
    gemstone_session = FakeGemstoneSession(
        {"ExampleClass": FakeGemstoneClass(compiled_method)}
    )
    browser_session = GemstoneBrowserSession(gemstone_session)

    breakpoint_entry = browser_session.set_breakpoint(
        "ExampleClass",
        "exampleMethod",
        True,
        13,
    )

    assert breakpoint_entry["step_point"] == 2
    assert breakpoint_entry["source_offset"] == 14
    assert compiled_method.breakpoints_set == [2]


def test_setting_same_breakpoint_twice_reuses_existing_entry():
    clear_all_breakpoints()
    compiled_method = FakeCompiledMethod([5, 14, 30])
    gemstone_session = FakeGemstoneSession(
        {"ExampleClass": FakeGemstoneClass(compiled_method)}
    )
    browser_session = GemstoneBrowserSession(gemstone_session)

    first_breakpoint = browser_session.set_breakpoint(
        "ExampleClass",
        "exampleMethod",
        True,
        14,
    )
    second_breakpoint = browser_session.set_breakpoint(
        "ExampleClass",
        "exampleMethod",
        True,
        14,
    )

    assert first_breakpoint["breakpoint_id"] == second_breakpoint["breakpoint_id"]
    assert compiled_method.breakpoints_set == [2]


def test_recompiling_a_method_reapplies_its_breakpoint_to_the_new_method():
    """AI: A recompile installs a brand-new CompiledMethod, so a breakpoint set on the old
    one is orphaned - the image stops honouring it while the IDE still shows it as set.
    Re-applying maps the breakpoint's stored source offset onto the NEW method's step points
    and re-installs the break there, so editing a method never silently disarms its
    breakpoint."""
    clear_all_breakpoints()
    original_method = FakeCompiledMethod([5, 14, 30])
    gemstone_class = FakeGemstoneClass(original_method)
    gemstone_session = FakeGemstoneSession({"ExampleClass": gemstone_class})
    browser_session = GemstoneBrowserSession(gemstone_session)
    browser_session.set_breakpoint("ExampleClass", "exampleMethod", True, 14)
    assert original_method.breakpoints_set == [2]

    # AI: The recompile: a new CompiledMethod whose step-point offsets have shifted.
    new_method = FakeCompiledMethod([5, 20, 36])
    gemstone_class.compiled_method = new_method
    browser_session.reapply_breakpoints_for_method("ExampleClass", True, "exampleMethod")

    # AI: The break is re-installed on the NEW method at the step point nearest the stored
    # AI: offset, and the registry entry tracks the new step point so the marker stays true.
    assert new_method.breakpoints_set == [2]
    reapplied_breakpoint = browser_session.list_breakpoints()[0]
    assert reapplied_breakpoint["step_point"] == 2
    assert reapplied_breakpoint["source_offset"] == 20


def test_clear_breakpoint_at_cursor_offset_removes_matching_breakpoint():
    clear_all_breakpoints()
    compiled_method = FakeCompiledMethod([5, 14, 30])
    gemstone_session = FakeGemstoneSession(
        {"ExampleClass": FakeGemstoneClass(compiled_method)}
    )
    browser_session = GemstoneBrowserSession(gemstone_session)
    breakpoint_entry = browser_session.set_breakpoint(
        "ExampleClass",
        "exampleMethod",
        True,
        30,
    )

    cleared_breakpoint = browser_session.clear_breakpoint_at(
        "ExampleClass",
        "exampleMethod",
        True,
        29,
    )

    assert cleared_breakpoint["breakpoint_id"] == breakpoint_entry["breakpoint_id"]
    assert compiled_method.breakpoints_cleared == [3]
    assert browser_session.list_breakpoints() == []
