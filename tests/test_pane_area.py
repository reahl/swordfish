# AI: Unit tests for the splittable centre of the IDE (PaneArea). A PaneArea
# is a horizontal arrangement of tab groups; panes reside in a group as tabs,
# and splitting adds another group beside the existing ones so two panes (for
# example the editor and an embedded Find) can sit side by side.

import tkinter as tk
from tkinter import ttk

from reahl.tofu import Fixture, set_up, tear_down
from reahl.tofu.pytestsupport import with_fixtures

from reahl.swordfish.pane_area import PaneArea


class PaneAreaFixture(Fixture):
    @set_up
    def create_root(self):
        self.root = tk.Tk()
        self.root.withdraw()

    @tear_down
    def destroy_root(self):
        self.root.destroy()


@with_fixtures(PaneAreaFixture)
def test_pane_area_places_a_pane_as_a_tab_in_a_group(fixture):
    """AI: A pane resides in a group as a tab -- the area shows it under the
    given title in the group it is placed into."""
    area = PaneArea(fixture.root)
    pane = ttk.Frame(area.group(0))

    area.place_pane(pane, 'Editor')

    group = area.group(0)
    assert [group.tab(tab, 'text') for tab in group.tabs()] == ['Editor']


@with_fixtures(PaneAreaFixture)
def test_splitting_adds_a_side_by_side_group(fixture):
    """AI: Splitting the area adds another tab group beside the first, so two
    panes (e.g. the editor and an embedded Find) can sit side by side, each
    holding its own panes."""
    area = PaneArea(fixture.root)
    editor = ttk.Frame(area.group(0))
    area.place_pane(editor, 'Editor')

    second_group = area.split()
    find = ttk.Frame(area.group(second_group))
    area.place_pane(find, 'Find', group=second_group)

    assert len(area.panes()) == 2
    first, second = area.group(0), area.group(second_group)
    assert [first.tab(t, 'text') for t in first.tabs()] == ['Editor']
    assert [second.tab(t, 'text') for t in second.tabs()] == ['Find']


@with_fixtures(PaneAreaFixture)
def test_closing_a_pane_collapses_its_empty_group(fixture):
    """AI: Closing the last pane in a non-primary group removes that group and
    collapses the split, so the remaining group reclaims the space rather than
    leaving an empty leftover."""
    area = PaneArea(fixture.root)
    area.place_pane(ttk.Frame(area.group(0)), 'Browser')
    second_group = area.split()
    find = ttk.Frame(area.group(second_group))
    area.place_pane(find, 'Find', group=second_group)
    assert len(area.panes()) == 2

    area.close_pane(find)

    assert len(area.groups) == 1
    assert len(area.panes()) == 1
