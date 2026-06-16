import contextlib
import threading

# AI: GCI is single-threaded per GemStone session: starting a second call before
# the first returns raises error 2203 and the IDE surfaces it as a fatal GemStone
# error. We give each connection a gate so that calls sharing one session pass
# through one at a time, while calls on different sessions stay independent.

gates_by_connection_id = {}
registry_lock = threading.Lock()


def gate_for_connection(connection_id):
    with registry_lock:
        existing_gate = gates_by_connection_id.get(connection_id)
        if existing_gate is None:
            existing_gate = threading.RLock()
            gates_by_connection_id[connection_id] = existing_gate
        return existing_gate


@contextlib.contextmanager
def exclusive_session_access(connection_id):
    gate = gate_for_connection(connection_id)
    gate.acquire()
    try:
        yield
    finally:
        gate.release()


def clear_gates():
    with registry_lock:
        gates_by_connection_id.clear()
