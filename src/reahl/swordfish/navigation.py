class NavigationHistory:
    def __init__(self, maximum_entries=200):
        self.maximum_entries = maximum_entries
        self.entries = []
        self.current_index = -1

    def current_entry(self):
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    def record(self, entry):
        if entry is None:
            return
        if self.current_entry() == entry:
            return
        if self.current_index < len(self.entries) - 1:
            self.entries = self.entries[: self.current_index + 1]
        self.entries.append(entry)
        overflow = len(self.entries) - self.maximum_entries
        if overflow > 0:
            self.entries = self.entries[overflow:]
        self.current_index = len(self.entries) - 1

    def can_go_back(self):
        return self.current_index > 0

    def can_go_forward(self):
        return 0 <= self.current_index < len(self.entries) - 1

    def go_back(self):
        if not self.can_go_back():
            return None
        self.current_index -= 1
        return self.current_entry()

    def go_forward(self):
        if not self.can_go_forward():
            return None
        self.current_index += 1
        return self.current_entry()

    def jump_to(self, history_index):
        if history_index < 0:
            return None
        if history_index >= len(self.entries):
            return None
        self.current_index = history_index
        return self.current_entry()

    def entries_with_current_marker(self):
        entry_details = []
        for index, entry in enumerate(self.entries):
            entry_details.append(
                {
                    'history_index': index,
                    'entry': entry,
                    'is_current': index == self.current_index,
                },
            )
        return entry_details
