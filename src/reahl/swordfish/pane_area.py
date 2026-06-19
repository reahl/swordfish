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
        self.add(group, weight=1)
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
        # split -- and rebalance so the new group is actually visible (otherwise
        # it gets squeezed to zero width at the right edge). Returns its index.
        index = self.add_group()
        self.distribute_groups_evenly()
        return index

    def distribute_groups_evenly(self):
        # AI: Give every group an equal share of the current width, so opening a
        # pane visibly rearranges the layout instead of hiding off to the right.
        self.update_idletasks()
        total_width = self.winfo_width()
        group_count = len(self.groups)
        if total_width <= 1 or group_count < 2:
            return
        for sash_index in range(group_count - 1):
            self.sashpos(
                sash_index, total_width * (sash_index + 1) // group_count
            )

    def close_pane(self, pane):
        # AI: Remove a pane; if that empties a non-primary group, drop the group
        # and collapse the split so the remaining groups reclaim the space.
        group = pane.master
        if group in self.groups:
            group.forget(pane)
        pane.destroy()
        if group in self.groups and group is not self.groups[0] and not group.tabs():
            self.forget(group)
            self.groups.remove(group)
            group.destroy()
            self.distribute_groups_evenly()
