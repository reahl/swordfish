import threading
import time

from reahl.swordfish.mcp.integration_state import IntegratedSessionState
from reahl.swordfish.mcp.session_serialization import exclusive_session_access
from reahl.swordfish.mcp.tools import register_tools


def peak_overlap_across(connection_ids):
    """AI: Run one thread per connection_id, each holding exclusive_session_access
    briefly, and report the largest number of threads that were ever inside the
    critical section at the same instant."""
    state_lock = threading.Lock()
    occupancy = {'current': 0, 'peak': 0}
    start_barrier = threading.Barrier(len(connection_ids))

    def hold_session(connection_id):
        start_barrier.wait()
        with exclusive_session_access(connection_id):
            with state_lock:
                occupancy['current'] = occupancy['current'] + 1
                occupancy['peak'] = max(occupancy['peak'], occupancy['current'])
            time.sleep(0.05)
            with state_lock:
                occupancy['current'] = occupancy['current'] - 1

    threads = [
        threading.Thread(target=hold_session, args=(connection_id,))
        for connection_id in connection_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return occupancy['peak']


def test_same_connection_calls_do_not_overlap():
    """AI: Two MCP calls on one GemStone session must run one at a time. GCI is
    single-threaded per session and raises error 2203 ('a call in progress') if a
    second call starts before the first returns, which the IDE surfaces as a fatal
    GemStone error window."""
    assert peak_overlap_across(['ide-session', 'ide-session']) == 1


def test_different_connections_may_overlap():
    """AI: Independent sessions have independent GCI state, so serializing across
    them would needlessly block unrelated work. Only calls sharing one session are
    gated."""
    assert peak_overlap_across(['session-a', 'session-b']) == 2


class RecordingProbe:
    """AI: A stand-in MCP tool whose body is slow enough for two callers to overlap, and which
    records the largest number of callers that were ever inside it at the same instant."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def run(self, connection_id=None):
        with self.lock:
            self.current = self.current + 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.05)
        with self.lock:
            self.current = self.current - 1
        return {'ok': True}


class CapturingMcpServer:
    """AI: Minimal stand-in for the FastMCP server. register_tools only ever touches `.tool`:
    it captures the raw decorator factory and then replaces it with the coordinated one, so a
    bare `.tool` that registers functions unchanged is the whole contract we must honour."""

    def tool(self, *decorator_arguments, **decorator_keywords):
        return lambda registered_function: registered_function


def probe_wrapped_through_coordinated_tool():
    """AI: Wrap a probe through the *real* coordinated_tool that register_tools installs onto
    mcp_server.tool, so the test exercises the production gate wiring rather than a copy of it."""
    mcp_server = CapturingMcpServer()
    register_tools(mcp_server, integrated_session_state=IntegratedSessionState())
    probe = RecordingProbe()
    coordinated_call = mcp_server.tool('probe')(probe.run)
    return probe, coordinated_call


def peak_overlap_through(coordinated_call, connection_ids):
    """AI: Fire one thread per connection_id at the coordinated wrapper at once and report the
    peak number of callers the probe ever saw inside itself simultaneously."""
    start_barrier = threading.Barrier(len(connection_ids))

    def fire(connection_id):
        start_barrier.wait()
        coordinated_call(connection_id=connection_id)

    threads = [
        threading.Thread(target=fire, args=(connection_id,))
        for connection_id in connection_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_coordinated_tool_serializes_concurrent_calls_on_one_connection():
    """AI: The gate must be wired into coordinated_tool itself, not merely available as a
    primitive. Two MCP calls sharing a connection, driven through the real wrapper, must never
    be inside the tool body at the same time - otherwise overlapping GCI raises error 2203 and
    the IDE falls over, exactly as observed live while the unit test of the primitive passed."""
    probe, coordinated_call = probe_wrapped_through_coordinated_tool()
    peak_overlap_through(coordinated_call, ['ide-session', 'ide-session'])
    assert probe.peak == 1


def test_coordinated_tool_lets_distinct_connections_run_in_parallel():
    """AI: The wiring keys the gate on connection_id, so calls on different sessions still run
    concurrently through the wrapper - the serialization is targeted, not a global stall."""
    probe, coordinated_call = probe_wrapped_through_coordinated_tool()
    peak_overlap_through(coordinated_call, ['session-a', 'session-b'])
    assert probe.peak == 2
