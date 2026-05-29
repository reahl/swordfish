import re
import tkinter as tk

from reahl.ptongue import GemstoneError

GRAPH_NODE_WIDTH = 200
GRAPH_NODE_HEIGHT = 60
GRAPH_NODE_PADDING_X = 40
GRAPH_NODE_PADDING_Y = 40
GRAPH_NODES_PER_ROW = 4
GRAPH_ORIGIN_X = 60
GRAPH_ORIGIN_Y = 60
UML_NODE_WIDTH = 240
UML_NODE_MIN_HEIGHT = 56
UML_NODE_PADDING_X = 40
UML_NODE_PADDING_Y = 40
UML_NODES_PER_ROW = 4
UML_ORIGIN_X = 60
UML_ORIGIN_Y = 60
UML_METHOD_LINE_HEIGHT = 18
UML_HEADER_HEIGHT = 26


def close_popup_menu(menu):
    try:
        menu.unpost()
    except tk.TclError:
        pass


def add_close_command_to_popup_menu(menu):
    if menu.index('end') is not None:
        menu.add_separator()
    menu.add_command(
        label='Close Menu',
        command=lambda current_menu=menu: close_popup_menu(current_menu),
    )


def popup_menu(menu, event):
    menu.bind(
        '<Escape>',
        lambda popup_event, current_menu=menu: close_popup_menu(current_menu),
    )
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def is_compile_error(exception):
    error_number = None
    try:
        error_number = exception.number
    except (AttributeError, GemstoneError, TypeError):
        pass
    if error_number == 1001:
        return True

    error_text = str(exception).lower()
    return 'compileerror' in error_text or 'compile error' in error_text


def add_source_code_commands(menu, source_code_editor, selected_text, enabled):
    # AI: Shared Run/Inspect/Debug/Show in Object Diagram group for every live code
    # AI: editor, so the action set stays identical wherever code is selected.
    command_state = tk.NORMAL if enabled and selected_text.strip() else tk.DISABLED

    def add_command(label, action):
        menu.add_command(
            label=label,
            command=lambda code=selected_text: action(code),
            state=command_state,
        )

    add_command('Run', source_code_editor.run_selected_source)
    add_command('Inspect', source_code_editor.inspect_selected_source)
    add_command('Debug', source_code_editor.debug_selected_source)
    add_command(
        'Show in Object Diagram',
        source_code_editor.show_selected_source_in_object_diagram,
    )


def word_under_text_cursor(text_widget):
    # AI: The identifier or symbol fragment at the current insertion point
    # of a tk.Text widget. Shared by every 'do something with the thing
    # under the cursor' source-window command so the boundary rules stay
    # consistent across CodePanel, RunTab, and any future code surface.
    line, column = text_widget.index(tk.INSERT).split('.')
    line_text = text_widget.get(f'{line}.0', f'{line}.end')
    cursor_column = int(column)
    token_matches = [
        token_match
        for token_match in re.finditer(
            r'[-+*/\\~<>=@%,|&?!]+|[A-Za-z_]\w*:?',
            line_text,
        )
        if token_match.start() <= cursor_column <= token_match.end()
    ]
    if not token_matches:
        return ''
    return token_matches[0].group(0)


def class_name_at_widget_cursor(text_widget, selected_text):
    # AI: Prefer the selection if there is one; otherwise fall back to the
    # word under the cursor. Strip and extract the first identifier-like
    # substring so callers get a clean class-name candidate (or None).
    candidate = selected_text if selected_text else word_under_text_cursor(text_widget)
    candidate = (candidate or '').strip()
    if not candidate:
        return None
    class_name_match = re.search(r'[A-Za-z_]\w*', candidate)
    if class_name_match is None:
        return None
    return class_name_match.group(0)
