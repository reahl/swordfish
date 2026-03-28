import json
import re
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.ui_support import (
    add_close_command_to_popup_menu,
    close_popup_menu,
)


class EditableText:
    def __init__(self, text_widget, clipboard_owner):
        self.text_widget = text_widget
        self.clipboard_owner = clipboard_owner

    def selected_range(self):
        start_index = None
        end_index = None
        try:
            start_index = self.text_widget.index(tk.SEL_FIRST)
            end_index = self.text_widget.index(tk.SEL_LAST)
        except tk.TclError:
            pass
        return start_index, end_index

    def delete_selection(self):
        start_index, end_index = self.selected_range()
        if start_index is None:
            return False
        self.text_widget.mark_set(tk.INSERT, start_index)
        self.text_widget.delete(start_index, end_index)
        return True

    def select_all(self):
        self.text_widget.tag_add(tk.SEL, '1.0', 'end-1c')
        self.text_widget.mark_set(tk.INSERT, '1.0')
        self.text_widget.see(tk.INSERT)

    def copy_selection(self):
        start_index, end_index = self.selected_range()
        if start_index is None:
            return
        selected_text = self.text_widget.get(start_index, end_index)
        self.clipboard_owner.clipboard_clear()
        self.clipboard_owner.clipboard_append(selected_text)

    def clipboard_text(self):
        clipboard_text = None
        try:
            clipboard_text = self.clipboard_owner.clipboard_get()
        except tk.TclError:
            pass
        return clipboard_text

    def paste(self):
        clipboard_text = self.clipboard_text()
        if clipboard_text is None:
            return
        autoseparators_enabled = True
        can_configure_autoseparators = True
        try:
            autoseparators_value = self.text_widget.cget('autoseparators')
            autoseparators_enabled = bool(int(autoseparators_value))
        except (tk.TclError, TypeError, ValueError):
            can_configure_autoseparators = False

        if can_configure_autoseparators:
            self.text_widget.configure(autoseparators=False)
        self.text_widget.edit_separator()
        self.delete_selection()
        self.text_widget.insert(tk.INSERT, clipboard_text)
        self.text_widget.edit_separator()
        if can_configure_autoseparators and autoseparators_enabled:
            self.text_widget.configure(autoseparators=True)

    def undo(self):
        try:
            self.text_widget.edit_undo()
        except tk.TclError:
            pass

    def delete_selection_before_typing(self, event):
        control_key_pressed = bool(event.state & 0x4)
        if control_key_pressed:
            return
        inserts_character = bool(event.char)
        inserts_control_character = event.keysym in ('Return', 'KP_Enter', 'Tab')
        if inserts_character or inserts_control_character:
            self.delete_selection()


class CodeLineNumberColumn:
    def __init__(self, parent, text_widget, external_yscrollcommand=None):
        self.parent = parent
        self.text_widget = text_widget
        self.external_yscrollcommand = external_yscrollcommand
        self.line_numbers_text = tk.Text(
            parent,
            width=4,
            wrap='none',
            padx=6,
            takefocus=0,
            state='disabled',
            borderwidth=0,
            highlightthickness=0,
            background='#f2f2f2',
            foreground='#666666',
            cursor='arrow',
        )
        self.line_numbers_text.tag_configure(
            'line_number_alignment',
            justify='right',
        )
        self.line_numbers_text.bind('<MouseWheel>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-4>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-5>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-1>', self.ignore_mouse_click)

        self.text_widget.bind('<<Modified>>', self.on_text_modified, add='+')
        self.text_widget.bind('<Configure>', self.refresh_line_numbers, add='+')
        self.text_widget.bind('<KeyRelease>', self.refresh_line_numbers, add='+')
        self.text_widget.bind('<ButtonRelease-1>', self.refresh_line_numbers, add='+')
        self.text_widget.configure(yscrollcommand=self.on_text_scrolled)

        self.clear_modified_flag()
        self.refresh_line_numbers()

    def clear_modified_flag(self):
        try:
            self.text_widget.edit_modified(False)
        except tk.TclError:
            pass

    def on_text_modified(self, event=None):
        text_is_marked_modified = False
        try:
            text_is_marked_modified = bool(self.text_widget.edit_modified())
        except tk.TclError:
            text_is_marked_modified = True
        if text_is_marked_modified:
            self.clear_modified_flag()
            self.refresh_line_numbers()

    def ignore_mouse_click(self, event=None):
        return 'break'

    def scroll_units_for_event(self, event):
        mouse_delta = 0
        if hasattr(event, 'delta'):
            mouse_delta = event.delta
        if mouse_delta > 0:
            return -1
        if mouse_delta < 0:
            return 1
        button_number = getattr(event, 'num', None)
        if button_number == 4:
            return -1
        if button_number == 5:
            return 1
        return 0

    def scroll_main_text(self, event):
        scroll_units = self.scroll_units_for_event(event)
        if scroll_units == 0:
            return None
        self.text_widget.yview_scroll(scroll_units, 'units')
        self.sync_scroll_position()
        return 'break'

    def on_text_scrolled(self, first_fraction, last_fraction):
        self.line_numbers_text.yview_moveto(first_fraction)
        if self.external_yscrollcommand:
            self.external_yscrollcommand(first_fraction, last_fraction)

    def line_count(self):
        line_number = int(self.text_widget.index('end-1c').split('.')[0])
        if line_number < 1:
            return 1
        return line_number

    def line_number_text_for_count(self, line_count):
        line_numbers = []
        for line_number in range(1, line_count + 1):
            line_numbers.append(str(line_number))
        return '\n'.join(line_numbers)

    def sync_scroll_position(self):
        first_fraction, _ = self.text_widget.yview()
        self.line_numbers_text.yview_moveto(first_fraction)

    def refresh_line_numbers(self, event=None):
        line_count = self.line_count()
        line_number_text = self.line_number_text_for_count(line_count)
        self.line_numbers_text.configure(state='normal')
        self.line_numbers_text.delete('1.0', tk.END)
        self.line_numbers_text.insert(
            '1.0',
            line_number_text,
            'line_number_alignment',
        )
        self.line_numbers_text.configure(
            width=max(3, len(str(line_count)) + 1),
        )
        self.line_numbers_text.configure(state='disabled')
        self.sync_scroll_position()


class TextCursorPositionIndicator:
    def __init__(self, text_widget, label_widget):
        self.text_widget = text_widget
        self.label_widget = label_widget
        self.text_widget.bind('<KeyRelease>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-1>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-2>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-3>', self.update_position, add='+')
        self.text_widget.bind('<FocusIn>', self.update_position, add='+')
        self.update_position()

    def line_and_column(self):
        try:
            line_text, zero_based_column_text = self.text_widget.index(tk.INSERT).split(
                '.'
            )
            line_number = int(line_text)
            one_based_column_number = int(zero_based_column_text) + 1
            return line_number, one_based_column_number
        except (tk.TclError, ValueError):
            return None, None

    def update_position(self, event=None):
        line_number, column_number = self.line_and_column()
        if line_number is None or column_number is None:
            self.label_widget.config(text='Ln -, Col -')
            return
        self.label_widget.config(text=f'Ln {line_number}, Col {column_number}')


def configure_widget_if_alive(widget, **configuration):
    if widget is None:
        return
    widget_exists = False
    try:
        widget_exists = bool(widget.winfo_exists())
    except tk.TclError:
        widget_exists = False
    if widget_exists:
        try:
            widget.configure(**configuration)
        except tk.TclError:
            pass


class JsonResultDialog(tk.Toplevel):
    def __init__(self, parent, title, result_payload):
        super().__init__(parent)
        self.title(title)
        self.geometry('800x600')
        self.transient(parent)
        self.grab_set()
        self.focus_force()

        self.result_text = tk.Text(self, wrap='word')
        self.result_text.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        rendered_result = json.dumps(
            result_payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        self.result_text.insert('1.0', rendered_result)
        self.result_text.config(state='disabled')

        self.close_button = tk.Button(self, text='Close', command=self.destroy)
        self.close_button.pack(pady=10)


class CodePanel(tk.Frame):
    def __init__(self, parent, application, tab_key=None):
        super().__init__(parent)

        self.application = application
        self.tab_key = tab_key

        self.text_editor = tk.Text(self, tabs=('4',), wrap='none', undo=True)
        self.editable_text = EditableText(self.text_editor, self)

        self.scrollbar_y = tk.Scrollbar(
            self,
            orient='vertical',
            command=self.text_editor.yview,
        )
        self.scrollbar_x = tk.Scrollbar(
            self,
            orient='horizontal',
            command=self.text_editor.xview,
        )
        self.line_number_column = CodeLineNumberColumn(
            self,
            self.text_editor,
            external_yscrollcommand=self.scrollbar_y.set,
        )
        self.text_editor.configure(
            xscrollcommand=self.scrollbar_x.set,
        )

        self.line_number_column.line_numbers_text.grid(
            row=0,
            column=0,
            sticky='ns',
        )
        self.text_editor.grid(row=0, column=1, sticky='nsew')
        self.scrollbar_y.grid(row=0, column=2, sticky='ns')
        self.scrollbar_x.grid(row=1, column=1, sticky='ew')
        self.cursor_position_label = ttk.Label(self, text='Ln 1, Col 1')
        self.cursor_position_label.grid(
            row=2,
            column=1,
            sticky='e',
            pady=(2, 0),
        )
        self.cursor_position_indicator = TextCursorPositionIndicator(
            self.text_editor,
            self.cursor_position_label,
        )

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.text_editor.tag_configure('smalltalk_keyword', foreground='blue')
        self.text_editor.tag_configure('smalltalk_comment', foreground='green')
        self.text_editor.tag_configure('smalltalk_string', foreground='orange')
        self.text_editor.tag_configure('highlight', background='darkgrey')
        self.text_editor.tag_configure(
            'breakpoint_marker',
            background='#ff6b6b',
            foreground='black',
        )

        self.text_editor.bind('<Control-a>', self.select_all_text_editor)
        self.text_editor.bind('<Control-A>', self.select_all_text_editor)
        self.text_editor.bind('<Control-c>', self.copy_text_editor_selection)
        self.text_editor.bind('<Control-C>', self.copy_text_editor_selection)
        self.text_editor.bind('<Control-v>', self.paste_into_text_editor)
        self.text_editor.bind('<Control-V>', self.paste_into_text_editor)
        self.text_editor.bind('<Control-z>', self.undo_text_editor)
        self.text_editor.bind('<Control-Z>', self.undo_text_editor)
        self.text_editor.bind(
            '<KeyPress>', self.replace_selected_text_editor_before_typing, add='+'
        )
        self.text_editor.bind('<KeyRelease>', self.on_key_release)
        self.text_editor.bind('<Button-3>', self.open_text_menu)

        self.current_context_menu = None
        self.text_editor.bind('<Button-1>', self.close_context_menu, add='+')

    def is_read_only(self):
        is_busy = self.application.integrated_session_state.is_mcp_busy()
        action_gate = getattr(self.application, 'action_gate', None)
        if action_gate is None:
            return is_busy
        return action_gate.read_only_for('method_editor_source', is_busy=is_busy)

    def set_read_only(self, read_only):
        text_state = tk.NORMAL
        if read_only:
            text_state = tk.DISABLED
        configure_widget_if_alive(self.text_editor, state=text_state)

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record

    def method_context(self):
        if self.tab_key is not None:
            return self.tab_key
        gemstone_session_record = self.gemstone_session_record
        if gemstone_session_record is None:
            return None
        class_name = gemstone_session_record.selected_class
        method_selector = gemstone_session_record.selected_method_symbol
        show_instance_side = gemstone_session_record.show_instance_side
        has_complete_context = class_name is not None and method_selector is not None
        if not has_complete_context:
            return None
        return (class_name, show_instance_side, method_selector)

    def selected_text(self):
        try:
            return self.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ''

    def select_all_text_editor(self, event=None):
        self.editable_text.select_all()
        return 'break'

    def copy_text_editor_selection(self, event=None):
        self.editable_text.copy_selection()
        return 'break'

    def paste_into_text_editor(self, event=None):
        self.editable_text.paste()
        return 'break'

    def undo_text_editor(self, event=None):
        self.editable_text.undo()
        return 'break'

    def replace_selected_text_editor_before_typing(self, event):
        self.editable_text.delete_selection_before_typing(event)

    def selector_token(self, token_text):
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

    def cursor_offset(self):
        cursor_index = self.text_editor.index(tk.INSERT)
        characters = self.text_editor.count('1.0', cursor_index, 'chars')
        if not characters:
            return 0
        return int(characters[0])

    def selector_entry_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            return None
        class_name, show_instance_side, method_selector = method_context
        sends_payload = self.gemstone_session_record.method_sends(
            class_name,
            method_selector,
            show_instance_side,
        )
        cursor_offset = self.cursor_offset()
        for send_entry in sends_payload.get('sends', []):
            starts_before_or_at_cursor = send_entry['start_offset'] <= cursor_offset
            ends_after_cursor = cursor_offset < send_entry['end_offset']
            if starts_before_or_at_cursor and ends_after_cursor:
                return send_entry
        return None

    def word_under_cursor(self):
        line, column = self.text_editor.index(tk.INSERT).split('.')
        line_text = self.text_editor.get(f'{line}.0', f'{line}.end')
        cursor_column = int(column)
        token_matches = [
            match
            for match in re.finditer(
                r'[-+*/\\~<>=@%,|&?!]+|[A-Za-z_]\w*:?',
                line_text,
            )
            if match.start() <= cursor_column <= match.end()
        ]
        token_match = token_matches[0] if token_matches else None
        if token_match is None:
            return ''
        return token_match.group(0)

    def selector_for_navigation(self):
        selected_text = self.selected_text()
        selector_from_selection = self.selector_token(selected_text)
        if selector_from_selection is not None:
            return selector_from_selection
        send_entry = self.selector_entry_at_cursor()
        if send_entry is not None:
            return send_entry['selector']
        selector_from_cursor = self.selector_token(self.word_under_cursor())
        if selector_from_cursor is not None:
            return selector_from_cursor
        method_context = self.method_context()
        if method_context is None:
            return None
        return method_context[2]

    def open_text_menu(self, event):
        self.text_editor.mark_set(tk.INSERT, f'@{event.x},{event.y}')
        if self.current_context_menu:
            self.current_context_menu.unpost()

        self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = self.is_read_only()
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        self.current_context_menu.add_command(
            label='Select All',
            command=self.select_all_text_editor,
        )
        self.current_context_menu.add_command(
            label='Copy',
            command=self.copy_text_editor_selection,
        )
        self.current_context_menu.add_command(
            label='Paste',
            command=self.paste_into_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Undo',
            command=self.undo_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_separator()
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is not None:
            self.current_context_menu.add_command(
                label='Jump to Class',
                command=self.jump_to_method_context,
            )
            self.current_context_menu.add_separator()
            self.current_context_menu.add_command(
                label='Save',
                command=self.save_current_tab,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Close',
                command=self.close_current_tab,
            )
            self.current_context_menu.add_command(
                label='Set Breakpoint Here',
                command=self.set_breakpoint_at_cursor,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Clear Breakpoint Here',
                command=self.clear_breakpoint_at_cursor,
                state=write_command_state,
            )
            self.current_context_menu.add_separator()
        selected_text = self.selected_text()
        if selected_text:
            self.current_context_menu.add_command(
                label='Run',
                command=lambda: self.run_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_command(
                label='Inspect',
                command=lambda: self.inspect_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_command(
                label='Show in Object Diagram',
                command=lambda: self.show_selected_text_in_object_diagram(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Implementors',
            command=self.open_implementors_from_source,
        )
        self.current_context_menu.add_command(
            label='Senders',
            command=self.open_senders_from_source,
        )
        self.current_context_menu.add_command(
            label='References',
            command=self.find_references_from_source,
        )
        if self.application.experimental_features_enabled:
            self.current_context_menu.add_separator()
            self.current_context_menu.add_command(
                label='Apply Rename Method',
                command=self.apply_method_rename,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Apply Move Method',
                command=self.apply_method_move,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Apply Add Parameter',
                command=self.apply_method_add_parameter,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Apply Remove Parameter',
                command=self.apply_method_remove_parameter,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Apply Extract Method',
                command=self.apply_method_extract,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Apply Inline Method',
                command=self.apply_method_inline,
                state=write_command_state,
            )
        add_close_command_to_popup_menu(self.current_context_menu)
        self.current_context_menu.bind(
            '<Escape>',
            lambda popup_event: close_popup_menu(self.current_context_menu),
        )
        self.current_context_menu.post(event.x_root, event.y_root)

    def active_editor_tab(self):
        parent_widget = self.master
        has_editor_tab_shape = (
            parent_widget is not None
            and hasattr(parent_widget, 'save')
            and hasattr(parent_widget, 'method_editor')
        )
        if not has_editor_tab_shape:
            return None
        return parent_widget

    def is_debugger_source_panel(self):
        debugger_tab = getattr(self.application, 'debugger_tab', None)
        if debugger_tab is None:
            return False
        return debugger_tab.code_panel is self

    def save_current_tab(self):
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is None:
            return
        active_editor_tab.save()

    def close_current_tab(self):
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is None:
            return
        active_editor_tab.method_editor.close_tab(active_editor_tab)

    def source_offset_at_cursor(self):
        return self.cursor_offset() + 1

    def set_breakpoint_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before setting a breakpoint.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        requested_source_offset = self.source_offset_at_cursor()
        try:
            breakpoint_entry = self.gemstone_session_record.set_breakpoint(
                class_name,
                show_instance_side,
                method_selector,
                requested_source_offset,
            )
            self.application.event_queue.publish(
                'BreakpointSet',
                log_context={
                    'class_name': class_name,
                    'method': method_selector,
                    'source_offset': breakpoint_entry['source_offset'],
                },
            )
            current_source = self.text_editor.get('1.0', 'end-1c')
            self.apply_breakpoint_markers(current_source)
            resolved_source_offset = breakpoint_entry['source_offset']
            if resolved_source_offset != requested_source_offset:
                requested_line, requested_column = (
                    self.line_and_column_for_source_offset(requested_source_offset)
                )
                resolved_line, resolved_column = self.line_and_column_for_source_offset(
                    resolved_source_offset
                )
                messagebox.showinfo(
                    'Breakpoint Set',
                    (
                        'Requested line %s, column %s. '
                        'Breakpoint set at nearest executable location '
                        'line %s, column %s.'
                    )
                    % (
                        requested_line,
                        requested_column,
                        resolved_line,
                        resolved_column,
                    ),
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Set Breakpoint', str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror('Set Breakpoint', str(error))

    def clear_breakpoint_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before clearing a breakpoint.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        source_offset = self.source_offset_at_cursor()
        try:
            self.gemstone_session_record.clear_breakpoint_at(
                class_name,
                show_instance_side,
                method_selector,
                source_offset,
            )
            self.application.event_queue.publish(
                'BreakpointCleared',
                log_context={
                    'class_name': class_name,
                    'method': method_selector,
                    'source_offset': source_offset,
                },
            )
            current_source = self.text_editor.get('1.0', 'end-1c')
            self.apply_breakpoint_markers(current_source)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Clear Breakpoint', str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror('Clear Breakpoint', str(error))

    def jump_to_method_context(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        self.application.handle_sender_selection(
            class_name,
            show_instance_side,
            method_selector,
        )

    def close_context_menu(self, event):
        if self.current_context_menu:
            self.current_context_menu.unpost()
            self.current_context_menu = None

    def run_selected_text(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                'Read Only',
                'MCP is busy. Run is disabled until MCP finishes.',
            )
            return
        self.application.event_queue.publish('SourceTextRun', log_context={'code': selected_text})
        self.application.run_code(selected_text)

    def inspect_selected_text(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                'Read Only',
                'MCP is busy. Inspect is disabled until MCP finishes.',
            )
            return
        if self.is_debugger_source_panel():
            debugger_tab = self.application.debugger_tab
            debugger_tab.inspect_selected_source_expression(selected_text)
            return
        self.application.event_queue.publish('SourceTextInspected', log_context={'code': selected_text})
        try:
            inspected_object = self.gemstone_session_record.run_code(selected_text)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Inspect Selection', str(domain_exception))
            self.application.event_queue.publish('SourceTextInspectFailed', log_context={
                'code': selected_text,
                'error': str(domain_exception),
            })
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Inspect Selection', str(gemstone_exception))
            self.application.event_queue.publish('SourceTextInspectFailed', log_context={
                'code': selected_text,
                'error': str(gemstone_exception),
            })
            return
        if hasattr(self.application, 'open_inspector_for_object'):
            self.application.open_inspector_for_object(inspected_object)

    def show_selected_text_in_object_diagram(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                'Read Only',
                'MCP is busy. Object diagram is disabled until MCP finishes.',
            )
            return
        if self.is_debugger_source_panel():
            debugger_tab = self.application.debugger_tab
            debugger_tab.show_selected_source_expression_in_object_diagram(selected_text)
            return
        try:
            inspected_object = self.gemstone_session_record.run_code(selected_text)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Show in Object Diagram', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Show in Object Diagram', str(gemstone_exception))
            return
        if hasattr(self.application, 'open_object_diagram_for_object'):
            self.application.open_object_diagram_for_object(inspected_object)

    def open_implementors_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
            )
            return
        self.application.event_queue.publish('ImplementorsOpened', log_context={'selector': selector})
        self.application.open_implementors_dialog(method_symbol=selector)

    def open_senders_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
            )
            return
        context = self.method_context()
        source_class_name = context[0] if context is not None else None
        self.application.event_queue.publish('SendersOpened', log_context={'selector': selector})
        self.application.open_senders_dialog(
            method_symbol=selector,
            source_class_name=source_class_name,
        )

    def class_name_for_reference_lookup(self):
        selected_text = self.selected_text()
        candidate = selected_text if selected_text else self.word_under_cursor()
        candidate = (candidate or '').strip()
        if not candidate:
            return None
        class_name_match = re.search(r'[A-Za-z_]\w*', candidate)
        if class_name_match is None:
            return None
        return class_name_match.group(0)

    def find_references_from_source(self):
        class_name = self.class_name_for_reference_lookup()
        if class_name is None:
            messagebox.showwarning(
                'No Class Name',
                'Could not determine a class name at the current cursor position.',
            )
            return
        self.application.open_find_dialog_for_class(class_name)

    def run_method_analysis(self, analysis_function, title):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        try:
            analysis_result = analysis_function(
                class_name,
                method_selector,
                show_instance_side,
            )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(self.application, title, analysis_result)

    def show_method_sends(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_sends,
            'Method Sends',
        )

    def show_method_structure(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_structure_summary,
            'Method Structure',
        )

    def show_method_control_flow(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_control_flow_summary,
            'Method Control Flow',
        )

    def show_method_ast(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_ast,
            'Method AST',
        )

    def new_selector_name(self, default_selector):
        return simpledialog.askstring(
            'Rename Method',
            'New selector name:',
            initialvalue=default_selector,
            parent=self.application,
        )

    def run_method_rename(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, old_selector = method_context
        new_selector = self.new_selector_name(old_selector)
        if not new_selector:
            return
        if apply_change:
            should_apply = messagebox.askyesno(
                'Confirm Rename',
                (
                    'Apply rename of %s to %s on %s (%s side)?'
                    % (
                        old_selector,
                        new_selector,
                        class_name,
                        'instance' if show_instance_side else 'class',
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                rename_result = self.gemstone_session_record.apply_method_rename(
                    class_name,
                    show_instance_side,
                    old_selector,
                    new_selector,
                )
            else:
                rename_result = self.gemstone_session_record.preview_method_rename(
                    class_name,
                    show_instance_side,
                    old_selector,
                    new_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Method Rename %s' % ('Apply' if apply_change else 'Preview'),
            rename_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_rename(self):
        self.run_method_rename(apply_change=False)

    def apply_method_rename(self):
        self.run_method_rename(apply_change=True)

    def side_input_to_boolean(self, side_input):
        normalized_side = (side_input or '').strip().lower()
        if normalized_side in ('instance', 'instance side', 'i'):
            return True
        if normalized_side in ('class', 'class side', 'meta', 'c'):
            return False
        return None

    def move_target_details(self, show_instance_side):
        target_class_name = simpledialog.askstring(
            'Move Method',
            'Target class name:',
            parent=self.application,
        )
        if not target_class_name:
            return None
        default_side = 'instance' if show_instance_side else 'class'
        target_side = simpledialog.askstring(
            'Move Method',
            'Target side (instance/class):',
            initialvalue=default_side,
            parent=self.application,
        )
        target_show_instance_side = self.side_input_to_boolean(target_side)
        if target_show_instance_side is None:
            messagebox.showerror(
                'Invalid Side',
                'Target side must be instance or class.',
            )
            return None
        return (target_class_name, target_show_instance_side)

    def run_method_move(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        source_class_name, source_show_instance_side, method_selector = method_context
        target_details = self.move_target_details(source_show_instance_side)
        if target_details is None:
            return
        target_class_name, target_show_instance_side = target_details
        overwrite_target_method = False
        delete_source_method = True
        if apply_change:
            overwrite_target_method = messagebox.askyesno(
                'Move Method',
                'Overwrite target method when it already exists?',
            )
            delete_source_method = messagebox.askyesno(
                'Move Method',
                'Delete source method after move?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Move',
                (
                    'Apply move of %s from %s (%s side) to %s (%s side)?'
                    % (
                        method_selector,
                        source_class_name,
                        'instance' if source_show_instance_side else 'class',
                        target_class_name,
                        'instance' if target_show_instance_side else 'class',
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                move_result = self.gemstone_session_record.apply_method_move(
                    source_class_name,
                    source_show_instance_side,
                    target_class_name,
                    target_show_instance_side,
                    method_selector,
                    overwrite_target_method=overwrite_target_method,
                    delete_source_method=delete_source_method,
                )
            else:
                move_result = self.gemstone_session_record.preview_method_move(
                    source_class_name,
                    source_show_instance_side,
                    target_class_name,
                    target_show_instance_side,
                    method_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Method Move %s' % ('Apply' if apply_change else 'Preview'),
            move_result,
        )
        if apply_change:
            self.application.event_queue.publish('SelectedClassChanged')
            self.application.event_queue.publish('SelectedCategoryChanged')
            self.application.event_queue.publish('MethodSelected')

    def preview_method_move(self):
        self.run_method_move(apply_change=False)

    def apply_method_move(self):
        self.run_method_move(apply_change=True)

    def parameter_keyword_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Parameter keyword (for example with:):',
            initialvalue='with:',
            parent=self.application,
        )

    def parameter_name_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Parameter name:',
            initialvalue='newValue',
            parent=self.application,
        )

    def default_argument_source_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Default argument source expression:',
            initialvalue='nil',
            parent=self.application,
        )

    def run_method_add_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        parameter_keyword = self.parameter_keyword_input()
        if not parameter_keyword:
            return
        parameter_name = self.parameter_name_input()
        if not parameter_name:
            return
        default_argument_source = self.default_argument_source_input()
        if not default_argument_source:
            return
        if apply_change:
            should_apply = messagebox.askyesno(
                'Confirm Add Parameter',
                (
                    'Apply add-parameter on %s>>%s with keyword %s?'
                    % (
                        class_name,
                        method_selector,
                        parameter_keyword,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                add_parameter_result = (
                    self.gemstone_session_record.apply_method_add_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        parameter_name,
                        default_argument_source,
                    )
                )
            else:
                add_parameter_result = (
                    self.gemstone_session_record.preview_method_add_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        parameter_name,
                        default_argument_source,
                    )
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Add Parameter %s' % ('Apply' if apply_change else 'Preview'),
            add_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=False)

    def apply_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=True)

    def remove_parameter_keyword_input(self):
        return simpledialog.askstring(
            'Remove Parameter',
            'Parameter keyword to remove:',
            parent=self.application,
        )

    def run_method_remove_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        parameter_keyword = self.remove_parameter_keyword_input()
        if not parameter_keyword:
            return
        rewrite_source_senders = messagebox.askyesno(
            'Remove Parameter',
            'Rewrite same-class senders that use this keyword selector?',
        )
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                'Remove Parameter',
                'Overwrite generated selector when it already exists?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Remove Parameter',
                (
                    'Apply remove-parameter on %s>>%s removing %s?'
                    % (
                        class_name,
                        method_selector,
                        parameter_keyword,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                remove_parameter_result = (
                    self.gemstone_session_record.apply_method_remove_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        overwrite_new_method=overwrite_new_method,
                        rewrite_source_senders=rewrite_source_senders,
                    )
                )
            else:
                remove_parameter_result = (
                    self.gemstone_session_record.preview_method_remove_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        rewrite_source_senders=rewrite_source_senders,
                    )
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Remove Parameter %s' % ('Apply' if apply_change else 'Preview'),
            remove_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_remove_parameter(self):
        self.run_method_remove_parameter(apply_change=False)

    def apply_method_remove_parameter(self):
        self.run_method_remove_parameter(apply_change=True)

    def new_selector_input(self, title_text, prompt_text, initial_value=None):
        return simpledialog.askstring(
            title_text,
            prompt_text,
            initialvalue=initial_value,
            parent=self.application,
        )

    def text_offset_for_index(self, text_index):
        characters = self.text_editor.count('1.0', text_index, 'chars')
        if not characters:
            return 0
        return int(characters[0])

    def selected_text_offsets(self):
        try:
            selection_start_index = self.text_editor.index(tk.SEL_FIRST)
            selection_end_index = self.text_editor.index(tk.SEL_LAST)
        except tk.TclError:
            return None
        selection_start_offset = self.text_offset_for_index(selection_start_index)
        selection_end_offset = self.text_offset_for_index(selection_end_index)
        if selection_start_offset <= selection_end_offset:
            return (selection_start_offset, selection_end_offset)
        return (selection_end_offset, selection_start_offset)

    def selector_from_words(self, text):
        words = re.findall(r'[A-Za-z0-9]+', text)
        if not words:
            return 'extractedPart'
        capitalized_words = ''.join(
            word[0:1].upper() + word[1:] for word in words if word
        )
        if not capitalized_words:
            return 'extractedPart'
        selector = 'extracted%s' % capitalized_words
        normalized_selector = re.sub(r'[^A-Za-z0-9_]', '', selector)
        if not normalized_selector:
            return 'extractedPart'
        if normalized_selector[0].isdigit():
            normalized_selector = 'extracted%s' % normalized_selector
        return normalized_selector[0].lower() + normalized_selector[1:]

    def method_argument_names_from_ast_header(
        self,
        method_ast_payload,
        method_selector,
    ):
        selector_tokens = [
            '%s:' % selector_part
            for selector_part in method_selector.split(':')
            if selector_part
        ]
        if not selector_tokens:
            return []
        header_source = method_ast_payload.get('header_source', '')
        cursor = 0
        argument_names = []
        for selector_token in selector_tokens:
            while cursor < len(header_source) and header_source[cursor].isspace():
                cursor = cursor + 1
            token_matches = header_source.startswith(selector_token, cursor)
            if not token_matches:
                return []
            cursor = cursor + len(selector_token)
            while cursor < len(header_source) and header_source[cursor].isspace():
                cursor = cursor + 1
            argument_match = re.match(
                r'[A-Za-z_][A-Za-z0-9_]*',
                header_source[cursor:],
            )
            if argument_match is None:
                return []
            argument_name = argument_match.group(0)
            argument_names.append(argument_name)
            cursor = cursor + len(argument_name)
        return argument_names

    def inferred_extract_argument_names(
        self,
        method_ast_payload,
        selected_statement_entries,
        method_selector,
    ):
        method_temporaries = method_ast_payload.get('temporaries', [])
        method_arguments = self.method_argument_names_from_ast_header(
            method_ast_payload,
            method_selector,
        )
        scoped_names = []
        for name in method_arguments + method_temporaries:
            if name not in scoped_names:
                scoped_names.append(name)
        assignment_targets = []
        for statement_entry in selected_statement_entries:
            assignment_match = re.match(
                r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=',
                statement_entry.get('source', ''),
            )
            has_assignment = assignment_match is not None
            if has_assignment:
                target_name = assignment_match.group(1)
                if target_name not in assignment_targets:
                    assignment_targets.append(target_name)
        inferred_argument_names = []
        for statement_entry in selected_statement_entries:
            statement_source = statement_entry.get('source', '')
            identifier_matches = re.finditer(
                r'[A-Za-z_][A-Za-z0-9_]*',
                statement_source,
            )
            for identifier_match in identifier_matches:
                identifier_name = identifier_match.group(0)
                is_scoped = identifier_name in scoped_names
                is_assigned = identifier_name in assignment_targets
                is_already_inferred = identifier_name in inferred_argument_names
                if is_scoped and not is_assigned and not is_already_inferred:
                    inferred_argument_names.append(identifier_name)
        return inferred_argument_names

    def suggested_extract_selector(
        self,
        selected_statement_entries,
        inferred_argument_names,
    ):
        if not selected_statement_entries:
            return 'extractedPart'
        first_statement = selected_statement_entries[0]
        statement_source = first_statement.get('source', '').strip()
        assignment_match = re.match(
            r'([A-Za-z_]\w*)\s*:=',
            statement_source,
        )
        if assignment_match:
            variable_name = assignment_match.group(1)
            base_selector = self.selector_from_words('compute %s' % variable_name)
        else:
            sends = first_statement.get('sends', [])
            if sends:
                base_selector = self.selector_from_words(sends[0].get('selector', ''))
            else:
                base_selector = self.selector_from_words(statement_source)
        if not inferred_argument_names:
            return base_selector
        keyword_tokens = ['%s:' % base_selector]
        for argument_name in inferred_argument_names[1:]:
            keyword_token = re.sub(r'[^A-Za-z0-9_]', '', argument_name) or 'with'
            keyword_tokens.append('%s:' % keyword_token)
        return ''.join(keyword_tokens)

    def selected_statement_entries_from_offsets(
        self,
        method_ast_payload,
        selection_offsets,
    ):
        if selection_offsets is None:
            raise DomainException(
                'Select one or more top-level statements before extracting.'
            )
        statements = method_ast_payload.get('statements', [])
        if not statements:
            raise DomainException('No extractable top-level statements found.')
        selection_start_offset, selection_end_offset = selection_offsets
        selected_statement_entries = [
            statement_entry
            for statement_entry in statements
            if (
                statement_entry['start_offset'] >= selection_start_offset
                and statement_entry['end_offset'] <= selection_end_offset
            )
        ]
        if not selected_statement_entries:
            raise DomainException(
                'Selection must fully cover one or more top-level statements.'
            )
        sorted_statement_entries = sorted(
            selected_statement_entries,
            key=lambda statement_entry: statement_entry['statement_index'],
        )
        statement_indexes = [
            statement_entry['statement_index']
            for statement_entry in sorted_statement_entries
        ]
        expected_statement_indexes = list(
            range(
                statement_indexes[0],
                statement_indexes[-1] + 1,
            )
        )
        if statement_indexes != expected_statement_indexes:
            raise DomainException(
                'Selection must cover contiguous top-level statements.'
            )
        return sorted_statement_entries

    def run_method_extract(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        try:
            selection_offsets = self.selected_text_offsets()
            if selection_offsets is None:
                raise DomainException(
                    'Select one or more top-level statements before extracting.'
                )
            method_ast_payload = self.gemstone_session_record.method_ast(
                class_name,
                method_selector,
                show_instance_side,
            )
            selected_statement_entries = self.selected_statement_entries_from_offsets(
                method_ast_payload,
                selection_offsets,
            )
            statement_indexes = [
                statement_entry['statement_index']
                for statement_entry in selected_statement_entries
            ]
            inferred_argument_names = self.inferred_extract_argument_names(
                method_ast_payload,
                selected_statement_entries,
                method_selector,
            )
            suggested_selector = self.suggested_extract_selector(
                selected_statement_entries,
                inferred_argument_names,
            )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror(
                'Extract Method',
                str(domain_exception),
            )
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Extract Method', str(gemstone_exception))
            return
        new_selector = self.new_selector_input(
            'Extract Method',
            'Name for extracted method:',
            initial_value=suggested_selector,
        )
        if not new_selector:
            return
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                'Extract Method',
                'Overwrite extracted method when it already exists?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Extract Method',
                (
                    'Apply extract-method on %s>>%s to %s using statements %s?'
                    % (
                        class_name,
                        method_selector,
                        new_selector,
                        statement_indexes,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                extract_result = self.gemstone_session_record.apply_method_extract(
                    class_name,
                    show_instance_side,
                    method_selector,
                    new_selector,
                    statement_indexes,
                    overwrite_new_method=overwrite_new_method,
                )
            else:
                extract_result = self.gemstone_session_record.preview_method_extract(
                    class_name,
                    show_instance_side,
                    method_selector,
                    new_selector,
                    statement_indexes,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Extract Method %s' % ('Apply' if apply_change else 'Preview'),
            extract_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_extract(self):
        self.run_method_extract(apply_change=False)

    def apply_method_extract(self):
        self.run_method_extract(apply_change=True)

    def inline_selector_input(self):
        return self.new_selector_input(
            'Inline Method',
            'Inline selector:',
        )

    def run_method_inline(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, caller_selector = method_context
        inline_selector = self.inline_selector_input()
        if not inline_selector:
            return
        delete_inlined_method = False
        if apply_change:
            delete_inlined_method = messagebox.askyesno(
                'Inline Method',
                'Delete the inlined callee method after rewriting caller?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Inline Method',
                (
                    'Apply inline-method in %s>>%s for selector %s?'
                    % (
                        class_name,
                        caller_selector,
                        inline_selector,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                inline_result = self.gemstone_session_record.apply_method_inline(
                    class_name,
                    show_instance_side,
                    caller_selector,
                    inline_selector,
                    delete_inlined_method=delete_inlined_method,
                )
            else:
                inline_result = self.gemstone_session_record.preview_method_inline(
                    class_name,
                    show_instance_side,
                    caller_selector,
                    inline_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Inline Method %s' % ('Apply' if apply_change else 'Preview'),
            inline_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_inline(self):
        self.run_method_inline(apply_change=False)

    def apply_method_inline(self):
        self.run_method_inline(apply_change=True)

    def apply_syntax_highlighting(self, text):
        for match in re.finditer(r'\b(class|self|super|true|false|nil)\b', text):
            start, end = match.span()
            self.text_editor.tag_add(
                'smalltalk_keyword', f'1.0 + {start} chars', f'1.0 + {end} chars'
            )

        for match in re.finditer(r'".*?"', text):
            start, end = match.span()
            self.text_editor.tag_add(
                'smalltalk_comment', f'1.0 + {start} chars', f'1.0 + {end} chars'
            )

        for match in re.finditer(r"\'.*?\'", text):
            start, end = match.span()
            self.text_editor.tag_add(
                'smalltalk_string', f'1.0 + {start} chars', f'1.0 + {end} chars'
            )

    def on_key_release(self, event):
        text = self.text_editor.get('1.0', tk.END)
        self.apply_syntax_highlighting(text)
        self.apply_breakpoint_markers(text)

    def line_and_column_for_source_offset(self, source_offset):
        source_text = self.text_editor.get('1.0', 'end-1c')
        source_length = len(source_text)
        normalized_source_offset = source_offset
        if normalized_source_offset < 1:
            normalized_source_offset = 1
        maximum_offset = source_length + 1
        if normalized_source_offset > maximum_offset:
            normalized_source_offset = maximum_offset
        index_text = self.text_editor.index(
            f'1.0 + {normalized_source_offset - 1} chars'
        )
        line_text, column_text = index_text.split('.')
        return int(line_text), int(column_text) + 1

    def breakpoint_entries_for_current_method(self):
        if self.tab_key is None:
            return []
        gemstone_session_record = self.gemstone_session_record
        if gemstone_session_record is None:
            return []
        class_name, show_instance_side, method_selector = self.tab_key
        breakpoint_entries = gemstone_session_record.list_breakpoints()
        matching_breakpoints = []
        index = 0
        breakpoint_count = len(breakpoint_entries)
        while index < breakpoint_count:
            breakpoint_entry = breakpoint_entries[index]
            same_class = breakpoint_entry['class_name'] == class_name
            same_side = breakpoint_entry['show_instance_side'] == show_instance_side
            same_selector = breakpoint_entry['method_selector'] == method_selector
            if same_class and same_side and same_selector:
                matching_breakpoints.append(breakpoint_entry)
            index += 1
        return matching_breakpoints

    def apply_breakpoint_markers(self, source):
        self.text_editor.tag_remove('breakpoint_marker', '1.0', tk.END)
        breakpoint_entries = self.breakpoint_entries_for_current_method()
        source_length = len(source)
        index = 0
        breakpoint_count = len(breakpoint_entries)
        while index < breakpoint_count:
            source_offset = breakpoint_entries[index]['source_offset']
            normalized_source_offset = source_offset
            if normalized_source_offset < 1:
                normalized_source_offset = 1
            if normalized_source_offset > source_length and source_length > 0:
                normalized_source_offset = source_length
            if source_length > 0:
                start_position = self.text_editor.index(
                    f'1.0 + {normalized_source_offset - 1} chars'
                )
                self.text_editor.tag_add(
                    'breakpoint_marker',
                    start_position,
                    f'{start_position} + 1c',
                )
            index += 1

    def refresh(self, source, mark=None):
        text_editor_was_disabled = self.text_editor.cget('state') == tk.DISABLED
        if text_editor_was_disabled:
            self.text_editor.configure(state=tk.NORMAL)
        self.text_editor.delete('1.0', tk.END)
        self.text_editor.insert('1.0', source)
        if mark is not None and mark >= 0:
            position = self.text_editor.index(f'1.0 + {mark-1} chars')
            self.text_editor.tag_add('highlight', position, f'{position} + 1c')
        self.apply_syntax_highlighting(source)
        self.apply_breakpoint_markers(source)
        self.cursor_position_indicator.update_position()
        if text_editor_was_disabled:
            self.text_editor.configure(state=tk.DISABLED)


class EditorTab(tk.Frame):
    def __init__(self, parent, browser_window, method_editor, tab_key):
        super().__init__(parent)
        self.browser_window = browser_window
        self.method_editor = method_editor
        self.tab_key = tab_key

        self.code_panel = CodePanel(
            self,
            self.browser_window.application,
            tab_key=tab_key,
        )
        self.code_panel.grid(row=0, column=0, sticky='nsew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.repopulate()

    def open_tab_menu(self, event):
        return None

    def save(self):
        selected_class, show_instance_side, method_symbol = self.tab_key
        self.browser_window.gemstone_session_record.update_method_source(
            selected_class,
            show_instance_side,
            method_symbol,
            self.code_panel.text_editor.get('1.0', 'end-1c'),
        )
        self.browser_window.event_queue.publish('MethodSelected', origin=self)
        self.repopulate()

    def repopulate(self):
        gemstone_method = self.browser_window.gemstone_session_record.get_method(
            *self.tab_key
        )
        if gemstone_method:
            method_source = gemstone_method.sourceString().to_py
            self.code_panel.refresh(method_source)
        else:
            self.method_editor.close_tab(self)
