import threading

from reahl.swordfish.mcp.session_serialization import OperationGate


def test_a_different_operation_is_excluded_until_the_holder_leaves():
    """AI: The gate serializes whole operations: while one operation holds the session, a
    different operation cannot enter. This is the core mutual exclusion that keeps an IDE
    operation's GCI calls from interleaving with an MCP operation's GCI calls."""
    gate = OperationGate()
    holder_has_it = threading.Event()
    holder_may_release = threading.Event()

    def hold_as(operation_token):
        gate.enter(operation_token)
        holder_has_it.set()
        holder_may_release.wait()
        gate.leave(operation_token)

    holder = threading.Thread(target=hold_as, args=('mcp-op-1',))
    holder.start()
    holder_has_it.wait()

    assert gate.try_enter('ide-op-1') is False

    holder_may_release.set()
    holder.join()

    assert gate.try_enter('ide-op-1') is True
    gate.leave('ide-op-1')


def test_the_same_operation_re_enters_from_another_thread_without_blocking():
    """AI: One operation can span two threads - an MCP operation holds the session on its worker
    thread, then drives IDE work that runs on the Tk thread. That second thread must be admitted
    under the same operation token rather than deadlocking against the operation's own hold, which
    a thread-based lock could never express."""
    gate = OperationGate()
    holder_has_it = threading.Event()
    holder_may_release = threading.Event()

    def hold_as(operation_token):
        gate.enter(operation_token)
        holder_has_it.set()
        holder_may_release.wait()
        gate.leave(operation_token)

    holder = threading.Thread(target=hold_as, args=('mcp-op-1',))
    holder.start()
    holder_has_it.wait()

    assert gate.try_enter('mcp-op-1') is True
    gate.leave('mcp-op-1')

    holder_may_release.set()
    holder.join()


def test_blocking_enter_proceeds_only_after_the_holder_leaves():
    """AI: The chosen contention policy is to wait, not reject. A second operation that blocks on
    enter must not proceed until the holder leaves, so the two never run concurrently."""
    gate = OperationGate()
    order = []
    order_lock = threading.Lock()
    holder_has_it = threading.Event()
    waiter_started = threading.Event()

    def hold_then_release():
        gate.enter('mcp-op-1')
        holder_has_it.set()
        waiter_started.wait()
        with order_lock:
            order.append('holder-leaving')
        gate.leave('mcp-op-1')

    def wait_to_enter():
        waiter_started.set()
        gate.enter('ide-op-1')
        with order_lock:
            order.append('waiter-entered')
        gate.leave('ide-op-1')

    holder = threading.Thread(target=hold_then_release)
    holder.start()
    holder_has_it.wait()
    waiter = threading.Thread(target=wait_to_enter)
    waiter.start()

    holder.join()
    waiter.join()

    assert order == ['holder-leaving', 'waiter-entered']
