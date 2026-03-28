import tkinter as tk
import tkinter.messagebox as messagebox
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.navigation import NavigationHistory
from reahl.swordfish.tab_registry import DeduplicatedTabRegistry
from reahl.swordfish.ui_support import add_close_command_to_popup_menu, popup_menu


class ObjectInspector(ttk.Frame):
    def __init__(
        self,
        parent,
        an_object=None,
        values=None,
        external_inspect_action=None,
        graph_inspect_action=None,
        browse_class_action=None,
        event_queue=None,
    ):
        super().__init__(parent)
        self.inspected_object = an_object
        self.external_inspect_action = external_inspect_action
        self.graph_inspect_action = graph_inspect_action
        self.browse_class_action = browse_class_action
        self.event_queue = event_queue
        self.current_object_menu = None
        self.page_size = 100
        self.current_page = 0
        self.total_items = 0
        self.pagination_mode = None
        self.dictionary_keys = []
        self.set_as_array = None
        self.actual_values = []
        self.treeview_heading = 'Name'

        self.treeview = ttk.Treeview(
            self, columns=('Name', 'Class', 'Value'), show='headings'
        )
        self.treeview.heading('Name', text='Name')
        self.treeview.heading('Class', text='Class')
        self.treeview.heading('Value', text='Value')
        self.treeview.grid(row=0, column=0, sticky='nsew')

        self.footer = ttk.Frame(self)
        self.footer.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        self.status_label = ttk.Label(self.footer, text='')
        self.status_label.grid(row=0, column=0, sticky='w')
        self.previous_button = ttk.Button(
            self.footer, text='Previous', command=self.on_previous_page
        )
        self.previous_button.grid(row=0, column=1, padx=(8, 0))
        self.next_button = ttk.Button(
            self.footer, text='Next', command=self.on_next_page
        )
        self.next_button.grid(row=0, column=2, padx=(4, 0))
        self.browse_class_button = ttk.Button(
            self.footer,
            text='Browse Class',
            command=self.browse_inspected_object_class,
        )
        self.browse_class_button.grid(row=0, column=3, padx=(8, 0))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.footer.columnconfigure(0, weight=1)

        if values is not None:
            self.pagination_mode = None
            self.load_rows(list(values.items()), 'Name', len(values))
        else:
            self.inspect_object(an_object)

        self.treeview.bind('<Double-1>', self.on_item_double_click)
        self.treeview.bind('<Button-3>', self.open_object_menu)
        self.treeview.bind('<Button-1>', self.close_object_menu, add='+')
        browse_class_state = tk.NORMAL
        if self.browse_class_action is None or self.inspected_object is None:
            browse_class_state = tk.DISABLED
        self.browse_class_button.configure(state=browse_class_state)

    def class_name_of(self, an_object):
        class_name = 'Unknown'
        if an_object is not None:
            try:
                class_name_candidate = an_object.gemstone_class().asString().to_py
                normalized_class_name = self.normalized_text(class_name_candidate)
                if normalized_class_name:
                    class_name = normalized_class_name
            except GemstoneError:
                pass
        return class_name

    def normalized_text(self, text_value):
        if isinstance(text_value, str):
            return ' '.join(text_value.split())
        return ''

    def string_value_via_as_string(self, an_object):
        if an_object is None:
            return ''
        try:
            return self.normalized_text(an_object.asString().to_py)
        except GemstoneError:
            return ''

    def string_value_via_print_string(self, an_object):
        if an_object is None:
            return ''
        try:
            return self.normalized_text(an_object.printString().to_py)
        except GemstoneError:
            return ''

    def oop_label_of(self, an_object):
        if an_object is None:
            return ''
        oop_label = ''
        try:
            oop_value = an_object.oop
            if isinstance(oop_value, int):
                oop_label = str(oop_value)
            if isinstance(oop_value, str):
                oop_label = oop_value.strip()
        except (GemstoneError, AttributeError):
            pass
        return oop_label

    def value_label(self, an_object):
        label = '<unavailable>'
        if an_object is not None:
            as_string_value = self.string_value_via_as_string(an_object)
            if as_string_value:
                label = as_string_value
            if not as_string_value:
                print_string_value = self.string_value_via_print_string(an_object)
                if print_string_value:
                    label = print_string_value
            if label == '<unavailable>':
                label = f'<{self.class_name_of(an_object)}>'
        return label

    def tab_label_for(self, an_object):
        if an_object is None:
            return 'Context'

        class_name = self.class_name_of(an_object)
        value = self.value_label(an_object)
        value_placeholder = f'<{class_name}>'
        include_value = value not in ('<unavailable>', value_placeholder, class_name)

        tab_label = class_name
        if include_value:
            tab_label = f'{class_name} {value}'

        oop_label = self.oop_label_of(an_object)
        if oop_label:
            tab_label = f'{oop_label}:{tab_label}'
        return tab_label

    def class_name_has_dictionary_semantics(self, class_name):
        dictionary_markers = ('Dictionary', 'KeyValue')
        return any(marker in class_name for marker in dictionary_markers)

    def class_name_has_indexed_collection_semantics(self, class_name):
        indexed_markers = (
            'Array',
            'OrderedCollection',
            'SortedCollection',
            'SequenceableCollection',
            'List',
        )
        return any(marker in class_name for marker in indexed_markers)

    def class_name_has_set_semantics(self, class_name):
        set_markers = ('Set', 'Bag')
        return any(marker in class_name for marker in set_markers)

    def configure_set_rows(self, an_object):
        try:
            self.set_as_array = an_object.asArray()
        except GemstoneError:
            return False
        try:
            total_items = self.set_as_array.size().to_py
        except GemstoneError:
            return False
        if type(total_items) is not int:
            return False
        self.pagination_mode = 'set'
        self.current_page = 0
        self.total_items = total_items
        self.treeview_heading = 'Element'
        self.refresh_rows_for_current_page()
        return True

    def set_rows_for_range(self, start_index, end_index):
        rows = []
        for one_based_index in range(start_index + 1, end_index + 1):
            value_found = False
            value = None
            try:
                value = self.set_as_array.at(one_based_index)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((f'[{one_based_index}]', value))
        return rows

    def inspect_object(self, an_object):
        if an_object is None:
            self.pagination_mode = None
            self.load_rows([], 'Name', 0)
            return

        try:
            is_class = an_object.isBehavior().to_py
        except GemstoneError:
            is_class = False

        if is_class:
            self.pagination_mode = None
            inspected_values = self.inspect_class(an_object)
            self.load_rows(
                list(inspected_values.items()), 'Name', len(inspected_values)
            )
            return

        class_name = self.class_name_of(an_object)
        dictionary_is_configured = False
        if self.class_name_has_dictionary_semantics(class_name):
            dictionary_is_configured = self.configure_dictionary_rows(an_object)
        if dictionary_is_configured:
            return

        indexed_collection_is_configured = False
        if self.class_name_has_indexed_collection_semantics(class_name):
            indexed_collection_is_configured = self.configure_indexed_collection_rows(
                an_object
            )
        if indexed_collection_is_configured:
            return

        set_is_configured = False
        if self.class_name_has_set_semantics(class_name):
            set_is_configured = self.configure_set_rows(an_object)
        if set_is_configured:
            return

        self.pagination_mode = None
        inspected_values = self.inspect_instance(an_object)
        self.load_rows(list(inspected_values.items()), 'Name', len(inspected_values))

    def configure_dictionary_rows(self, an_object):
        try:
            self.dictionary_keys = list(an_object.keys())
        except GemstoneError:
            return False

        self.pagination_mode = 'dictionary'
        self.current_page = 0
        self.total_items = len(self.dictionary_keys)
        self.treeview_heading = 'Key'
        self.refresh_rows_for_current_page()
        return True

    def configure_indexed_collection_rows(self, an_object):
        try:
            total_items = an_object.size().to_py
        except GemstoneError:
            return False
        if type(total_items) is not int:
            return False

        can_access_index_one = True
        if total_items > 0:
            try:
                an_object.at(1)
            except GemstoneError:
                can_access_index_one = False
        if not can_access_index_one:
            return False

        self.pagination_mode = 'indexed'
        self.current_page = 0
        self.total_items = total_items
        self.treeview_heading = 'Index'
        self.refresh_rows_for_current_page()
        return True

    def row_range_for_current_page(self):
        if self.total_items < 1:
            return 0, 0

        start_index = self.current_page * self.page_size
        end_index = start_index + self.page_size
        if end_index > self.total_items:
            end_index = self.total_items
        return start_index, end_index

    def dictionary_rows_for_range(self, start_index, end_index):
        rows = []
        for key in self.dictionary_keys[start_index:end_index]:
            value_found = False
            value = None
            try:
                value = self.inspected_object.at(key)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((self.value_label(key), value))
        return rows

    def indexed_rows_for_range(self, start_index, end_index):
        rows = []
        for one_based_index in range(start_index + 1, end_index + 1):
            value_found = False
            value = None
            try:
                value = self.inspected_object.at(one_based_index)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((f'[{one_based_index}]', value))
        return rows

    def refresh_rows_for_current_page(self):
        start_index, end_index = self.row_range_for_current_page()
        rows = []
        if self.pagination_mode == 'dictionary':
            rows = self.dictionary_rows_for_range(start_index, end_index)
        if self.pagination_mode == 'indexed':
            rows = self.indexed_rows_for_range(start_index, end_index)
        if self.pagination_mode == 'set':
            rows = self.set_rows_for_range(start_index, end_index)
        self.load_rows(rows, self.treeview_heading, self.total_items)

    def inspect_instance(self, an_object):
        # AI: Regular instances expose their instance variables via instVarNamed:.
        values = {}
        for i, instvar_name in enumerate(
            an_object.gemstone_class().allInstVarNames(), start=1
        ):
            try:
                values[instvar_name.to_py] = an_object.instVarNamed(instvar_name)
            except GemstoneError:
                try:
                    # AI: Fall back to indexed access for objects that understand instVarAt:
                    # but not instVarNamed: (e.g. VariableContext, some built-in types).
                    values[instvar_name.to_py] = an_object.instVarAt(i)
                except GemstoneError:
                    pass
        return values

    def inspect_class(self, an_object):
        # AI: For class objects, show class variables (shared among all instances)
        # and any class-side instance variables.
        values = {}
        try:
            class_pool = an_object.classPool()
            for key in class_pool.keys():
                try:
                    values[key.to_py] = class_pool.at(key)
                except GemstoneError:
                    pass
        except (GemstoneError, AttributeError):
            pass
        for i, instvar_name in enumerate(
            an_object.gemstone_class().allInstVarNames(), start=1
        ):
            try:
                values[instvar_name.to_py] = an_object.instVarAt(i)
            except GemstoneError:
                pass
        return values

    def load_rows(self, rows, first_column_title, total_items):
        self.treeview_heading = first_column_title
        self.total_items = total_items
        self.treeview.heading('Name', text=self.treeview_heading)

        for existing_item in self.treeview.get_children():
            self.treeview.delete(existing_item)
        self.actual_values = []

        for row_name, row_value in rows:
            self.treeview.insert(
                '',
                'end',
                values=(
                    row_name,
                    self.class_name_of(row_value),
                    self.value_label(row_value),
                ),
            )
            self.actual_values.append(row_value)

        self.update_footer()

    def update_footer(self):
        start_index, end_index = self.row_range_for_current_page()
        show_page_window = (
            self.pagination_mode in ('dictionary', 'indexed')
            and self.total_items > self.page_size
        )
        if show_page_window:
            self.status_label.configure(
                text=f'Items {start_index + 1}-{end_index} of {self.total_items}'
            )
        if not show_page_window:
            if self.total_items == 1:
                self.status_label.configure(text='1 item')
            if self.total_items != 1:
                self.status_label.configure(text=f'{self.total_items} items')

        self.previous_button.configure(state=tk.DISABLED)
        self.next_button.configure(state=tk.DISABLED)
        if show_page_window:
            if self.current_page > 0:
                self.previous_button.configure(state=tk.NORMAL)
            if end_index < self.total_items:
                self.next_button.configure(state=tk.NORMAL)

    def on_previous_page(self):
        can_page_backwards = (
            self.pagination_mode in ('dictionary', 'indexed') and self.current_page > 0
        )
        if can_page_backwards:
            self.current_page -= 1
            self.refresh_rows_for_current_page()

    def on_next_page(self):
        start_index, end_index = self.row_range_for_current_page()
        can_page_forwards = (
            self.pagination_mode in ('dictionary', 'indexed')
            and end_index < self.total_items
        )
        if can_page_forwards:
            self.current_page += 1
            self.refresh_rows_for_current_page()

    def on_item_double_click(self, event):
        value = self.selected_row_value()
        if value is None:
            return

        if self.event_queue is not None:
            self.event_queue.publish('ObjectInspected', log_context={'label': self.tab_label_for(value)})

        if hasattr(self.master, 'open_or_select_object'):
            self.master.open_or_select_object(value)
            return

        tab_label = self.tab_label_for(value)
        try:
            new_tab = ObjectInspector(
                self.master,
                an_object=value,
                external_inspect_action=self.external_inspect_action,
                graph_inspect_action=self.graph_inspect_action,
                event_queue=self.event_queue,
            )
        except GemstoneError as e:
            messagebox.showerror('Inspector', f'Cannot inspect this object:\n{e}')
            return
        self.master.add(new_tab, text=tab_label)
        self.master.select(new_tab)

    def selected_row_value(self):
        selected_item = self.treeview.focus()
        if not selected_item:
            return None
        index = self.treeview.index(selected_item)
        if index < len(self.actual_values):
            return self.actual_values[index]
        return None

    def select_row_at_coordinates(self, event):
        selected_item = self.treeview.identify_row(event.y)
        if selected_item:
            self.treeview.focus(selected_item)
            self.treeview.selection_set(selected_item)

    def inspect_selected_row_in_external_inspector(self):
        if self.external_inspect_action is None:
            return
        value = self.selected_row_value()
        if value is None:
            return
        self.external_inspect_action(value)

    def show_selected_row_in_object_diagram(self):
        if self.graph_inspect_action is None:
            return
        value = self.selected_row_value()
        if value is None:
            return
        self.graph_inspect_action(value)

    def browse_inspected_object_class(self):
        if self.browse_class_action is None:
            return
        if self.inspected_object is None:
            return
        self.browse_class_action(self.inspected_object)

    def open_object_menu(self, event):
        self.close_object_menu()
        self.select_row_at_coordinates(event)
        selected_value = self.selected_row_value()
        if selected_value is None:
            return
        object_menu = tk.Menu(self, tearoff=0)
        if self.external_inspect_action is not None:
            object_menu.add_command(
                label='Inspect',
                command=self.inspect_selected_row_in_external_inspector,
            )
        if self.graph_inspect_action is not None:
            object_menu.add_command(
                label='Show in Object Diagram',
                command=self.show_selected_row_in_object_diagram,
            )
        has_menu_entries = object_menu.index('end') is not None
        if not has_menu_entries:
            return
        add_close_command_to_popup_menu(object_menu)
        self.current_object_menu = object_menu
        popup_menu(object_menu, event)

    def close_object_menu(self, event=None):
        if self.current_object_menu is None:
            return
        self.current_object_menu.destroy()
        self.current_object_menu = None


class Explorer(ttk.Notebook):
    def __init__(
        self,
        parent,
        an_object=None,
        values=None,
        root_tab_label=None,
        external_inspect_action=None,
        graph_inspect_action=None,
        browse_class_action=None,
        event_queue=None,
    ):
        super().__init__(parent)
        self.tab_registry = DeduplicatedTabRegistry(self)
        self.external_inspect_action = external_inspect_action
        self.graph_inspect_action = graph_inspect_action
        self.browse_class_action = browse_class_action
        self.event_queue = event_queue

        context_frame = ObjectInspector(
            self,
            an_object=an_object,
            values=values,
            external_inspect_action=self.external_inspect_action,
            graph_inspect_action=self.graph_inspect_action,
            browse_class_action=self.browse_class_action,
            event_queue=self.event_queue,
        )
        tab_label = root_tab_label
        if tab_label is None:
            tab_label = context_frame.tab_label_for(an_object)
        self.add(context_frame, text=tab_label)
        context_key = None
        if values is not None and an_object is None:
            context_key = ('context', str(id(context_frame)))
        self.register_object_tab(
            context_frame, an_object, tab_label, object_key=context_key
        )

    def object_key_for(self, an_object):
        if an_object is None:
            return ('none',)

        oop_label = ''
        try:
            oop_value = an_object.oop
            if isinstance(oop_value, int):
                oop_label = str(oop_value)
            if isinstance(oop_value, str):
                oop_label = oop_value.strip()
        except (GemstoneError, AttributeError):
            pass

        if oop_label:
            return ('oop', oop_label)
        return ('identity', str(id(an_object)))

    def register_object_tab(self, tab_widget, an_object, tab_label, object_key=None):
        if object_key is None:
            object_key = self.object_key_for(an_object)
        self.tab_registry.register_tab(object_key, tab_widget, tab_label)
        return object_key

    def open_or_select_object(self, an_object):
        object_key = self.object_key_for(an_object)
        if self.tab_registry.select_key(object_key):
            return

        try:
            new_tab = ObjectInspector(
                self,
                an_object=an_object,
                external_inspect_action=self.external_inspect_action,
                graph_inspect_action=self.graph_inspect_action,
                browse_class_action=self.browse_class_action,
            )
        except GemstoneError as e:
            messagebox.showerror('Inspector', f'Cannot inspect this object:\n{e}')
            return
        tab_label = new_tab.tab_label_for(an_object)
        self.add(new_tab, text=tab_label)
        self.register_object_tab(new_tab, an_object, tab_label, object_key=object_key)
        self.select(new_tab)

    def selected_object_key(self):
        return self.tab_registry.selected_key()

    def select_object_key(self, object_key):
        return self.tab_registry.select_key(object_key)

    def label_for_object_key(self, object_key):
        return self.tab_registry.label_for_key(object_key)


class InspectorTab(ttk.Frame):
    def __init__(
        self,
        parent,
        application,
        an_object=None,
        graph_inspect_action=None,
    ):
        super().__init__(parent)
        self.application = application
        self.object_navigation_history = NavigationHistory()
        self.history_choice_indices = []
        self.navigation_selection_in_progress = False

        self.actions_frame = ttk.Frame(self)
        self.actions_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 5))
        self.actions_frame.columnconfigure(4, weight=1)

        self.title_label = ttk.Label(self.actions_frame, text='Inspector')
        self.title_label.grid(row=0, column=0, sticky='w')

        self.back_button = ttk.Button(
            self.actions_frame,
            text='Back',
            command=self.go_to_previous_object,
        )
        self.back_button.grid(row=0, column=1, padx=(6, 0))

        self.forward_button = ttk.Button(
            self.actions_frame,
            text='Forward',
            command=self.go_to_next_object,
        )
        self.forward_button.grid(row=0, column=2, padx=(4, 0))

        self.history_combobox = ttk.Combobox(
            self.actions_frame,
            state='readonly',
            width=44,
        )
        self.history_combobox.grid(row=0, column=3, padx=(6, 0), sticky='e')
        self.history_combobox.bind(
            '<<ComboboxSelected>>',
            self.jump_to_selected_history_entry,
        )

        self.close_button = ttk.Button(
            self.actions_frame,
            text='Close',
            command=self.application.close_inspector_tab,
        )
        self.close_button.grid(row=0, column=5, sticky='e')

        self.explorer = Explorer(
            self,
            an_object=an_object,
            graph_inspect_action=graph_inspect_action,
            browse_class_action=self.application.browse_object_class,
            event_queue=self.application.event_queue,
        )
        self.explorer.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))
        self.explorer.bind(
            '<<NotebookTabChanged>>',
            self.handle_explorer_tab_changed,
        )

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.record_object_navigation()

    def current_object_context(self):
        return self.explorer.selected_object_key()

    def object_context_label(self, object_context):
        return self.explorer.label_for_object_key(object_context)

    def record_object_navigation(self):
        self.object_navigation_history.record(self.current_object_context())
        self.refresh_navigation_controls()

    def refresh_navigation_controls(self):
        back_button_state = (
            tk.NORMAL if self.object_navigation_history.can_go_back() else tk.DISABLED
        )
        self.back_button.configure(state=back_button_state)

        forward_button_state = (
            tk.NORMAL
            if self.object_navigation_history.can_go_forward()
            else tk.DISABLED
        )
        self.forward_button.configure(state=forward_button_state)

        history_entries = self.object_navigation_history.entries_with_current_marker()
        self.history_choice_indices = []
        history_labels = []
        for history_entry in reversed(history_entries):
            history_index = history_entry['history_index']
            object_context = history_entry['entry']
            history_labels.append(self.object_context_label(object_context))
            self.history_choice_indices.append(history_index)
        self.history_combobox['values'] = history_labels

        if len(history_labels) > 0:
            current_history_index = self.object_navigation_history.current_index
            selected_index = len(history_labels) - current_history_index - 1
            self.history_combobox.current(selected_index)
        if len(history_labels) == 0:
            self.history_combobox.set('')

    def jump_to_object_context(self, object_context):
        if object_context is None:
            self.refresh_navigation_controls()
            return
        if object_context == self.current_object_context():
            self.refresh_navigation_controls()
            return
        self.navigation_selection_in_progress = True
        selected = self.explorer.select_object_key(object_context)
        if not selected:
            self.navigation_selection_in_progress = False
        self.refresh_navigation_controls()

    def go_to_previous_object(self):
        self.application.event_queue.publish('InspectorNavigatedBack')
        object_context = self.object_navigation_history.go_back()
        self.jump_to_object_context(object_context)

    def go_to_next_object(self):
        self.application.event_queue.publish('InspectorNavigatedForward')
        object_context = self.object_navigation_history.go_forward()
        self.jump_to_object_context(object_context)

    def jump_to_selected_history_entry(self, event):
        combobox_index = self.history_combobox.current()
        if combobox_index < 0:
            return
        if combobox_index >= len(self.history_choice_indices):
            return
        history_index = self.history_choice_indices[combobox_index]
        object_context = self.object_navigation_history.jump_to(history_index)
        self.jump_to_object_context(object_context)

    def handle_explorer_tab_changed(self, event=None):
        if self.navigation_selection_in_progress:
            self.navigation_selection_in_progress = False
            self.refresh_navigation_controls()
            return
        self.record_object_navigation()
