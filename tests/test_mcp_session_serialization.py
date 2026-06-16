import threading
import time

from reahl.swordfish.mcp.session_serialization import exclusive_session_access


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
