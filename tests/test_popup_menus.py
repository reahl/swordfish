import tkinter as tk
import types
from unittest.mock import patch

from reahl.swordfish.ui_support import close_popup_menu, popup_menu


def test_popup_menu_retains_grab_so_a_click_outside_dismisses_it():
    """AI: A right-click menu must keep the input grab that tk_popup installs.

    On X11 that grab is what makes a click outside the menu reach it and dismiss
    it. Releasing the grab synchronously (the previous behaviour) tore down the
    only mechanism that closed the menu on an outside click, so it stayed open
    until the user selected an item or pressed Escape.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label='Something', command=lambda: None)
        event = types.SimpleNamespace(x_root=0, y_root=0)
        with patch.object(menu, 'tk_popup') as posted, patch.object(
            menu, 'grab_release'
        ) as released:
            popup_menu(menu, event)
        posted.assert_called_once_with(0, 0)
        released.assert_not_called()
    finally:
        root.destroy()


def test_closing_a_popup_menu_releases_its_grab():
    """AI: Dismissing a popup explicitly must release the grab it holds.

    The click-away grab is desirable while the menu is up, but the explicit-close
    path (Escape) has to release it; otherwise the rest of the UI would stay
    frozen behind the dismissed menu's input grab.
    """
    root = tk.Tk()
    root.withdraw()
    try:
        menu = tk.Menu(root, tearoff=0)
        with patch.object(menu, 'unpost') as unposted, patch.object(
            menu, 'grab_release'
        ) as released:
            close_popup_menu(menu)
        unposted.assert_called_once()
        released.assert_called_once()
    finally:
        root.destroy()
