import tkinter as tk

from reahl.swordfish.ui_support import Tooltip


def test_tooltip_shows_its_text_in_a_popup_and_then_hides_it():
    """AI: A tooltip surfaces an icon button's meaning on hover: it puts the description in a small
    popup when shown and removes the popup when hidden, so a compact glyph button stays compact
    without being cryptic."""
    root = tk.Tk()
    root.withdraw()
    try:
        button = tk.Button(root, text='X')
        button.pack()
        root.update_idletasks()
        tooltip = Tooltip(button, 'Run', delay_ms=0)

        assert tooltip.tip_window is None

        tooltip.show()
        assert tooltip.tip_window is not None
        popup_label = tooltip.tip_window.winfo_children()[0]
        assert popup_label.cget('text') == 'Run'

        tooltip.hide()
        assert tooltip.tip_window is None
    finally:
        root.destroy()
