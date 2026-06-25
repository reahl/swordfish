import tkinter as tk
import types
from unittest.mock import patch

from reahl.swordfish.text_editing import CodePanel


def test_debugger_context_menu_includes_breakpoint_commands():
    """AI: While debugging, the user should be able to set or clear breakpoints to control
    future execution paths. The debugger source panel must offer Set/Clear Breakpoint in its
    right-click menu, just as the regular method editor does."""
    root = tk.Tk()
    root.withdraw()
    try:
        fake_app = types.SimpleNamespace(
            tab_spacing=4,
            integrated_session_state=types.SimpleNamespace(is_mcp_busy=lambda: False),
            debugger_tab=None,
            experimental_features_enabled=False,
        )
        code_panel = CodePanel(root, application=fake_app)
        fake_debugger_tab = types.SimpleNamespace(
            code_panel=code_panel,
            save_current_frame_method=lambda: None,
            cancel_current_frame_method=lambda: None,
        )
        fake_app.debugger_tab = fake_debugger_tab

        event = types.SimpleNamespace(x=0, y=0, x_root=0, y_root=0)
        with patch.object(tk.Menu, 'tk_popup'):
            code_panel.open_text_menu(event)

        menu = code_panel.current_context_menu
        end_index = menu.index(tk.END)
        menu_labels = [
            menu.entrycget(i, 'label')
            for i in range(end_index + 1)
            if menu.type(i) not in ('separator', 'tearoff')
        ]

        assert 'Set Breakpoint Here' in menu_labels
        assert 'Clear Breakpoint Here' in menu_labels
    finally:
        root.destroy()
