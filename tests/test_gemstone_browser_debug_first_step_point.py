from reahl.stubble import stubclass
from reahl.tofu import Fixture, expected, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


# AI: "Debug" should always drop you into the debugger on the FIRST STATEMENT of the code you
# AI: asked to debug - as if an implicit breakpoint sat there - rather than only stopping when
# AI: the code happens to raise. The mechanism (verified against a live gem) is a transient
# AI: break at step point 2 (step point 1 is the method entry / header), which traps to the
# AI: client exactly like the existing debugger expects. A step-point break only traps during
# AI: an EXECUTE, so the code under debug is always run through run_code, never invoked via
# AI: gem_proxy.perform. For selected text we compile a doit-METHOD (whose entry maps cleanly
# AI: to step points) rather than a block (whose prologue would put the marker ahead of
# AI: execution).


class WrappedInteger:
    """AI: parseltongue's from_py wraps a Python int as a gem object whose .to_py reads
    it back. The break-installing code converts the step point through from_py, so the
    recorded argument arrives wrapped - this satisfies just that contract."""

    def __init__(self, value):
        self.to_py = value


class RecordingSession:
    def from_py(self, value):
        return WrappedInteger(value)


class FakeStepPointOffsets:
    def __init__(self, count):
        self.count = count

    def size(self):
        return WrappedInteger(self.count)


class RecordingCompiledMethod:
    """AI: Records the step-point break protocol (setBreakAtStepPoint: /
    disableBreakAtStepPoint:) so a test can prove a break was both installed and removed,
    and reports a step-point count via _sourceOffsets so the first-statement (step point 2)
    choice can be exercised."""

    def __init__(self, step_point_count=5):
        self.step_point_count = step_point_count
        self.step_points_broken = []
        self.step_points_cleared = []

    def perform(self, selector, *args):
        if selector == '_sourceOffsets':
            return FakeStepPointOffsets(self.step_point_count)
        if selector == 'setBreakAtStepPoint:':
            self.step_points_broken.append(args[0].to_py)
            return None
        if selector == 'disableBreakAtStepPoint:':
            self.step_points_cleared.append(args[0].to_py)
            return None
        raise AssertionError('AI: Unexpected selector: %s' % selector)


class SimulatedBreakpointTrap(Exception):
    """AI: Stands in for the ptongue GemstoneError raised when the implicit step-point
    break traps. The session layer must let it propagate so the debugger can open on it."""


@stubclass(GemstoneBrowserSession)
class RecordingDebugSession(GemstoneBrowserSession):
    requested_method = None
    run_outcome = None
    canned_run_result = None
    compiled_method = None

    def get_compiled_method(self, class_name, method_selector, show_instance_side):
        self.requested_method = (class_name, method_selector, show_instance_side)
        return self.compiled_method

    def run_code(self, source):
        self.run_code_sources.append(source)
        if self.run_outcome is not None:
            raise self.run_outcome
        return self.canned_run_result


class DebugFirstStepPointFixture(Fixture):
    def new_compiled_method(self):
        return RecordingCompiledMethod()

    def new_browser_session(self):
        session = RecordingDebugSession(RecordingSession())
        session.compiled_method = self.compiled_method
        session.run_code_sources = []
        return session


@with_fixtures(DebugFirstStepPointFixture)
def test_debugging_a_test_breaks_at_its_first_statement(fixture):
    """AI: Debugging a test method should stop on its first real statement, not its header:
    the session installs a break at step point 2 (step point 1 is the method entry) of the
    instance-side test method and runs the test via runCase, so the trap lands on the first
    statement of the test body (after setUp)."""
    session = fixture.browser_session
    session.run_outcome = SimulatedBreakpointTrap()

    with expected(SimulatedBreakpointTrap):
        session.debug_test_method('AccountTest', 'testDeposit')

    assert session.requested_method == ('AccountTest', 'testDeposit', True)
    executed_source = session.run_code_sources[-1]
    assert "AccountTest selector: ('testDeposit' asSymbol)" in executed_source
    assert 'runCase' in executed_source
    assert fixture.compiled_method.step_points_broken == [2]


@with_fixtures(DebugFirstStepPointFixture)
def test_implicit_test_break_is_removed_even_when_it_traps(fixture):
    """AI: The implicit break is transient - it must be removed once the run is under way,
    even though hitting it raises the trap that opens the debugger - so debugging a test
    never leaves breakpoints lying around in the image."""
    session = fixture.browser_session
    session.run_outcome = SimulatedBreakpointTrap()

    with expected(SimulatedBreakpointTrap):
        session.debug_test_method('AccountTest', 'testDeposit')

    assert fixture.compiled_method.step_points_cleared == [2]


@with_fixtures(DebugFirstStepPointFixture)
def test_debugging_selected_source_compiles_it_as_a_doit_method_run_via_execute(fixture):
    """AI: Selected text is compiled into a doit-METHOD (not a block, whose prologue would
    put the marker two step points ahead of execution), broken at its first statement (step
    point 2, since step point 1 is the synthetic doIt header), and run through
    _executeInContext: in a single execute - so the break traps on the selection's first
    statement with the marker where execution actually is."""
    session = fixture.browser_session
    session.run_outcome = SimulatedBreakpointTrap()

    with expected(SimulatedBreakpointTrap):
        session.debug_source('account deposit: 10')

    executed_source = session.run_code_sources[-1]
    assert '_compileMethod:' in executed_source
    assert "'doIt\naccount deposit: 10'" in executed_source
    assert 'setBreakAtStepPoint: (swordfishDebugMethod _sourceOffsets size min: 2)' in executed_source
    assert '_executeInContext: nil' in executed_source


@with_fixtures(DebugFirstStepPointFixture)
def test_debug_doit_method_is_compiled_uninstalled_so_nothing_persists(fixture):
    """AI: The doit-method is compiled with UndefinedObject _compileMethod:symbolList:, which
    returns an uninstalled GsNMethod - never added to any class's method dictionary - so
    debugging arbitrary source leaves nothing behind in the image to clean up."""
    session = fixture.browser_session
    session.run_outcome = SimulatedBreakpointTrap()

    with expected(SimulatedBreakpointTrap):
        session.debug_source('account deposit: 10')

    executed_source = session.run_code_sources[-1]
    assert 'UndefinedObject' in executed_source
    assert 'compileMethod:dictionaries:' not in executed_source
