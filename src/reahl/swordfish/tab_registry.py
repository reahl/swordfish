class DeduplicatedTabRegistry:
    def __init__(self, notebook):
        self.notebook = notebook
        self.tabs_by_key = {}
        self.key_by_tab_id = {}
        self.label_by_key = {}

    def register_tab(self, tab_key, tab_widget, tab_label=''):
        tab_id = str(tab_widget)
        self.tabs_by_key[tab_key] = tab_widget
        self.key_by_tab_id[tab_id] = tab_key
        self.label_by_key[tab_key] = tab_label

    def remove_key(self, tab_key):
        if tab_key not in self.tabs_by_key:
            return
        tab_widget = self.tabs_by_key.pop(tab_key)
        tab_id = str(tab_widget)
        if tab_id in self.key_by_tab_id:
            del self.key_by_tab_id[tab_id]
        if tab_key in self.label_by_key:
            del self.label_by_key[tab_key]

    def select_key(self, tab_key):
        if tab_key not in self.tabs_by_key:
            return False
        self.notebook.select(self.tabs_by_key[tab_key])
        return True

    def selected_key(self):
        selected_tab_id = self.notebook.select()
        if selected_tab_id in self.key_by_tab_id:
            return self.key_by_tab_id[selected_tab_id]
        return None

    def label_for_key(self, tab_key):
        if tab_key in self.label_by_key:
            return self.label_by_key[tab_key]
        return ''
