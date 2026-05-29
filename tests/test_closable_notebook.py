# AI: Unit tests for the closable_notebook helper. The actual UI click
# detection depends on Tk laying out the notebook and is exercised manually;
# these tests cover the dispatch contract (gate + callback) and the style
# wiring that the helper installs on a notebook.

import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

from reahl.tofu import Fixture, set_up, tear_down
from reahl.tofu.pytestsupport import with_fixtures

from reahl.swordfish.closable_notebook import install_close_buttons


class ClosableNotebookFixture(Fixture):
    @set_up
    def create_notebook(self):
        self.root = tk.Tk()
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack()
        self.first_page = ttk.Frame(self.notebook)
        self.second_page = ttk.Frame(self.notebook)
        self.notebook.add(self.first_page, text='First')
        self.notebook.add(self.second_page, text='Second')
        self.close_callback = Mock()

    @tear_down
    def destroy_root(self):
        self.root.destroy()


@with_fixtures(ClosableNotebookFixture)
def test_install_close_buttons_applies_closable_style(fixture):
    """AI: The helper switches the notebook to the Closable.TNotebook style
    so every tab — present or future — picks up the 'x' element."""
    install_close_buttons(fixture.notebook, fixture.close_callback)

    assert fixture.notebook.cget('style') == 'Closable.TNotebook'


@with_fixtures(ClosableNotebookFixture)
def test_close_callback_receives_clicked_tab_index(fixture):
    """AI: Invoking the dispatch path with a tab index calls the close
    callback with that exact (notebook, tab_index) pair."""
    install_close_buttons(fixture.notebook, fixture.close_callback)

    fixture.notebook.close_tab_at_index(1)

    fixture.close_callback.assert_called_once_with(fixture.notebook, 1)


@with_fixtures(ClosableNotebookFixture)
def test_is_closable_gate_suppresses_callback_for_protected_tabs(fixture):
    """AI: When is_closable returns False for a tab the callback must not
    fire, regardless of the click — protecting tabs like the main Browser
    tab from being inadvertently closed."""
    is_closable = lambda notebook, tab_index: tab_index != 0
    install_close_buttons(
        fixture.notebook, fixture.close_callback, is_closable=is_closable
    )

    closed = fixture.notebook.close_tab_at_index(0)

    assert closed is False
    fixture.close_callback.assert_not_called()
