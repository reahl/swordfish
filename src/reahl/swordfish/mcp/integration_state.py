import threading


class IntegratedSessionState:
    def __init__(self):
        self.lock = threading.RLock()
        self.ide_gui_active = False
        self.ide_session = None
        self.ide_transaction_active = True
        self.mcp_operation_depth = 0
        self.active_mcp_operation = ''
        self.pending_model_changes = []
        self.ide_connection_identifier = 'ide-session'

    def attach_ide_gui(self):
        with self.lock:
            self.ide_gui_active = True

    def detach_ide_gui(self):
        with self.lock:
            self.ide_gui_active = False
            self.ide_session = None
            self.ide_transaction_active = True
            self.pending_model_changes = []

    def is_ide_gui_active(self):
        with self.lock:
            return self.ide_gui_active

    def attach_ide_session(self, gemstone_session):
        with self.lock:
            self.ide_gui_active = True
            self.ide_session = gemstone_session
            self.ide_transaction_active = True

    def detach_ide_session(self):
        with self.lock:
            self.ide_session = None
            self.ide_transaction_active = True
            self.pending_model_changes = []

    def has_ide_session(self):
        with self.lock:
            return self.ide_session is not None

    def ide_session_for_mcp(self):
        with self.lock:
            return self.ide_session

    def ide_connection_id(self):
        return self.ide_connection_identifier

    def is_ide_connection_id(self, connection_id):
        return connection_id == self.ide_connection_identifier

    def ide_metadata_for_mcp(self):
        with self.lock:
            if self.ide_session is None:
                return None
            return {
                'connection_mode': 'ide_attached',
                'transaction_active': self.ide_transaction_active,
                'managed_by_ide': True,
            }

    def mark_ide_transaction_active(self):
        with self.lock:
            self.ide_transaction_active = True

    def mark_ide_transaction_inactive(self):
        with self.lock:
            self.ide_transaction_active = False

    def begin_mcp_operation(self, operation_name):
        with self.lock:
            self.mcp_operation_depth = self.mcp_operation_depth + 1
            self.active_mcp_operation = operation_name

    def end_mcp_operation(self):
        with self.lock:
            if self.mcp_operation_depth > 0:
                self.mcp_operation_depth = self.mcp_operation_depth - 1
            if self.mcp_operation_depth == 0:
                self.active_mcp_operation = ''

    def is_mcp_busy(self):
        with self.lock:
            return self.mcp_operation_depth > 0

    def current_mcp_operation_name(self):
        with self.lock:
            return self.active_mcp_operation

    def request_model_refresh(self, change_kind):
        with self.lock:
            self.pending_model_changes.append(change_kind)

    def consume_model_refresh_requests(self):
        with self.lock:
            change_kinds = list(self.pending_model_changes)
            self.pending_model_changes = []
            return change_kinds


integrated_session_state = IntegratedSessionState()


def current_integrated_session_state():
    return integrated_session_state
