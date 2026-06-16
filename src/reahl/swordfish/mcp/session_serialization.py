import contextlib
import threading

# AI: GCI is single-threaded per GemStone session: starting a second call before the first
# returns raises error 2203 and the IDE surfaces it as a fatal GemStone error. We serialize at the
# granularity of whole *operations* (an MCP tool call, an IDE action) rather than individual GCI
# calls, because an operation is several GCI calls that must not interleave with another operation.
# An operation can span two threads - an MCP operation holds the session on its worker thread and
# then drives IDE work on the Tk thread - so the gate is keyed by an operation token, not a thread,
# and the same token re-enters instead of deadlocking against its own hold.


class OperationGate:
    """AI: Mutual exclusion keyed by an operation token rather than by a thread. A whole
    operation holds the session under one token. A different token must wait (enter) or is refused
    (try_enter); the same token re-enters without blocking, so an operation that spans two threads
    never deadlocks on its own hold. Contention policy is to wait, matching the choice that the
    loser blocks until free."""

    def __init__(self):
        self.condition = threading.Condition()
        self.holder_token = None
        self.hold_count = 0

    def enter(self, operation_token):
        with self.condition:
            while self.hold_count > 0 and self.holder_token != operation_token:
                self.condition.wait()
            self.holder_token = operation_token
            self.hold_count = self.hold_count + 1

    def try_enter(self, operation_token):
        with self.condition:
            held_by_other = self.hold_count > 0 and self.holder_token != operation_token
            admitted = not held_by_other
            if admitted:
                self.holder_token = operation_token
                self.hold_count = self.hold_count + 1
            return admitted

    def leave(self, operation_token):
        with self.condition:
            self.hold_count = self.hold_count - 1
            if self.hold_count == 0:
                self.holder_token = None
                self.condition.notify_all()


gates_by_connection_id = {}
registry_lock = threading.Lock()
operation_context = threading.local()


def operation_gate_for(connection_id):
    with registry_lock:
        gate = gates_by_connection_id.get(connection_id)
        if gate is None:
            gate = OperationGate()
            gates_by_connection_id[connection_id] = gate
        return gate


def current_operation_token():
    # AI: The operation token in force on the current thread, or None. The MCP worker thread sets
    # it while a tool runs, so code it calls - notably driving IDE navigation - can carry the token
    # to the Tk thread and re-enter the gate under the same operation rather than deadlocking.
    return getattr(operation_context, 'token', None)


@contextlib.contextmanager
def session_operation(connection_id, operation_token):
    # AI: Hold the session for the whole duration of one operation (blocking acquire). Safe to
    # block here on the MCP worker thread; the Tk thread must use try_enter_session_operation.
    gate = operation_gate_for(connection_id)
    previous_token = getattr(operation_context, 'token', None)
    gate.enter(operation_token)
    operation_context.token = operation_token
    try:
        yield
    finally:
        operation_context.token = previous_token
        gate.leave(operation_token)


def try_enter_session_operation(connection_id, operation_token):
    # AI: Non-blocking acquire for the Tk thread, which also services MCP-driven navigation and so
    # must never block. A False answer means another operation holds the session; defer the work.
    return operation_gate_for(connection_id).try_enter(operation_token)


def leave_session_operation(connection_id, operation_token):
    operation_gate_for(connection_id).leave(operation_token)


def clear_gates():
    with registry_lock:
        gates_by_connection_id.clear()
