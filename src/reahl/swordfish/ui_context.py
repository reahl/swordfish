import threading


UI_CONTEXT_SEQUENCE = 0
UI_CONTEXT_SEQUENCE_LOCK = threading.RLock()


def next_ui_context_identifier(tab_id):
    global UI_CONTEXT_SEQUENCE
    with UI_CONTEXT_SEQUENCE_LOCK:
        UI_CONTEXT_SEQUENCE = UI_CONTEXT_SEQUENCE + 1
        return '%s-%s' % (tab_id, UI_CONTEXT_SEQUENCE)


class UiContext:
    def __init__(self, tab_id):
        self.tab_id = next_ui_context_identifier(tab_id)
        self.version = 0
        self.alive = True
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return (self.tab_id, self.version)

    def invalidate(self):
        with self.lock:
            if self.alive:
                self.alive = False
                self.version = self.version + 1

    def matches(self, snapshot):
        with self.lock:
            return self.alive and snapshot == (self.tab_id, self.version)
