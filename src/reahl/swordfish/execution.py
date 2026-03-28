import re
import tkinter as tk
import tkinter.messagebox as messagebox
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.gemstone import GemstoneDebugSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.inspector import Explorer
from reahl.swordfish.text_editing import (
    CodeLineNumberColumn,
    CodePanel,
    EditableText,
    TextCursorPositionIndicator,
    configure_widget_if_alive,
)
from reahl.swordfish.ui_context import UiContext
from reahl.swordfish.ui_support import add_close_command_to_popup_menu


class RunTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.last_exception = None
        self.current_text_menu = None
        self.ui_context = UiContext('run-tab')

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(5, weight=1)

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 5))
        self.button_frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(
            self.button_frame,
            text='Run',
            command=self.run_code_from_editor,
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5))

        self.debug_button = ttk.Button(
            self.button_frame,
            text='Debug',
            command=self.open_debugger,
        )
        self.debug_button.grid(row=0, column=1, sticky='w', padx=(0, 5))

        self.close_button = ttk.Button(
            self.button_frame,
            text='Close',
            command=self.close_tab,
        )
        self.close_button.grid(row=0, column=3, sticky='e')

        self.source_label = ttk.Label(self, text='Source Code:')
        self.source_label.grid(row=1, column=0, sticky='w', padx=10, pady=(5, 0))

        self.source_editor_frame = ttk.Frame(self)
        self.source_editor_frame.grid(
            row=2,
            column=0,
            sticky='nsew',
            padx=10,
            pady=(0, 10),
        )
        self.source_editor_frame.rowconfigure(0, weight=1)
        self.source_editor_frame.columnconfigure(1, weight=1)
        self.source_text = tk.Text(
            self.source_editor_frame,
            height=10,
            undo=True,
        )
        self.editable_source = EditableText(self.source_text, self)
        self.source_line_number_column = CodeLineNumberColumn(
            self.source_editor_frame,
            self.source_text,
        )
        self.source_line_number_column.line_numbers_text.grid(
            row=0,
            column=0,
            sticky='ns',
        )
        self.source_text.grid(
            row=0,
            column=1,
            sticky='nsew',
        )

        self.status_bar = ttk.Frame(self)
        self.status_bar.grid(row=3, column=0, sticky='ew', padx=10)
        self.status_bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(self.status_bar, text='Ready')
        self.status_label.grid(row=0, column=0, sticky='w')
        self.source_cursor_position_label = ttk.Label(
            self.status_bar,
            text='Ln 1, Col 1',
        )
        self.source_cursor_position_label.grid(
            row=0,
            column=1,
            sticky='e',
        )

        self.result_label = ttk.Label(self, text='Result:')
        self.result_label.grid(row=4, column=0, sticky='nw', padx=10, pady=(10, 0))

        self.result_text = tk.Text(self, height=7, state='disabled')
        self.editable_result = EditableText(self.result_text, self)
        self.result_text.grid(row=5, column=0, sticky='nsew', padx=10, pady=(0, 10))
        self.configure_text_actions()
        self.source_cursor_position_indicator = TextCursorPositionIndicator(
            self.source_text,
            self.source_cursor_position_label,
        )
        self.application.event_queue.subscribe(
            'McpBusyStateChanged',
            self.handle_mcp_busy_state_changed,
            ui_context=self.ui_context,
        )
        self.set_read_only(self.is_read_only())

    def configure_text_actions(self):
        self.source_text.bind('<Control-a>', self.select_all_source_text)
        self.source_text.bind('<Control-A>', self.select_all_source_text)
        self.source_text.bind('<Control-c>', self.copy_source_selection)
        self.source_text.bind('<Control-C>', self.copy_source_selection)
        self.source_text.bind('<Control-v>', self.paste_into_source_text)
        self.source_text.bind('<Control-V>', self.paste_into_source_text)
        self.source_text.bind('<Control-z>', self.undo_source_text)
        self.source_text.bind('<Control-Z>', self.undo_source_text)
        self.source_text.bind(
            '<KeyPress>', self.replace_selected_source_text_before_typing, add='+'
        )
        self.source_text.bind('<Button-3>', self.open_source_text_menu)

        self.result_text.bind('<Control-a>', self.select_all_result_text)
        self.result_text.bind('<Control-A>', self.select_all_result_text)
        self.result_text.bind('<Control-c>', self.copy_result_selection)
        self.result_text.bind('<Control-C>', self.copy_result_selection)
        self.result_text.bind('<Button-3>', self.open_result_text_menu)

        self.source_text.bind('<Button-1>', self.close_text_menu, add='+')
        self.result_text.bind('<Button-1>', self.close_text_menu, add='+')

    def is_read_only(self):
        is_busy = self.application.integrated_session_state.is_mcp_busy()
        action_gate = getattr(self.application, 'action_gate', None)
        if action_gate is None:
            return is_busy
        return action_gate.read_only_for('run_editor_source', is_busy=is_busy)

    def set_read_only(self, read_only):
        source_text_state = tk.NORMAL
        run_button_state = tk.NORMAL
        debug_button_state = tk.NORMAL
        if read_only:
            source_text_state = tk.DISABLED
            run_button_state = tk.DISABLED
            debug_button_state = tk.DISABLED
        configure_widget_if_alive(self.source_text, state=source_text_state)
        configure_widget_if_alive(self.run_button, state=run_button_state)
        configure_widget_if_alive(self.debug_button, state=debug_button_state)

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name='',
        busy_lease_token=None,
    ):
        busy_coordinator = getattr(self.application, 'busy_coordinator', None)
        if busy_coordinator is not None:
            if not busy_coordinator.is_current_lease(busy_lease_token):
                return
        self.set_read_only(is_busy)

    def select_all_source_text(self, event=None):
        self.editable_source.select_all()
        return 'break'

    def copy_source_selection(self, event=None):
        self.editable_source.copy_selection()
        return 'break'

    def paste_into_source_text(self, event=None):
        self.editable_source.paste()
        return 'break'

    def undo_source_text(self, event=None):
        self.editable_source.undo()
        return 'break'

    def replace_selected_source_text_before_typing(self, event):
        self.editable_source.delete_selection_before_typing(event)

    def select_all_result_text(self, event=None):
        self.editable_result.select_all()
        return 'break'

    def copy_result_selection(self, event=None):
        self.editable_result.copy_selection()
        return 'break'

    def open_source_text_menu(self, event):
        self.source_text.mark_set(tk.INSERT, f'@{event.x},{event.y}')
        self.show_text_menu_for_widget(
            event,
            self.source_text,
            allow_paste=True,
            allow_undo=True,
            include_run_actions=True,
        )

    def open_result_text_menu(self, event):
        self.result_text.mark_set(tk.INSERT, f'@{event.x},{event.y}')
        self.show_text_menu_for_widget(
            event,
            self.result_text,
            allow_paste=False,
            allow_undo=False,
            include_run_actions=False,
        )

    def selected_source_text(self):
        start_index, end_index = self.editable_source.selected_range()
        if start_index is None:
            return ''
        return self.source_text.get(start_index, end_index)

    def editable_text_for_widget(self, text_widget):
        if text_widget is self.source_text:
            return self.editable_source
        if text_widget is self.result_text:
            return self.editable_result
        return EditableText(text_widget, self)

    def run_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Run is disabled.')
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text='Select source text to run')
            return
        self.application.event_queue.publish('RunSelectionRun', log_context={'code': selected_text})
        self.status_label.config(text='Running selection...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Running selected source...')
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
                self.application.event_queue.publish('RunSelectionSucceeded', log_context={
                    'code': selected_text,
                    'result': result.asString().to_py,
                })
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                self.application.event_queue.publish('RunSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(domain_exception),
                })
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                self.application.event_queue.publish('RunSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(gemstone_exception),
                })
        finally:
            self.application.end_foreground_activity()

    def inspect_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Inspect is disabled.')
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text='Select source text to inspect')
            return
        self.application.event_queue.publish('InspectSelectionRun', log_context={'code': selected_text})
        self.status_label.config(text='Inspecting selection...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Inspecting selected source...')
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
                self.application.open_inspector_for_object(result)
                self.application.event_queue.publish('InspectSelectionSucceeded', log_context={
                    'code': selected_text,
                    'result': result.asString().to_py,
                })
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                self.application.event_queue.publish('InspectSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(domain_exception),
                })
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                self.application.event_queue.publish('InspectSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(gemstone_exception),
                })
        finally:
            self.application.end_foreground_activity()

    def show_selected_source_text_in_object_diagram(self):
        if self.is_read_only():
            self.status_label.config(
                text='MCP is busy. Object diagram is disabled.'
            )
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(
                text='Select source text to show in Object Diagram'
            )
            return
        self.application.event_queue.publish('DiagramSelectionRun', log_context={'code': selected_text})
        self.status_label.config(text='Showing selection in Object Diagram...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity(
            'Showing selected source in Object Diagram...'
        )
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
                self.application.open_object_diagram_for_object(result)
                self.application.event_queue.publish('DiagramSelectionSucceeded', log_context={
                    'code': selected_text,
                    'result': result.asString().to_py,
                })
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                self.application.event_queue.publish('DiagramSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(domain_exception),
                })
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                self.application.event_queue.publish('DiagramSelectionFailed', log_context={
                    'code': selected_text,
                    'error': str(gemstone_exception),
                })
        finally:
            self.application.end_foreground_activity()

    def show_text_menu_for_widget(
        self,
        event,
        text_widget,
        allow_paste,
        allow_undo,
        include_run_actions,
    ):
        if self.current_text_menu is not None:
            self.current_text_menu.unpost()

        self.current_text_menu = tk.Menu(self, tearoff=0)
        editable_text = self.editable_text_for_widget(text_widget)
        read_only = self.is_read_only()
        paste_command_state = tk.NORMAL
        undo_command_state = tk.NORMAL
        if read_only and text_widget is self.source_text:
            paste_command_state = tk.DISABLED
            undo_command_state = tk.DISABLED
        self.current_text_menu.add_command(
            label='Select All',
            command=editable_text.select_all,
        )
        self.current_text_menu.add_command(
            label='Copy',
            command=editable_text.copy_selection,
        )
        if allow_paste:
            self.current_text_menu.add_command(
                label='Paste',
                command=editable_text.paste,
                state=paste_command_state,
            )
        if allow_undo:
            self.current_text_menu.add_command(
                label='Undo',
                command=editable_text.undo,
                state=undo_command_state,
            )
        if include_run_actions:
            has_selection = bool(self.selected_source_text().strip())
            run_command_state = tk.NORMAL if has_selection else tk.DISABLED
            if self.is_read_only():
                run_command_state = tk.DISABLED
            self.current_text_menu.add_separator()
            self.current_text_menu.add_command(
                label='Run',
                command=self.run_selected_source_text,
                state=run_command_state,
            )
            self.current_text_menu.add_command(
                label='Inspect',
                command=self.inspect_selected_source_text,
                state=run_command_state,
            )
            self.current_text_menu.add_command(
                label='Show in Object Diagram',
                command=self.show_selected_source_text_in_object_diagram,
                state=run_command_state,
            )
        add_close_command_to_popup_menu(self.current_text_menu)
        self.current_text_menu.bind(
            '<Escape>',
            lambda popup_event: self.close_text_menu(popup_event),
        )
        self.current_text_menu.post(event.x_root, event.y_root)

    def close_text_menu(self, event):
        if self.current_text_menu is not None:
            self.current_text_menu.unpost()
            self.current_text_menu = None

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record

    def present_source(self, source, run_immediately=False):
        source_text_was_disabled = self.source_text.cget('state') == tk.DISABLED
        if source_text_was_disabled:
            self.source_text.configure(state=tk.NORMAL)
        if source and source.strip():
            self.source_text.delete('1.0', tk.END)
            self.source_text.insert(tk.END, source)
            self.source_cursor_position_indicator.update_position()
        if source_text_was_disabled:
            self.source_text.configure(state=tk.DISABLED)
        if run_immediately:
            self.run_code_from_editor()

    def run_code_from_editor(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Run is disabled.')
            return
        code_to_run = self.source_text.get('1.0', 'end-1c')
        self.application.event_queue.publish('RunTabCodeRun', log_context={'code': code_to_run})
        self.status_label.config(text='Running...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Running source...')
        try:
            try:
                result = self.gemstone_session_record.run_code(code_to_run)
                self.on_run_complete(result)
                self.application.event_queue.publish('RunTabCodeSucceeded', log_context={
                    'code': code_to_run,
                    'result': result.asString().to_py,
                })
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                self.application.event_queue.publish('RunTabCodeFailed', log_context={
                    'code': code_to_run,
                    'error': str(domain_exception),
                })
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                self.application.event_queue.publish('RunTabCodeFailed', log_context={
                    'code': code_to_run,
                    'error': str(gemstone_exception),
                })
        finally:
            self.application.end_foreground_activity()

    def on_run_complete(self, result):
        self.status_label.config(text='Completed successfully')
        self.clear_source_error_highlight()
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert(tk.END, result.asString().to_py)
        self.result_text.config(state='disabled')

    def on_run_error(self, exception):
        self.last_exception = exception
        error_text = str(exception)
        line_number, column_number = self.compile_error_location_for_exception(
            exception, error_text
        )
        self.show_source_error_highlight(line_number, column_number)
        self.show_error_in_result_panel(error_text, line_number, column_number)
        self.status_label.config(
            text=self.error_status_text(error_text, line_number, column_number)
        )

    def clear_source_error_highlight(self):
        self.source_text.tag_remove('compile_error_location', '1.0', tk.END)

    def source_text_line_count(self):
        return int(self.source_text.index('end-1c').split('.')[0])

    def source_text_line(self, line_number):
        if line_number < 1:
            return None
        line_count = self.source_text_line_count()
        if line_number > line_count:
            return None
        return self.source_text.get(f'{line_number}.0', f'{line_number}.end')

    def show_source_error_highlight(self, line_number, column_number):
        self.clear_source_error_highlight()
        if line_number is None:
            return

        source_line = self.source_text_line(line_number)
        if source_line is None:
            return

        start_index = f'{line_number}.0'
        end_index = f'{line_number}.end'
        if column_number is not None and column_number > 0:
            bounded_column_number = column_number
            if bounded_column_number > len(source_line) + 1:
                bounded_column_number = len(source_line) + 1
            start_index = f'{line_number}.{bounded_column_number - 1}'
            end_index = f'{line_number}.{bounded_column_number}'

        self.source_text.tag_configure(
            'compile_error_location',
            background='#ffe4e4',
            underline=True,
        )
        self.source_text.tag_add('compile_error_location', start_index, end_index)
        self.source_text.see(start_index)

    def show_error_in_result_panel(self, error_text, line_number, column_number):
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert(tk.END, error_text)
        if line_number is not None and column_number is not None:
            source_line = self.source_text_line(line_number)
            if source_line is None:
                source_line = ''
            caret_padding = ''
            if column_number > 1:
                caret_padding = ' ' * (column_number - 1)
            self.result_text.insert(
                tk.END, f'\nLine {line_number}, column {column_number}\n'
            )
            self.result_text.insert(tk.END, f'{source_line}\n')
            self.result_text.insert(tk.END, f'{caret_padding}^\n')
        self.result_text.config(state='disabled')

    def error_status_text(self, error_text, line_number, column_number):
        if line_number is not None and column_number is not None:
            return f'Error: {error_text} (line {line_number}, column {column_number})'
        return f'Error: {error_text}'

    def compile_error_location_for_exception(self, exception, error_text):
        line_number = None
        column_number = None

        line_number, column_number = (
            self.compile_error_location_from_structured_arguments(exception)
        )
        if line_number is None:
            line_number, column_number = self.compile_error_location_from_text(
                error_text
            )
            if line_number is None:
                message_text = self.compile_error_message_text(exception)
                line_number, column_number = self.compile_error_location_from_text(
                    message_text
                )

        return line_number, column_number

    def compile_error_message_text(self, exception):
        message_text = ''
        try:
            message_text = exception.message
        except (AttributeError, GemstoneError, TypeError):
            pass
        return message_text

    def compile_error_location_from_structured_arguments(self, exception):
        error_number = None
        try:
            error_number = exception.number
        except (AttributeError, GemstoneError, TypeError):
            pass
        if error_number != 1001:
            return None, None

        argument_values = self.compile_error_argument_values(exception)
        detail_rows = self.sequence_item(argument_values, 1)
        first_detail = self.sequence_item(detail_rows, 1)
        offset_value = self.sequence_item(first_detail, 2)
        source_text = self.sequence_item(argument_values, 2)

        offset_number = self.python_error_value(offset_value)
        source_value = self.python_error_value(source_text)
        if not isinstance(offset_number, int) or not isinstance(source_value, str):
            return None, None
        return self.line_and_column_for_offset(source_value, offset_number)

    def compile_error_argument_values(self, exception):
        argument_values = ()
        try:
            argument_values = exception.args
        except (AttributeError, GemstoneError, TypeError):
            pass
        return argument_values

    def compile_error_location_from_text(self, error_text):
        if not isinstance(error_text, str):
            return None, None

        line_number = None
        column_number = None

        full_match = re.search(
            r'line\s+(\d+)\s*[,;]?\s*column\s+(\d+)', error_text, re.IGNORECASE
        )
        if full_match:
            line_number = int(full_match.group(1))
            column_number = int(full_match.group(2))

        if line_number is None:
            inverted_match = re.search(
                r'column\s+(\d+)\s*[,;]?\s*line\s+(\d+)', error_text, re.IGNORECASE
            )
            if inverted_match:
                line_number = int(inverted_match.group(2))
                column_number = int(inverted_match.group(1))

        if line_number is None:
            line_only_match = re.search(r'line\s+(\d+)', error_text, re.IGNORECASE)
            if line_only_match:
                line_number = int(line_only_match.group(1))

        return line_number, column_number

    def sequence_item(self, sequence_value, one_based_index):
        if sequence_value is None:
            return None

        if isinstance(sequence_value, (list, tuple)):
            zero_based_index = one_based_index - 1
            if zero_based_index >= 0 and zero_based_index < len(sequence_value):
                return sequence_value[zero_based_index]
            return None

        size_value = self.python_error_value(
            self.message_send_result(sequence_value, 'size')
        )
        if not isinstance(size_value, int):
            return None
        if one_based_index < 1 or one_based_index > size_value:
            return None
        return self.message_send_result(sequence_value, 'at', one_based_index)

    def message_send_result(self, receiver, selector_name, *arguments):
        result = None
        if receiver is None:
            return result
        selector = getattr(receiver, selector_name, None)
        if selector is None:
            return result
        try:
            result = selector(*arguments)
        except (GemstoneError, TypeError, AttributeError):
            pass
        return result

    def python_error_value(self, candidate_value):
        if candidate_value is None:
            return None
        if isinstance(candidate_value, (int, str)):
            return candidate_value

        to_py_value = getattr(candidate_value, 'to_py', None)
        if to_py_value is not None:
            if callable(to_py_value):
                try:
                    return to_py_value()
                except (GemstoneError, TypeError, AttributeError):
                    pass
            if not callable(to_py_value):
                return to_py_value

        as_string_result = self.message_send_result(candidate_value, 'asString')
        as_string_value = getattr(as_string_result, 'to_py', None)
        if callable(as_string_value):
            try:
                return as_string_value()
            except (GemstoneError, TypeError, AttributeError):
                return None
        if as_string_value is not None:
            return as_string_value
        return None

    def line_and_column_for_offset(self, source_text, one_based_offset):
        if one_based_offset < 1:
            return None, None

        bounded_offset = one_based_offset
        if bounded_offset > len(source_text):
            bounded_offset = len(source_text)
        if bounded_offset < 1:
            bounded_offset = 1

        source_before_error = source_text[: bounded_offset - 1]
        line_number = source_before_error.count('\n') + 1
        last_newline_index = source_before_error.rfind('\n')
        column_number = bounded_offset
        if last_newline_index >= 0:
            column_number = len(source_before_error) - last_newline_index
        return line_number, column_number

    def open_debugger(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Debug is disabled.')
            return
        code_to_run = self.source_text.get('1.0', 'end-1c')
        if not code_to_run.strip():
            self.status_label.config(text='No source to debug')
            return
        self.application.event_queue.publish('RunTabDebugRun', log_context={'code': code_to_run})
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Debugging source...')
        try:
            try:
                result = self.gemstone_session_record.run_code(code_to_run)
                self.on_run_complete(result)
                self.status_label.config(
                    text='Completed successfully; no debugger context',
                )
                self.application.event_queue.publish('RunTabDebugSucceeded', log_context={
                    'code': code_to_run,
                    'result': result.asString().to_py,
                })
                return
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                self.application.event_queue.publish('RunTabDebugFailed', log_context={
                    'code': code_to_run,
                    'error': str(domain_exception),
                })
                return
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                if self.is_compile_error(gemstone_exception):
                    self.application.event_queue.publish('RunTabDebugFailed', log_context={
                        'code': code_to_run,
                        'error': str(gemstone_exception),
                    })
                    return
                self.application.open_debugger(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def is_compile_error(self, exception):
        error_number = None
        try:
            error_number = exception.number
        except (AttributeError, GemstoneError, TypeError):
            pass
        if error_number == 1001:
            return True

        error_text = str(exception).lower()
        return 'compileerror' in error_text or 'compile error' in error_text

    def close_tab(self):
        self.ui_context.invalidate()
        run_session_key = getattr(self, 'global_navigation_session_key', None)
        if run_session_key:
            self.application.mark_global_navigation_place_stale(
                ('run_session', run_session_key),
            )
        if self.application.run_tab is self:
            self.application.run_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()

    def destroy(self):
        self.ui_context.invalidate()
        self.application.event_queue.clear_subscribers(self)
        super().destroy()


class DebuggerWindow(ttk.PanedWindow):
    def __init__(
        self, parent, application, gemstone_session_record, event_queue, exception
    ):
        super().__init__(
            parent, orient=tk.VERTICAL
        )

        self.application = application
        self.exception = exception
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record

        self.call_stack_frame = ttk.Frame(self)
        self.code_panel_frame = ttk.Frame(self)
        self.explorer_frame = ttk.Frame(self)

        self.add(self.call_stack_frame, weight=1)
        self.add(self.code_panel_frame, weight=1)
        self.add(self.explorer_frame, weight=1)

        self.debugger_controls = DebuggerControls(
            self.call_stack_frame, self, self.event_queue
        )
        self.debugger_controls.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        self.close_button = self.debugger_controls.close_button

        self.listbox = ttk.Treeview(
            self.call_stack_frame,
            columns=('Level', 'Column1', 'Column2'),
            show='headings',
        )
        self.listbox.heading('Level', text='Level')
        self.listbox.heading('Column1', text='Class Name')
        self.listbox.heading('Column2', text='Method Name')
        self.listbox.grid(row=1, column=0, sticky='nsew')

        self.debug_session = GemstoneDebugSession(self.exception)
        self.stack_frames = self.debug_session.call_stack()

        self.listbox.bind('<ButtonRelease-1>', self.on_listbox_select)
        self.listbox.bind('<Double-1>', self.open_method_from_selected_frame)

        self.code_panel = CodePanel(self.code_panel_frame, application=application)
        self.code_panel.grid(row=0, column=0, sticky='nsew')

        self.call_stack_frame.columnconfigure(0, weight=1)
        self.call_stack_frame.rowconfigure(1, weight=1)

        self.code_panel_frame.columnconfigure(0, weight=1)
        self.code_panel_frame.rowconfigure(0, weight=1)

        self.explorer_frame.columnconfigure(0, weight=1)
        self.explorer_frame.rowconfigure(0, weight=1)

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.grid(row=0, column=0, sticky='nsew')

        self.refresh()

    @property
    def is_running(self):
        return bool(self.stack_frames)

    def refresh(self):
        for item in self.listbox.get_children():
            self.listbox.delete(item)

        for frame in self.stack_frames:
            iid = str(frame.level)
            self.listbox.insert(
                '',
                'end',
                iid=iid,
                values=(frame.level, frame.class_name, frame.method_name),
            )

        if self.stack_frames:
            first_frame = next(iter(self.stack_frames))
            first_iid = str(first_frame.level)
            self.listbox.selection_set(first_iid)
            self.listbox.focus(first_iid)
            self.code_panel.refresh(
                first_frame.method_source,
                mark=first_frame.step_point_offset,
            )
            self.refresh_explorer(first_frame)

    def refresh_explorer(self, frame):
        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        explorer = Explorer(
            self.explorer_frame,
            frame,
            values=dict([('self', frame.self)] + list(frame.vars.items())),
            root_tab_label='Context',
            external_inspect_action=self.application.open_inspector_for_object,
            graph_inspect_action=self.application.open_object_diagram_for_object,
        )
        self.explorer = explorer
        explorer.grid(row=0, column=0, sticky='nsew')

    def on_listbox_select(self, event):
        frame = self.get_selected_stack_frame()
        if frame:
            self.event_queue.publish('DebuggerFrameSelected', log_context={'frame_level': self.selected_frame_level()})
            self.code_panel.refresh(frame.method_source, mark=frame.step_point_offset)
            self.refresh_explorer(frame)

    def open_method_from_selected_frame(self, event):
        self.open_selected_frame_method()

    def stack_frame_for_level(self, level):
        for frame in self.stack_frames:
            if frame.level == level:
                return frame
        return None

    def get_selected_stack_frame(self):
        selected_items = self.listbox.selection()
        selected_item = None
        if selected_items:
            selected_item = selected_items[0]
        if selected_item is None:
            selected_item = self.listbox.focus()
        if selected_item:
            try:
                selected_level = int(selected_item)
            except ValueError:
                return None
            return self.stack_frame_for_level(selected_level)
        return None

    def value_for_named_local_on_frame(self, frame, variable_name):
        frame_vars = frame.vars
        if variable_name in frame_vars:
            return True, frame_vars[variable_name]
        return False, None

    def value_for_named_instance_variable_on_frame_self(self, frame, variable_name):
        frame_self = getattr(frame, 'self', None)
        if frame_self is None:
            return False, None
        inst_var_names = []
        try:
            inst_var_names = list(frame_self.gemstone_class().allInstVarNames())
        except (GemstoneError, AttributeError):
            return False, None
        for one_based_index, inst_var_name in enumerate(inst_var_names, start=1):
            candidate_name = ''
            try:
                candidate_name = inst_var_name.to_py
            except AttributeError:
                candidate_name = str(inst_var_name)
            names_match = candidate_name == variable_name
            if names_match:
                value = None
                value_found = False
                try:
                    value = frame_self.instVarNamed(inst_var_name)
                    value_found = True
                except GemstoneError:
                    pass
                if not value_found:
                    try:
                        value = frame_self.instVarAt(one_based_index)
                        value_found = True
                    except GemstoneError:
                        pass
                if value_found:
                    return True, value
        return False, None

    def value_for_source_expression(self, frame, source_expression):
        expression = source_expression.strip()
        if expression == 'self':
            return frame.self
        local_value_found, local_value = self.value_for_named_local_on_frame(
            frame,
            expression,
        )
        if local_value_found:
            return local_value
        instvar_value_found, instvar_value = (
            self.value_for_named_instance_variable_on_frame_self(
                frame,
                expression,
            )
        )
        if instvar_value_found:
            return instvar_value
        return frame.gemstone_session.execute(
            expression,
            context=frame.var_context,
        )

    def inspect_selected_source_expression(self, source_expression):
        expression = source_expression.strip()
        if not expression:
            messagebox.showwarning(
                'No Selection',
                'Select source text in the debugger method pane to inspect it.',
            )
            return
        frame = self.get_selected_stack_frame()
        if frame is None:
            messagebox.showwarning(
                'No Stack Frame',
                'Select a stack frame before inspecting source text.',
            )
            return
        try:
            inspected_object = self.value_for_source_expression(
                frame,
                expression,
            )
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Inspect Expression', str(error))
            return
        self.application.open_inspector_for_object(inspected_object)

    def show_selected_source_expression_in_object_diagram(self, source_expression):
        expression = source_expression.strip()
        if not expression:
            messagebox.showwarning(
                'No Selection',
                'Select source text in the debugger method pane to inspect it.',
            )
            return
        frame = self.get_selected_stack_frame()
        if frame is None:
            messagebox.showwarning(
                'No Stack Frame',
                'Select a stack frame before inspecting source text.',
            )
            return
        try:
            inspected_object = self.value_for_source_expression(
                frame,
                expression,
            )
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Inspect Expression', str(error))
            return
        self.application.open_object_diagram_for_object(inspected_object)

    def frame_method_context(self, frame):
        if frame is None:
            return None
        class_name = frame.class_name
        show_instance_side = True
        class_side_suffix = ' class'
        if class_name.endswith(class_side_suffix):
            class_name = class_name[: -len(class_side_suffix)]
            show_instance_side = False
        if not class_name or not frame.method_name:
            return None
        return class_name, show_instance_side, frame.method_name

    def open_selected_frame_method(self):
        frame = self.get_selected_stack_frame()
        method_context = self.frame_method_context(frame)
        if method_context is None:
            return
        class_name, show_instance_side, method_name = method_context
        try:
            self.application.handle_sender_selection(
                class_name,
                show_instance_side,
                method_name,
            )
            if self.application.browser_tab:
                self.application.notebook.select(self.application.browser_tab)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Browse Frame Method', str(error))

    def selected_frame_level(self):
        frame = self.get_selected_stack_frame()
        if frame:
            return frame.level
        return None

    def apply_debug_action_outcome(self, action_outcome):
        self.stack_frames = self.debug_session.call_stack()
        if action_outcome.has_completed:
            self.finish(action_outcome.result)
        else:
            self.refresh()

    def continue_running(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.continue_running()
            self.apply_debug_action_outcome(action_outcome)

    def step_over(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_over(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def step_into(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_into(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def step_through(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_through(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def restart_frame(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            outcome = self.debug_session.restart_frame(frame_level)
            self.apply_debug_action_outcome(outcome)

    def stop(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.stop()
            if action_outcome.has_completed:
                self.dismiss()
            else:
                self.stack_frames = self.debug_session.call_stack()
                self.refresh()

    def dismiss(self):
        self.stack_frames = None
        debugger_session_key = getattr(self, 'global_navigation_session_key', None)
        if debugger_session_key:
            self.application.mark_global_navigation_place_stale(
                ('debugger_session', debugger_session_key),
            )
        if self.application.debugger_tab is self:
            self.application.debugger_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()

    def finish(self, result):
        self.stack_frames = None

        self.forget(self.call_stack_frame)
        self.forget(self.code_panel_frame)
        self.forget(self.explorer_frame)

        self.finished_frame = ttk.Frame(self)
        self.finished_frame.columnconfigure(0, weight=1)
        self.finished_frame.rowconfigure(1, weight=1)
        self.add(self.finished_frame, weight=1)

        self.finished_actions = ttk.Frame(self.finished_frame)
        self.finished_actions.grid(row=0, column=0, sticky='ew', padx=5, pady=(5, 0))
        self.finished_actions.columnconfigure(0, weight=1)

        self.close_button = ttk.Button(
            self.finished_actions,
            text='Close',
            command=self.dismiss,
        )
        self.close_button.grid(row=0, column=1, sticky='e')

        self.result_text = tk.Text(self.finished_frame)
        self.result_text.insert('1.0', result.asString().to_py)
        self.result_text.grid(row=1, column=0, sticky='nsew', padx=5, pady=(5, 5))


class DebuggerControls(ttk.Frame):
    def __init__(self, parent, debugger, event_queue):
        super().__init__(parent)
        self.debugger = debugger
        self.event_queue = event_queue

        self.continue_button = ttk.Button(
            self, text='Continue', command=self.handle_continue
        )
        self.continue_button.grid(row=0, column=0, padx=5, pady=5)

        self.over_button = ttk.Button(self, text='Over', command=self.handle_over)
        self.over_button.grid(row=0, column=1, padx=5, pady=5)

        self.into_button = ttk.Button(self, text='Into', command=self.handle_into)
        self.into_button.grid(row=0, column=2, padx=5, pady=5)

        self.through_button = ttk.Button(
            self, text='Through', command=self.handle_through
        )
        self.through_button.grid(row=0, column=3, padx=5, pady=5)

        self.restart_button = ttk.Button(
            self, text='Restart', command=self.handle_restart
        )
        self.restart_button.grid(row=0, column=4, padx=5, pady=5)

        self.stop_button = ttk.Button(self, text='Stop', command=self.handle_stop)
        self.stop_button.grid(row=0, column=5, padx=5, pady=5)

        self.browse_button = ttk.Button(
            self,
            text='Browse Method',
            command=self.handle_browse,
        )
        self.browse_button.grid(row=0, column=6, padx=5, pady=5)

        self.columnconfigure(7, weight=1)
        self.close_button = ttk.Button(
            self,
            text='Close',
            command=self.handle_close,
        )
        self.close_button.grid(row=0, column=8, padx=5, pady=5, sticky='e')

    def handle_continue(self):
        self.event_queue.publish('DebuggerContinued')
        self.debugger.continue_running()

    def handle_over(self):
        self.event_queue.publish('DebuggerSteppedOver')
        self.debugger.step_over()

    def handle_into(self):
        self.event_queue.publish('DebuggerSteppedInto')
        self.debugger.step_into()

    def handle_through(self):
        self.event_queue.publish('DebuggerSteppedThrough')
        self.debugger.step_through()

    def handle_restart(self):
        self.event_queue.publish('DebuggerFrameRestarted')
        self.debugger.restart_frame()

    def handle_stop(self):
        self.event_queue.publish('DebuggerStopped')
        self.debugger.stop()

    def handle_browse(self):
        self.event_queue.publish('DebuggerBrowsed')
        self.debugger.open_selected_frame_method()

    def handle_close(self):
        self.event_queue.publish('DebuggerClosed')
        self.debugger.dismiss()
