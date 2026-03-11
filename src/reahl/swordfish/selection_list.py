import tkinter as tk
from tkinter import ttk


class InteractiveSelectionList(ttk.Frame):
    def __init__(self, parent, get_all_entries, get_selected_entry, set_selected_to):
        super().__init__(parent)

        self.get_all_entries = get_all_entries
        self.get_selected_entry = get_selected_entry
        self.set_selected_to = set_selected_to
        self.synchronizing_selection = False

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, columnspan=2, sticky='ew')

        self.selection_listbox = tk.Listbox(
            self, selectmode=tk.SINGLE, exportselection=False
        )
        self.selection_listbox.grid(row=1, column=0, sticky='nsew')

        self.scrollbar = tk.Scrollbar(
            self, orient='vertical', command=self.selection_listbox.yview
        )
        self.scrollbar.grid(row=1, column=1, sticky='ns')
        self.selection_listbox.config(yscrollcommand=self.scrollbar.set)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.repopulate()
        self.selection_listbox.bind('<<ListboxSelect>>', self.handle_selection)

    def repopulate(self, origin=None):
        self.synchronizing_selection = True
        try:
            self.all_entries = self.get_all_entries()
            self.filter_var.set('')
            self.update_filter()

            selected_indices = self.selection_listbox.curselection()
            if selected_indices:
                index = selected_indices[0]
                if not self.selection_listbox.bbox(index):
                    self.selection_listbox.see(index)
        finally:
            self.synchronizing_selection = False

    def update_filter(self, *args):
        filter_text = self.filter_var.get().lower()
        self.selection_listbox.delete(0, tk.END)

        selected_entry = self.get_selected_entry()
        filtered_index = 0
        for entry in self.all_entries:
            if filter_text in entry.lower():
                self.selection_listbox.insert(tk.END, entry)
                if selected_entry and selected_entry == entry:
                    self.selection_listbox.selection_set(filtered_index)
                filtered_index += 1

    def handle_selection(self, event):
        if self.synchronizing_selection:
            return
        try:
            selected_listbox = event.widget
            selected_indices = selected_listbox.curselection()
            selected_index = selected_indices[-1]
            selected_entry = selected_listbox.get(selected_index)
            current_selected_entry = self.get_selected_entry()
            if selected_entry == current_selected_entry:
                return

            self.set_selected_to(selected_entry)
        except IndexError:
            pass
