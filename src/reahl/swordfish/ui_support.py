import re
import tkinter as tk
import tkinter.messagebox as messagebox

from reahl.ptongue import GemstoneError

from reahl.swordfish.session_activity import ForegroundActivity
from reahl.swordfish.theme import active_theme

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


class Tooltip:
    """A hover-help popup for a widget.

    It shows a short description in a small borderless window once the pointer has rested on the
    widget, and hides it when the pointer leaves or the widget is pressed. This lets compact icon
    buttons stay compact without becoming cryptic: the glyph is the affordance, the tooltip is the
    name."""

    def __init__(self, widget, text, delay_ms=500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self.scheduled_id = None
        widget.bind('<Enter>', self.schedule_show, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')

    def schedule_show(self, event=None):
        self.cancel_scheduled()
        self.scheduled_id = self.widget.after(self.delay_ms, self.show)

    def cancel_scheduled(self):
        if self.scheduled_id is not None:
            try:
                self.widget.after_cancel(self.scheduled_id)
            except tk.TclError:
                pass
            self.scheduled_id = None

    def show(self):
        self.scheduled_id = None
        if self.tip_window is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry('+%d+%d' % (x, y))
        label = tk.Label(
            self.tip_window,
            text=self.text,
            justify='left',
            background=active_theme.current().color_for('tooltip_background'),
            foreground=active_theme.current().color_for('tooltip_foreground'),
            relief='solid',
            borderwidth=1,
            padx=4,
            pady=2,
        )
        label.pack()

    def hide(self, event=None):
        self.cancel_scheduled()
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


def close_popup_menu(menu):
    # AI: Unpost AND release the input grab. tk_popup installs a grab that lets a
    # click outside the menu dismiss it; the explicit-close path (Escape) must
    # release that grab so the rest of the UI is not left frozen behind it.
    try:
        menu.unpost()
    except tk.TclError:
        pass
    try:
        menu.grab_release()
    except tk.TclError:
        pass


def popup_menu(menu, event):
    menu.bind(
        '<Escape>',
        lambda popup_event, current_menu=menu: close_popup_menu(current_menu),
    )
    # AI: Do NOT grab_release() here. tk_popup installs the input grab that makes a
    # click outside the menu dismiss it; releasing it synchronously (tk_popup returns
    # immediately on X11) left the menu stuck open. Tk releases the grab itself when
    # the menu is dismissed normally, and close_popup_menu releases it on Escape/Close.
    menu.tk_popup(event.x_root, event.y_root)


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


class SelectionEvaluation:
    """AI: A selection of source evaluated against the shared session as an
    interruptible foreground activity.

    The evaluation runs on a worker thread so the menu-bar Stop can hard-break a long
    doit; the outcome is delivered back on the UI thread. Every 'evaluate the
    selection' action -- Inspect, Print, Show in Diagram, and the Run window's own
    run -- evaluates through this, so a selection that takes a while is interruptible
    no matter which editor or command started it. The caller supplies what to
    evaluate (``evaluate_source``, run on the worker thread) and what to do with the
    outcome (``on_result`` on the UI thread); a failure falls back to a dialog named
    by ``failure_title`` unless the caller handles it itself."""

    def __init__(self, application, message, failure_title):
        self.application = application
        self.message = message
        self.failure_title = failure_title

    def evaluate(
        self,
        source,
        evaluate_source,
        on_result,
        on_failed=None,
        on_interrupted=None,
    ):
        activity = ForegroundActivity(
            self.message,
            work=lambda should_stop: evaluate_source(source),
            on_finished=on_result,
            on_failed=on_failed if on_failed is not None else self.report_failure,
            on_interrupted=on_interrupted,
        )
        self.application.run_foreground_activity(activity)

    def report_failure(self, error):
        messagebox.showerror(self.failure_title, str(error))


def add_run_commands(menu, source_code_editor, selected_text, enabled):
    # AI: The 'evaluate the selection' group - Run / Print / Inspect / Debug - shared
    # by every live code editor so the action set stays identical wherever code is
    # selected. Print evaluates and splices the result's printString back into the
    # editor (classic Smalltalk 'print it'). Disabled when there is nothing to
    # evaluate. Order follows the classic do-it / print-it / inspect-it / debug-it.
    command_state = tk.NORMAL if enabled and selected_text.strip() else tk.DISABLED

    def add_command(label, action):
        menu.add_command(
            label=label,
            command=lambda code=selected_text: action(code),
            state=command_state,
        )

    add_command('Run', source_code_editor.run_selected_source)
    add_command('Print', source_code_editor.print_selected_source)
    add_command('Inspect', source_code_editor.inspect_selected_source)
    add_command('Debug', source_code_editor.debug_selected_source)


def add_navigation_commands(menu, source_code_editor):
    # AI: The 'find the code behind a name' group - Implementors / Senders /
    # References / Browse Class - which act on the selector or class name under the
    # cursor, so they need no selection and are always enabled.
    menu.add_command(
        label='Implementors',
        command=source_code_editor.open_implementors_from_source,
    )
    menu.add_command(
        label='Senders',
        command=source_code_editor.open_senders_from_source,
    )
    menu.add_command(
        label='References',
        command=source_code_editor.find_references_from_source,
    )
    menu.add_command(
        label='Browse Class',
        command=source_code_editor.browse_class_from_source,
    )


def add_diagram_commands(menu, source_code_editor, selected_text, enabled):
    # AI: The diagram group. The two 'Show in ...' entries evaluate the selection
    # (so share its enablement); 'Add to Class Diagram' acts on the class name under
    # the cursor, paired directly under 'Show in Class Diagram'.
    eval_state = tk.NORMAL if enabled and selected_text.strip() else tk.DISABLED
    menu.add_command(
        label='Show in Object Diagram',
        command=(
            lambda code=selected_text: (
                source_code_editor.show_selected_source_in_object_diagram(code)
            )
        ),
        state=eval_state,
    )
    menu.add_command(
        label='Show in Class Diagram',
        command=(
            lambda code=selected_text: (
                source_code_editor.show_selected_source_in_class_diagram(code)
            )
        ),
        state=eval_state,
    )
    menu.add_command(
        label='Add to Class Diagram',
        command=source_code_editor.add_class_to_class_diagram_from_source,
    )


def class_name_for_class_diagram(gem_object):
    # AI: The class to diagram for an evaluated result: the object's class, or the
    # object itself when it already is a class/metaclass (a Behavior). Mirrors how
    # 'Show in Object Diagram' graphs the live result, but at the class level.
    target = gem_object
    try:
        is_class = gem_object.isBehavior().to_py
    except GemstoneError:
        is_class = False
    if not is_class:
        target = gem_object.gemstone_class()
    return target.name().to_py


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


def selector_token(token_text):
    # AI: Reduce a fragment of source to the Smalltalk selector it names, or None.
    # Handles unary/keyword identifiers (foo, foo:bar:), bare keyword runs, and
    # binary selectors (+, ->, etc.). Shared by every source window so cursor->
    # selector resolution stays identical across CodePanel and RunTab.
    candidate = (token_text or '').strip()
    if not candidate:
        return None
    is_identifier_selector = re.fullmatch(
        r'[A-Za-z_]\w*(?::[A-Za-z_]\w*)*:?',
        candidate,
    )
    if is_identifier_selector:
        return candidate
    keyword_tokens = re.findall(
        r'[A-Za-z_]\w*:',
        candidate,
    )
    if keyword_tokens:
        return ''.join(keyword_tokens)
    is_binary_selector = re.fullmatch(r'[-+*/\\~<>=@%,|&?!]+', candidate)
    if is_binary_selector:
        return candidate
    return None


def selector_at_widget_cursor(text_widget, selected_text):
    # AI: Prefer the selection if it names a selector; otherwise fall back to the
    # selector token under the cursor. Mirrors class_name_at_widget_cursor so the
    # Run tab and CodePanel resolve selectors for Implementors/Senders the same way.
    selector_from_selection = selector_token(selected_text)
    if selector_from_selection is not None:
        return selector_from_selection
    return selector_token(word_under_text_cursor(text_widget))
