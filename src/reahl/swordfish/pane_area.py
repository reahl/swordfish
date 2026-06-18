# AI: The splittable centre of the IDE. A PaneArea arranges tab groups side by
# side; a pane resides in a group as a tab, and splitting adds another group so
# two panes (for example the editor and an embedded Find) can be seen at once.
# Placement lives here, not in the panes -- a Pane never grids itself, so the
# same pane can sit in a BrowserWindow today or a split group tomorrow.

from tkinter import ttk


class PaneArea(ttk.PanedWindow):
    def __init__(self, parent):
        super().__init__(parent, orient='horizontal')
        self.groups = []
        self.add_group()

    def add_group(self):
        # AI: A group is a notebook of panes shown as tabs. Returns the new
        # group's index so callers can place panes into it.
        group = ttk.Notebook(self)
        self.add(group)
        self.groups.append(group)
        return len(self.groups) - 1

    def group(self, index=0):
        return self.groups[index]

    def place_pane(self, pane, title, group=0):
        # AI: Show the pane as a tab in the given group. The pane must already
        # be a child of that group (Tk parents tab contents to their notebook).
        self.groups[group].add(pane, text=title)

    def split(self):
        # AI: Add another tab group beside the current one(s) -- a horizontal
        # split -- and return its index so panes can be placed into it.
        return self.add_group()
