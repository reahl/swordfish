import tkinter as tk
import types
from unittest.mock import patch

from reahl.swordfish.main import EventQueue
from reahl.swordfish.text_editing import CodePanel


def make_fake_app(root=None, **overrides):
    fake_app = types.SimpleNamespace(
        tab_spacing=4,
        integrated_session_state=types.SimpleNamespace(is_mcp_busy=lambda: False),
        debugger_tab=None,
        experimental_features_enabled=False,
        gemstone_session_record=None,
        event_queue=None,
    )
    for name, value in overrides.items():
        setattr(fake_app, name, value)
    return fake_app


def simulate_user_edit(code_panel, text):
    # AI: Reproduce a real edit, NOT a synthetic edit_modified(True). A real keystroke fires
    # <<Modified>>, which BOTH CodePanel.notify_text_changed (records dirtiness) and the line-
    # number gutter's on_text_modified (resets the Tk 'modified' flag so it keeps getting events)
    # handle. The gutter's reset is exactly what makes the raw Tk flag useless as a dirtiness
    # signal, so a faithful test must include it - otherwise it cannot catch that regression.
    code_panel.text_editor.insert(tk.INSERT, text)
    code_panel.notify_text_changed()
    code_panel.line_number_column.on_text_modified()


def breakpoint_command_states(code_panel):
    # AI: Pop the right-click menu (suppressing the real popup) and read back the
    # tk state of the Set/Clear Breakpoint entries so a test can assert greying.
    event = types.SimpleNamespace(x=0, y=0, x_root=0, y_root=0)
    with patch.object(tk.Menu, 'tk_popup'):
        code_panel.open_text_menu(event)
    menu = code_panel.current_context_menu
    end_index = menu.index(tk.END)
    states = {}
    index = 0
    while index <= end_index:
        if menu.type(index) not in ('separator', 'tearoff'):
            label = menu.entrycget(index, 'label')
            if label in ('Set Breakpoint Here', 'Clear Breakpoint Here'):
                states[label] = str(menu.entrycget(index, 'state'))
        index += 1
    return states


def attach_debugger_pane(fake_app, code_panel):
    fake_app.debugger_tab = types.SimpleNamespace(
        code_panel=code_panel,
        save_current_frame_method=lambda: None,
        cancel_current_frame_method=lambda: None,
    )


def test_debugger_breakpoint_commands_disabled_while_method_is_dirty():
    """AI: A breakpoint's source offset is captured from the editor's live text but resolved
    against the COMPILED method. While the debugger source pane carries unsaved edits the two
    coordinate systems have diverged, so a breakpoint set now lands at the wrong step point.
    Set/Clear Breakpoint must therefore be greyed out until the edits are saved or cancelled."""
    root = tk.Tk()
    root.withdraw()
    try:
        fake_app = make_fake_app()
        code_panel = CodePanel(root, application=fake_app)
        attach_debugger_pane(fake_app, code_panel)
        simulate_user_edit(code_panel, 'edited but unsaved')

        states = breakpoint_command_states(code_panel)

        assert states['Set Breakpoint Here'] == 'disabled'
        assert states['Clear Breakpoint Here'] == 'disabled'
    finally:
        root.destroy()


def test_debugger_breakpoint_commands_enabled_when_method_is_clean():
    """AI: With no unsaved edits the pane's text matches the compiled method, so offsets line
    up and breakpoints are meaningful. The commands must be available in that state."""
    root = tk.Tk()
    root.withdraw()
    try:
        fake_app = make_fake_app()
        code_panel = CodePanel(root, application=fake_app)
        attach_debugger_pane(fake_app, code_panel)
        code_panel.text_editor.edit_modified(False)

        states = breakpoint_command_states(code_panel)

        assert states['Set Breakpoint Here'] == 'normal'
        assert states['Clear Breakpoint Here'] == 'normal'
    finally:
        root.destroy()


def test_editor_tab_breakpoint_commands_disabled_while_method_is_dirty():
    """AI: The same offset divergence applies to the regular method editor, not only the
    debugger pane. A dirty editor tab must grey out Set/Clear Breakpoint for the same reason."""
    root = tk.Tk()
    root.withdraw()
    try:
        editor_tab_parent = tk.Frame(root)
        editor_tab_parent.save = lambda: None
        editor_tab_parent.method_editor = object()
        fake_app = make_fake_app()
        code_panel = CodePanel(editor_tab_parent, application=fake_app)
        simulate_user_edit(code_panel, 'edited but unsaved')

        states = breakpoint_command_states(code_panel)

        assert states['Set Breakpoint Here'] == 'disabled'
        assert states['Clear Breakpoint Here'] == 'disabled'
    finally:
        root.destroy()


def test_editor_tab_breakpoint_commands_enabled_when_method_is_clean():
    """AI: A clean method editor tab keeps the breakpoint commands available."""
    root = tk.Tk()
    root.withdraw()
    try:
        editor_tab_parent = tk.Frame(root)
        editor_tab_parent.save = lambda: None
        editor_tab_parent.method_editor = object()
        fake_app = make_fake_app()
        code_panel = CodePanel(editor_tab_parent, application=fake_app)
        code_panel.text_editor.edit_modified(False)

        states = breakpoint_command_states(code_panel)

        assert states['Set Breakpoint Here'] == 'normal'
        assert states['Clear Breakpoint Here'] == 'normal'
    finally:
        root.destroy()


def breakpoint_for(class_name, method_selector):
    return {
        'class_name': class_name,
        'show_instance_side': True,
        'method_selector': method_selector,
        'source_offset': 5,
        'step_point': 1,
        'breakpoint_id': 1,
    }


def test_breakpoints_changed_remarks_a_clean_pane_showing_that_method():
    """AI: A breakpoint set in one view must appear in every other open view of the same method.
    On BreakpointsChanged a clean pane re-reads the session's breakpoints and re-paints its
    gutter, so the editor and debugger never disagree about where breakpoints are."""
    root = tk.Tk()
    root.withdraw()
    try:
        tab_key = ('Account', True, 'deposit:')
        session_record = types.SimpleNamespace(
            list_breakpoints=lambda: [breakpoint_for('Account', 'deposit:')],
        )
        fake_app = make_fake_app(gemstone_session_record=session_record)
        code_panel = CodePanel(root, application=fake_app, tab_key=tab_key)
        code_panel.refresh('deposit: anAmount\n\t^anAmount')
        code_panel.text_editor.tag_remove('breakpoint_marker', '1.0', tk.END)

        code_panel.refresh_breakpoint_markers()

        assert code_panel.text_editor.tag_ranges('breakpoint_marker')
    finally:
        root.destroy()


def test_breakpoints_changed_skips_a_dirty_pane():
    """AI: A pane with unsaved edits must NOT be re-painted from stored offsets: the offsets no
    longer match the edited text, so re-applying would drop markers in the wrong place. Tk keeps
    tracking the existing marker tags as the user types, so the skip is safe."""
    root = tk.Tk()
    root.withdraw()
    try:
        tab_key = ('Account', True, 'deposit:')
        session_record = types.SimpleNamespace(
            list_breakpoints=lambda: [breakpoint_for('Account', 'deposit:')],
        )
        fake_app = make_fake_app(gemstone_session_record=session_record)
        code_panel = CodePanel(root, application=fake_app, tab_key=tab_key)
        code_panel.refresh('deposit: anAmount\n\t^anAmount')
        code_panel.text_editor.tag_remove('breakpoint_marker', '1.0', tk.END)
        simulate_user_edit(code_panel, ' edited')

        code_panel.refresh_breakpoint_markers()

        assert not code_panel.text_editor.tag_ranges('breakpoint_marker')
    finally:
        root.destroy()


def test_setting_a_breakpoint_remarks_another_open_pane_for_the_same_method():
    """AI: End-to-end of the sync bug: setting a breakpoint in one pane re-marks a second open
    pane that shows the same method, via the BreakpointsChanged event each pane subscribes to."""
    root = tk.Tk()
    root.withdraw()
    try:
        tab_key = ('Account', True, 'deposit:')
        recorded_breakpoints = []

        def set_breakpoint(class_name, show_instance_side, method_selector, source_offset):
            entry = {
                'class_name': class_name,
                'show_instance_side': show_instance_side,
                'method_selector': method_selector,
                'source_offset': source_offset,
                'step_point': 1,
                'breakpoint_id': len(recorded_breakpoints) + 1,
            }
            recorded_breakpoints.append(entry)
            return entry

        session_record = types.SimpleNamespace(
            set_breakpoint=set_breakpoint,
            list_breakpoints=lambda: list(recorded_breakpoints),
        )
        event_queue = EventQueue(root)
        fake_app = make_fake_app(
            gemstone_session_record=session_record,
            event_queue=event_queue,
        )

        setting_pane = CodePanel(root, application=fake_app, tab_key=tab_key)
        setting_pane.refresh('deposit: anAmount\n\t^anAmount')
        viewing_pane = CodePanel(root, application=fake_app, tab_key=tab_key)
        viewing_pane.refresh('deposit: anAmount\n\t^anAmount')
        viewing_pane.text_editor.tag_remove('breakpoint_marker', '1.0', tk.END)

        setting_pane.set_breakpoint_at_cursor()

        assert viewing_pane.text_editor.tag_ranges('breakpoint_marker')
    finally:
        root.destroy()
