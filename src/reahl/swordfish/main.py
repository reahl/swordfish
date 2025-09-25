#!/var/local/gemstone/venv/wonka/bin/python

import contextlib
import logging
import re
import tkinter as tk
import tkinter.messagebox as messagebox
import weakref
from tkinter import ttk

from reahl.ptongue import GemstoneError, LinkedSession, RPCSession


class DomainException(Exception):
    pass

class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.selected_package = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.show_instance_side = True

    def select_package(self, package):
        self.selected_package = package
        self.select_class(None)
        
    def select_instance_side(self, show_instance_side):
        self.show_instance_side = show_instance_side

    def select_class(self, selected_class):
        self.selected_class = selected_class
        self.select_method_category(None)

    def select_method_category(self, selected_method_category):
        self.selected_method_category = selected_method_category
        self.select_method_symbol(None)
        
    def select_method_symbol(self, selected_method_symbol):
        self.selected_method_symbol = selected_method_symbol

    def commit(self):
        self.gemstone_session.commit()
        
    def abort(self):
        self.gemstone_session.abort()
        
    @classmethod
    def log_in_rpc(cls, gemstone_user_name, gemstone_password, rpc_hostname, stone_name, netldi_name):
        nrs_string = f'!@{rpc_hostname}#netldi:{netldi_name}!gemnetobject'
        logging.getLogger(__name__).debug(f'Logging in with: {gemstone_user_name} stone_name={stone_name} netldi_task={nrs_string}')
        try:
            gemstone_session = RPCSession(gemstone_user_name, gemstone_password, stone_name=stone_name, netldi_task=nrs_string)
        except GemstoneError as e:
            raise DomainException('Gemstone error: %s' % e)
        return cls(gemstone_session)

    @classmethod
    def log_in_linked(cls, gemstone_user_name, gemstone_password, stone_name):
        logging.getLogger(__name__).debug(f'Logging in with: {gemstone_user_name} stone_name={stone_name}')
        try:
            gemstone_session = LinkedSession(gemstone_user_name, gemstone_password, stone_name=stone_name)
        except GemstoneError as e:
            raise DomainException('Gemstone error: %s' % e)
        return cls(gemstone_session)
    
    @property
    def stone_name(self):
        return self.gemstone_session.System.stoneName().to_py

    @property
    def host_name(self):
        return self.gemstone_session.System.hostname().to_py
    
    @property
    def user_name(self):
        return self.gemstone_session.System.myUserProfile().userId().to_py

    @property
    def session_id(self):
        # self.gemstone_session.System.session() returns our self.gemstone_session itself, not the id we want
        return self.gemstone_session.execute('System session').to_py        

    def __str__(self):
        return f'{self.session_id}: {self.user_name} on {self.stone_name} at server {self.host_name}'

    def log_out(self):
        self.gemstone_session.log_out()

    @property
    def class_organizer(self):
        return self.gemstone_session.ClassOrganizer.new()

    @property
    def class_categories(self):
        yield from [i.to_py for i in self.class_organizer.categories().keys().asSortedCollection()]
        
    def get_classes_in_category(self, category):
        if not category:
            return
        yield from [i.name().to_py for i in self.class_organizer.categories().at(category)]
        
    def get_categories_in_class(self, class_name, show_instance_side):
        if not class_name:
            return
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        class_to_query = gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        yield from [i.to_py for i in class_to_query.categoryNames().asSortedCollection()]

    def get_selectors_in_class(self, class_name, method_category, show_instance_side):
        if not class_name or not method_category:
            return
        
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        class_to_query = gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        try:
            if method_category == 'all':
                selectors = class_to_query.selectors().asSortedCollection()
            else:
                selectors = class_to_query.selectorsIn(method_category).asSortedCollection()
                
        except GemstoneError:
            return
        
        yield from [i.to_py for i in selectors]

    def get_method(self, class_name, show_instance_side, method_symbol):
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        class_to_query = gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        try:
            return class_to_query.compiledMethodAt(method_symbol)
        except GemstoneError:
            return

    def jump_to_class(self, class_name, show_instance_side):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_package = selected_gemstone_class.category().to_py
        self.select_package(selected_package)
        self.select_instance_side(show_instance_side)
        self.select_class(class_name)
        
    def jump_to_method(self, class_name, show_instance_side, method_symbol):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_package = selected_gemstone_class.category().to_py
        class_to_query = selected_gemstone_class if show_instance_side else selected_gemstone_class.gemstone_class()
        selected_method_category = class_to_query.categoryOfSelector(method_symbol).to_py
        self.select_package(selected_package)
        self.select_class(class_name)
        self.select_instance_side(show_instance_side)
        self.select_method_category(selected_method_category)
        self.select_method_symbol(method_symbol)
        
    def get_current_methods(self):
        return list(self.get_selectors_in_class(self.selected_class, self.selected_method_category, self.show_instance_side))
        
    def find_class_names_matching(self, search_input):
        pattern = re.compile(search_input, re.IGNORECASE)
        yield from [name for i in self.class_organizer.classNames() if pattern.search(name := i.value().to_py)]
        
    def find_selectors_matching(self, search_input):
        # Uses object browser code....
        yield from [gemstone_selector.to_py for gemstone_selector in  self.gemstone_session.Symbol.selectorsContaining(search_input)]

    def find_implementors_of_method(self, method_name):
        yield from [(gemstone_method.classSymbol().to_py, gemstone_method.classIsMeta().to_py) for gemstone_method in  self.gemstone_session.SystemNavigation.default().allImplementorsOf(method_name)]
        
    def update_method_source(self, selected_class, show_instance_side, method_symbol, source):
        gemstone_class = self.gemstone_session.resolve_symbol(selected_class)
        class_to_query = gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        class_to_query.compile(source)

    def run_code(self, source):
        return self.gemstone_session.execute(source)
    # except GemstoneError as e:
    #     try:
    #         e.context.gciStepOverFromLevel(1)
    #     except GemstoneError as ex:
    #         result = ex.continue_with()
    
        
    
class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = []
        self.root.bind('<<CustomEventsPublished>>', self.process_events)

    def subscribe(self, event_name, callback, *args):
        self.events.setdefault(event_name, [])
        self.events[event_name].append((weakref.WeakMethod(callback), args))

    def publish(self, event_name, *args, **kwargs):
        if event_name in self.events:
            self.queue.append((event_name, args, kwargs))
        self.root.event_generate('<<CustomEventsPublished>>')

    def process_events(self, event):
        while self.queue:
            event_name, args, kwargs = self.queue.pop(0)
            if event_name in self.events:
                logging.getLogger(__name__).debug(f'Processing: {event_name}')
                for weak_callback, callback_args in self.events[event_name]:
                    callback = weak_callback()
                    if callback is not None:
                        logging.getLogger(__name__).debug(f'Calling: {callback}')
                        callback(*callback_args, *args, **kwargs)
                    
    def clear_subscribers(self, owner):
        for event_name, registered_callbacks in self.events.copy().items():
            cleaned_callbacks = [(weak_callback, callback_args) for (weak_callback, callback_args) in registered_callbacks
                                 if weak_callback().__self__ is not owner]
            self.events[event_name] = cleaned_callbacks


class MainMenu(tk.Menu):
    def __init__(self, parent, event_queue, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.event_queue = event_queue
        self.file_menu = tk.Menu(self, tearoff=0)
        self.session_menu = tk.Menu(self, tearoff=0)

        self._create_menus()
        self._subscribe_events()

    def _create_menus(self):
        # File Menu
        self.add_cascade(label="File", menu=self.file_menu)
        self.update_file_menu()

        # Session Menu
        self.add_cascade(label="Session", menu=self.session_menu)
        self.update_session_menu()

    def _subscribe_events(self):
        self.event_queue.subscribe('LoggedInSuccessfully', self.update_menus)
        self.event_queue.subscribe('LoggedOut', self.update_menus)

    def update_menus(self, gemstone_session_record=None):
        self.update_session_menu()
        self.update_file_menu()
        
    def update_session_menu(self):
        self.session_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            self.session_menu.add_command(label="Commit", command=self.parent.commit)
            self.session_menu.add_command(label="Abort", command=self.parent.abort)
            self.session_menu.add_command(label="Logout", command=self.parent.logout)
        else:
            self.session_menu.add_command(label="Login", command=self.parent.show_login_screen)
            
    def update_file_menu(self):
        self.file_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            self.file_menu.add_command(label="Find", command=self.show_find_dialog)
            self.file_menu.add_command(label="Implementors", command=self.show_implementors_dialog)
            self.file_menu.add_command(label="Run", command=self.show_run_dialog)
            self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

    def show_find_dialog(self):
        self.parent.open_find_dialog()
        
    def show_implementors_dialog(self):
        self.parent.open_implementors_dialog()

    def show_run_dialog(self):
        self.parent.run_code()


class FindDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Find")
        self.geometry("300x400")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Radio buttons for search type
        self.search_type = tk.StringVar(value="class")
        ttk.Label(self, text="Search Type:").grid(row=0, column=0, padx=10, pady=5, sticky='w')
        self.class_radio = ttk.Radiobutton(self, text="Class", variable=self.search_type, value="class")
        self.class_radio.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        self.method_radio = ttk.Radiobutton(self, text="Method", variable=self.search_type, value="method")
        self.method_radio.grid(row=0, column=2, padx=5, pady=5, sticky='w')

        # Find entry
        ttk.Label(self, text="Find what:").grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.find_entry = ttk.Entry(self)
        self.find_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky='ew')

        # Buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.find_button = ttk.Button(self.button_frame, text="Find", command=self.find_text)
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=5)

        # Listbox for results
        self.results_listbox = tk.Listbox(self)
        self.results_listbox.grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky='nsew')
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record
    
    def find_text(self):
        self.results_listbox.grid()

        # Simulate search results based on the search type and query
        search_query = self.find_entry.get()
        search_type = self.search_type.get()
        results = []

        if search_query:
            if search_type == "class":
                # Simulate finding classes
                results = self.gemstone_session_record.find_class_names_matching(search_query)
            elif search_type == "method":
                results = self.gemstone_session_record.find_selectors_matching(search_query)

        # Display results in the listbox
        self.results_listbox.delete(0, tk.END)
        for result in results:
            self.results_listbox.insert(tk.END, result)

        self.results_listbox.grid()  # Show the listbox

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_text = self.results_listbox.get(selected_index)
            search_type = self.search_type.get()
            parent = self.parent
            self.destroy()
            if search_type == 'class':
                parent.handle_find_selection(search_type == 'class', selected_text)
            else:
                parent.open_implementors_dialog(method_symbol=selected_text)
        except IndexError:
            pass


class ImplementorsDialog(tk.Toplevel):
    def __init__(self, parent, method_name=None):
        super().__init__(parent)
        self.title("Implementors")
        self.geometry("400x500")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent

        # Configure grid for proper resizing
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Method name entry
        ttk.Label(self, text="Method Name:").grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.method_entry = ttk.Entry(self)
        self.method_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky='ew')
        if method_name:
            self.method_entry.insert(0, method_name)

        # Buttons frame
        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=1, column=0, columnspan=3, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.find_button = ttk.Button(self.button_frame, text="Find", command=self.find_implementors)
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=5)

        # Listbox for results
        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)
        self.results_listbox.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky='nsew')

        # Initialize with the implementors
        self.find_implementors()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def find_implementors(self):
        self.results_listbox.grid()  # Make listbox visible
        # Simulate search results for implementors of a method
        method_name = self.method_entry.get()
        results = []

        if method_name:
            results = self.gemstone_session_record.find_implementors_of_method(method_name)

        # Display results in the listbox
        self.results_listbox.delete(0, tk.END)
        for class_name, is_meta in results:
            method_type = " class" if is_meta else ""
            self.results_listbox.insert(tk.END, f"{class_name}{method_type}")

        self.results_listbox.grid()  # Show the listbox

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_text = self.results_listbox.get(selected_index)
            class_name, *rest = selected_text.split(' ', 1)
            is_instance_side = 'class' not in rest
            self.parent.handle_implementor_selection(self.method_entry.get(), class_name, is_instance_side)
            self.destroy()
        except IndexError:
            pass

        
class Swordfish(tk.Tk):
    def __init__(self):
        super().__init__()
        self.event_queue = EventQueue(self)
        self.title("Swordfish")
        self.geometry("800x600")
        
        self.notebook = None
        self.browser_tab = None
        self.debugger_tab = None
        
        self.gemstone_session_record = None

        self.event_queue.subscribe('LoggedInSuccessfully', self.show_main_app)
        self.event_queue.subscribe('LoggedOut', self.show_login_screen)
        
        self.create_menu()
        self.show_login_screen()

    @property
    def is_logged_in(self):
        return self.gemstone_session_record is not None
    
    def create_menu(self):
        self.menu_bar = MainMenu(self, self.event_queue)
        self.config(menu=self.menu_bar)

    def commit(self):
        self.gemstone_session_record.commit()
        self.event_queue.publish('Committed')
        
    def abort(self):
        self.gemstone_session_record.abort()
        self.event_queue.publish('Aborted')
        
    def logout(self):
        self.gemstone_session_record.log_out()
        self.gemstone_session_record = None
        self.event_queue.publish('LoggedOut')
            
    def clear_widgets(self):
        for widget in self.winfo_children():
            if widget != self.menu_bar:
                widget.destroy()
        self.browser_tab = None
        self.debugger_tab = None

    def show_login_screen(self):
        self.clear_widgets()

        self.login_frame = LoginFrame(self)
        self.login_frame.grid(row=0, column=0, sticky="nsew")
        self.login_frame.rowconfigure(0, weight=1)
        self.login_frame.columnconfigure(0, weight=1)

    def show_main_app(self, gemstone_session_record):
        self.gemstone_session_record = gemstone_session_record
        
        self.clear_widgets()

        self.create_notebook()
        self.add_browser_tab()

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def add_browser_tab(self):
        if self.browser_tab:
            self.browser_tab.destroy()
        self.browser_tab = BrowserWindow(self.notebook, self)
        self.notebook.add(self.browser_tab, text="Browser")

    def open_debugger(self, exception):
        if self.debugger_tab:
            if self.debugger_tab.is_running:
                response = messagebox.askquestion("Debugger Already Open", "A debugger is already open. Replace it with a new one?", icon='warning', type='okcancel')
                if response == 'cancel':
                    return
            self.debugger_tab.destroy()

        self.add_debugger_tab(exception)
        self.select_debugger_tab()

    def add_debugger_tab(self, exception):
        self.debugger_tab = DebuggerWindow(self.notebook, self, self.gemstone_session_record, self.event_queue, exception)
        self.notebook.add(self.debugger_tab, text="Debugger")

    def select_debugger_tab(self):
        pass
        # if self.debugger_tab:
        #     self.notebook.select(self.debugger_tab)
        #     self.debugger_tab.top_frame.lift()
        #     self.debugger_tab.forget(self.debugger_tab.top_frame)
        #     self.debugger_tab.add(self.debugger_tab.top_frame)            
        #     self.debugger_tab.event_generate('<Configure>')
        #     self.debugger_tab.update()
        
    def handle_find_selection(self, show_instance_side, class_name):
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish('SelectedClassChanged')
        
    def handle_implementor_selection(self, method_symbol, class_name, show_instance_side):
        selected_show_instance_side = show_instance_side
        selected_method = method_symbol

        self.gemstone_session_record.jump_to_method(class_name, show_instance_side, method_symbol)
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')

    def run_code(self, source=""):
        RunDialog(self, source=source)
        
    def open_find_dialog(self):
        FindDialog(self)
        
    def open_implementors_dialog(self, method_symbol=None):
        ImplementorsDialog(self, method_name=method_symbol)
        
        
class RunDialog(tk.Toplevel):
    def __init__(self, parent, source=""):
        super().__init__(parent)
        self.title("Run Code")
        self.geometry("600x500")
        self.transient(parent)  # Set to be on top of the parent window
        self.grab_set()  # Prevent interaction with the main window
        self.focus_force()  # Force focus to the dialog

        self.source_label = tk.Label(self, text="Source Code:")
        self.source_label.pack(anchor="w", padx=10, pady=(10, 0))

        self.source_text = tk.Text(self, height=10)
        self.source_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.source_text.insert(tk.END, source)

        self.run_button = tk.Button(self, text="Run", command=self.run_code_from_editor)
        self.run_button.pack(pady=(0, 10))

        self.status_label = tk.Label(self, text="Running...")
        self.status_label.pack(anchor="w", padx=10)

        self.result_label = tk.Label(self, text="Result:")
        self.result_label.pack(anchor="w", padx=10, pady=(10, 0))

        self.result_text = tk.Text(self, height=5, state="disabled")
        self.result_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.close_button = tk.Button(self, text="Close", command=self.destroy)
        self.close_button.pack(pady=(0, 10))

        # Run the code immediately if there is any in the source area
        if source.strip():
            self.run_code_from_editor()

    def run_code_from_editor(self):
        self.status_label.config(text="Running...")
        try:
            code_to_run = self.source_text.get("1.0", tk.END).strip()
            result = self.master.gemstone_session_record.run_code(code_to_run)
            self.on_run_complete(result)
        except Exception as e:
            self.status_label.config(text=f"Error: {str(e)}")
            self.debug_button = tk.Button(self, text="Debug", command=lambda exc=e: self.open_debugger(exc))
            self.debug_button.pack(pady=(0, 10))
            
    def on_run_complete(self, result):
        self.status_label.config(text="Completed successfully")
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, result.asString().to_py)
        self.result_text.config(state="disabled")

    def open_debugger(self, exception):
        self.destroy()        
        self.master.open_debugger(exception)
        
class FramedWidget(ttk.Frame):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, borderwidth=2, relief="sunken")
        self.browser_window = browser_window
        self.event_queue = event_queue
        self.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

    @property
    def gemstone_session_record(self):
        return self.browser_window.gemstone_session_record
    
    def destroy(self):
        super().destroy()
        self.event_queue.clear_subscribers(self)

class InteractiveSelectionList(ttk.Frame):
    def __init__(self, parent, get_all_entries, get_selected_entry, set_selected_to):
        super().__init__(parent)

        self.get_all_entries = get_all_entries
        self.get_selected_entry = get_selected_entry
        self.set_selected_to = set_selected_to

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, columnspan=2, sticky='ew')

        # Packages listbox to show filtered packages with scrollbar
        self.selection_listbox = tk.Listbox(self, selectmode=tk.SINGLE, exportselection=False)
        self.selection_listbox.grid(row=1, column=0, sticky='nsew')

        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.selection_listbox.yview)
        self.scrollbar.grid(row=1, column=1, sticky='ns')
        self.selection_listbox.config(yscrollcommand=self.scrollbar.set)

        # Configure weights for proper resizing
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Initial population of listbox
        self.repopulate()

        # Bind the listbox selection event
        self.selection_listbox.bind('<<ListboxSelect>>', self.handle_selection)
        
    def repopulate(self, origin=None):
        # Store packages for filtering purposes
        self.all_entries = self.get_all_entries()
        self.filter_var.set('')
        self.update_filter()

        # Scroll into view the selected item if it exists
        selected_indices = self.selection_listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            if not self.selection_listbox.bbox(index):
                self.selection_listbox.see(index)
                    
    def update_filter(self, *args):
        # Get the filter text
        filter_text = self.filter_var.get().lower()

        # Clear current listbox contents
        self.selection_listbox.delete(0, tk.END)

        selected_entry = self.get_selected_entry()
        
        # Add only matching packages to the listbox and select the matching item
        for index, entry in enumerate(self.all_entries):
            if filter_text in entry.lower():
                self.selection_listbox.insert(tk.END, entry)
                if selected_entry and selected_entry == entry:
                    self.selection_listbox.selection_set(index)

    def handle_selection(self, event):
        try:
            selected_listbox = event.widget
            selected_index = selected_listbox.curselection()[0]
            selected_entry = selected_listbox.get(selected_index)

            self.set_selected_to(selected_entry)
        except IndexError:
            pass

        
class PackageSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.selection_list = InteractiveSelectionList(self, self.get_all_packages, self.get_selected_package, self.select_package)
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
                                                       
        # Initial population of listbox
        self.repopulate()

        # Subscribe to event_queue for any "Aborted" event
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

    def select_package(self, selected_package):
        self.gemstone_session_record.select_package(selected_package)
        self.event_queue.publish('SelectedPackageChanged', origin=self)
        
    def get_all_packages(self):
        return list(self.browser_window.gemstone_session_record.class_categories)

    def get_selected_package(self):
        return self.gemstone_session_record.selected_package
        
    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()

            
class ClassSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)
        
        self.classes_notebook = ttk.Notebook(self)
        self.classes_notebook.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Create 'List' tab with an InteractiveSelectionList
        self.selection_list = InteractiveSelectionList(self, self.get_all_classes, self.get_selected_class, self.select_class)
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.classes_notebook.add(self.selection_list, text='List')

        # Create 'Hierarchy' tab with a Treeview
        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.hierarchy_frame.grid(row=0, column=0, sticky="nsew")
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(self.hierarchy_frame)
        self.hierarchy_tree.grid(row=0, column=0, sticky='nsew')
        self.hierarchy_frame.rowconfigure(0, weight=1)
        self.hierarchy_frame.columnconfigure(0, weight=1)
        self.hierarchy_tree.insert('', 'end', text='Root Node')
        parent_node = self.hierarchy_tree.insert('', 'end', text='Parent Node 1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.2')
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.repopulate_categories)

        # Add Radiobuttons for Class or Instance selection
        self.selection_var = tk.StringVar(value='instance' if self.gemstone_session_record.show_instance_side else 'class')
        self.selection_var.trace_add('write', lambda name, index, operation: self.switch_side())
        self.class_radiobutton = tk.Radiobutton(self, text='Class', variable=self.selection_var, value='class')
        self.instance_radiobutton = tk.Radiobutton(self, text='Instance', variable=self.selection_var, value='instance')
        self.class_radiobutton.grid(column=0, row=2, sticky="w")
        self.instance_radiobutton.grid(column=1, row=2, sticky="w")

        # Configure row and column for frame layout to expand properly
        self.rowconfigure(1, weight=0)  # Give no weight to the row with radiobuttons to keep them fixed

        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

    def switch_side(self):
        self.gemstone_session_record.select_instance_side(self.show_instance_side)
        self.event_queue.publish('SelectedClassChanged')

    @property
    def show_instance_side(self):
        return self.selection_var.get() == 'instance'  

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                # Handle selection from a Listbox
                selected_index = widget.curselection()[0]
                selected_class = widget.get(selected_index)
            elif isinstance(widget, ttk.Treeview):
                # Handle selection from a Treeview
                selected_item_id = widget.selection()[0]
                selected_class = widget.item(selected_item_id, 'text')

            self.gemstone_session_record.select_class(selected_class)
            self.event_queue.publish('SelectedClassChanged', origin=self)
        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            selected_package = self.gemstone_session_record.selected_package
            # Repopulate hierarchy_tree with new options based on the selected package
            self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
            # parent_node = self.hierarchy_tree.insert('', 'end', text=f'{selected_package} Parent Node 1')
            # self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.1')
            # self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.2')

            # Repopulate InteractiveSelectionList with new options based on the selected package
            self.selection_list.repopulate()

            # Always select the 'List' tab in the classes_notebook after repopulating
            self.classes_notebook.select(self.selection_list)

    def get_all_classes(self):
        selected_package = self.gemstone_session_record.selected_package
        return list(self.browser_window.gemstone_session_record.get_classes_in_category(selected_package))

    def get_selected_class(self):
        return self.gemstone_session_record.selected_class

    def select_class(self, selected_class):
        self.gemstone_session_record.select_class(selected_class)
        self.event_queue.publish('SelectedClassChanged', origin=self)

                    
class CategorySelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        # Create InteractiveSelectionList for categories
        self.selection_list = InteractiveSelectionList(self, self.get_all_categories, self.get_selected_category, self.select_category)
        self.selection_list.grid(row=0, column=0, sticky="nsew")

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

    def repopulate_class_and_instance(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            self.selected_category = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_category(self.selected_category)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
        except IndexError:
            pass
        
    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()

    def get_all_categories(self):
        if self.gemstone_session_record.selected_class:
            # Repopulate InteractiveSelectionList with new options based on the selected class
            return ['all'] + list(self.gemstone_session_record.get_categories_in_class(
                self.gemstone_session_record.selected_class, 
                self.gemstone_session_record.show_instance_side
            ))
        else:
            return  []

    def get_selected_category(self):
        return self.gemstone_session_record.selected_method_category

    def select_category(self, selected_category):
        self.gemstone_session_record.select_method_category(selected_category)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        # Create InteractiveSelectionList for methods
        self.selection_list = InteractiveSelectionList(self, self.get_all_methods, self.get_selected_method, self.select_method)
        self.selection_list.grid(row=0, column=0, sticky="nsew")

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        self.event_queue.subscribe('MethodSelected', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_method = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_symbol(selected_method)
            self.selection_changed = False
            self.event_queue.publish('MethodSelected', origin=self)

        except IndexError:
            pass
        
    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()

    def get_all_methods(self):
        return self.gemstone_session_record.get_current_methods()

    def get_selected_method(self):
        return self.gemstone_session_record.selected_method_symbol

    def select_method(self, selected_method):
        self.gemstone_session_record.select_method_symbol(selected_method)
        self.event_queue.publish('MethodSelected', origin=self)

        
class MethodEditor(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.current_menu = None
        
        # Add a label bar above the notebook
        self.label_bar = tk.Label(self, text="Method Editor", anchor='w')
        self.label_bar.grid(row=0, column=0, columnspan=2, sticky='ew')

        # Add a notebook to editor_area_widget
        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.grid(row=1, column=0, sticky='nsew')
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Bind right-click event to the notebook for context menu
        self.editor_notebook.bind('<Button-3>', self.open_tab_menu_handler)
        # Bind hover event to change label bar text when the mouse moves over tabs
        self.editor_notebook.bind('<Motion>', self.on_tab_motion)
        self.editor_notebook.bind('<Leave>', self.on_tab_leave)

        # Dictionary to keep track of open tabs
        self.open_tabs = {}  # Format: {(class_name, show_instance_side, method_symbol): tab_reference}

        self.event_queue.subscribe('MethodSelected', self.open_method)
        self.event_queue.subscribe('Aborted', self.repopulate)
        
    def repopulate(self, origin=None):
        # Iterate through each open tab and update the text editor with the current method source code
        for key, tab in dict(self.open_tabs).items():
            tab.repopulate()

    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)

    def open_tab_menu_handler(self, event):
        # Identify which tab was clicked
        tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
        tab = self.get_tab(tab_index)
        tab.open_tab_menu(event)

    def close_tab(self, tab):
        tab_id = self.open_tabs[tab.tab_key]
        self.editor_notebook.forget(tab_id)
        if tab.tab_key in self.open_tabs:
            del self.open_tabs[tab.tab_key]

    def open_method(self, origin=None):
        selected_class = self.gemstone_session_record.selected_class
        show_instance_side = self.gemstone_session_record.show_instance_side
        selected_method_symbol = self.gemstone_session_record.selected_method_symbol

        # Check if tab already exists using open_tabs dictionary
        if (selected_class, show_instance_side, selected_method_symbol) in self.open_tabs:
            self.editor_notebook.select(self.open_tabs[(selected_class, show_instance_side, selected_method_symbol)])
            return

        # Create a new tab using EditorTab
        new_tab = EditorTab(self.editor_notebook, self.browser_window, self, (selected_class, show_instance_side, selected_method_symbol))
        self.editor_notebook.add(new_tab, text=selected_method_symbol)
        self.editor_notebook.select(new_tab)

        # Add the tab to open_tabs dictionary
        self.open_tabs[(selected_class, show_instance_side, selected_method_symbol)] = new_tab

    def on_tab_motion(self, event):
        try:
            tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
            if tab_index is not None:
                tab_key = self.get_tab(tab_index).tab_key
                if tab_key[1]:
                    text = f"{tab_key[0]}>>{tab_key[2]}"
                else:
                    text = f"{tab_key[0]} class>>{tab_key[2]}"
                self.label_bar.config(text=text)
        except tk.TclError:
            pass

    def on_tab_leave(self, event):
        self.label_bar.config(text="Method Editor")


class CodePanel(tk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)

        self.application = application
        
        # Assuming text editor widget will be placed here (e.g., tk.Text)
        self.text_editor = tk.Text(self, tabs=('4',), wrap='none')

        # Add scrollbars to the text editor
        self.scrollbar_y = tk.Scrollbar(self, orient='vertical', command=self.text_editor.yview)
        self.scrollbar_x = tk.Scrollbar(self, orient='horizontal', command=self.text_editor.xview)
        self.text_editor.configure(yscrollcommand=self.scrollbar_y.set, xscrollcommand=self.scrollbar_x.set)

        # Use grid instead of pack
        self.text_editor.grid(row=0, column=0, sticky='nsew')
        self.scrollbar_y.grid(row=0, column=1, sticky='ns')
        self.scrollbar_x.grid(row=1, column=0, sticky='ew')

        # Configure the grid weights for resizing
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Configure a tag for syntax highlighting
        self.text_editor.tag_configure("smalltalk_keyword", foreground="blue")
        self.text_editor.tag_configure("smalltalk_comment", foreground="green")
        self.text_editor.tag_configure("smalltalk_string", foreground="orange")
        
        # Configure a tag for highlighting with a darker background color
        self.text_editor.tag_configure("highlight", background="darkgrey")
        
        # Bind key release event to update syntax highlighting
        self.text_editor.bind("<KeyRelease>", self.on_key_release)

        # Bind right-click event to open context menu for selected text
        self.text_editor.bind("<Button-3>", self.open_text_menu)

        # Track the current context menu
        self.current_context_menu = None

        # Bind click event to close context menu when clicking outside
        self.text_editor.bind("<Button-1>", self.close_context_menu, add="+")

    def open_text_menu(self, event):
        # Close any existing context menu before opening a new one
        if self.current_context_menu:
            self.current_context_menu.unpost()

        # Create a context menu for the selected text
        self.current_context_menu = tk.Menu(self, tearoff=0)
        self.current_context_menu.add_command(label="Run", command=lambda: self.run_selected_text(self.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST)))
        self.current_context_menu.post(event.x_root, event.y_root)

    def close_context_menu(self, event):
        # Close the current context menu if it exists
        if self.current_context_menu:
            self.current_context_menu.unpost()
            self.current_context_menu = None

    def run_selected_text(self, selected_text):
        self.application.run_code(selected_text)

    def apply_syntax_highlighting(self, text):
        # A simple example of syntax highlighting for Smalltalk code
        # Highlight keywords
        for match in re.finditer(r'\b(class|self|super|true|false|nil)\b', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_keyword", f"1.0 + {start} chars", f"1.0 + {end} chars")

        # Highlight comments
        for match in re.finditer(r'".*?"', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_comment", f"1.0 + {start} chars", f"1.0 + {end} chars")

        # Highlight strings
        for match in re.finditer(r'\'.*?\'', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_string", f"1.0 + {start} chars", f"1.0 + {end} chars")

    def on_key_release(self, event):
        # Apply syntax highlighting as user types
        text = self.text_editor.get("1.0", tk.END)
        self.apply_syntax_highlighting(text)

    def refresh(self, source, mark=None):
        # Update the CodePanel with the source code of the method
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", source)

        # Highlight the word starting at the position given by mark, if valid
        if mark is not None and mark >= 0:
            position = self.text_editor.index(f"1.0 + {mark-1} chars")
            self.text_editor.tag_add("highlight", position, f"{position} + 1c")
            
        # Apply syntax highlighting
        self.apply_syntax_highlighting(source)
        

class EditorTab(tk.Frame):
    def __init__(self, parent, browser_window, method_editor, tab_key):
        super().__init__(parent)
        self.browser_window = browser_window
        self.method_editor = method_editor
        self.tab_key = tab_key

        # Create CodePanel instance
        self.code_panel = CodePanel(self, self.browser_window.application)
        self.code_panel.grid(row=0, column=0, sticky='nsew')

        # Configure the grid weights for resizing
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.repopulate()

    def open_tab_menu(self, event):
        # If a menu is already open, unpost it first
        if self.method_editor.current_menu:
            self.method_editor.current_menu.unpost()

        # Create a context menu for the tab
        self.method_editor.current_menu = tk.Menu(self.browser_window, tearoff=0)
        self.method_editor.current_menu.add_command(label="Close", command=lambda: self.method_editor.close_tab(self))
        self.method_editor.current_menu.add_command(label="Save", command=lambda: self.save())

        self.method_editor.current_menu.post(event.x_root, event.y_root)

    def save(self):
        (selected_class, show_instance_side, method_symbol) = self.tab_key
        self.browser_window.gemstone_session_record.update_method_source(selected_class, show_instance_side, method_symbol, self.code_panel.text_editor.get("1.0", "end-1c"))
        self.browser_window.event_queue.publish('MethodSelected', origin=self)
        self.repopulate()
        
    def repopulate(self):
        (selected_class, show_instance_side, method_symbol) = self.tab_key
        gemstone_method = self.browser_window.gemstone_session_record.get_method(*self.tab_key)
        if gemstone_method:
            method_source = gemstone_method.sourceString().to_py
            self.code_panel.refresh(method_source)
        else:
            self.method_editor.close_tab(self)
        
        
class BrowserWindow(ttk.PanedWindow):
    def __init__(self, parent, application):
        super().__init__(parent, orient=tk.VERTICAL)  # Make BrowserWindow a vertical paned window

        self.application = application

        # Create two frames to act as rows in the PanedWindow
        self.top_frame = ttk.Frame(self)
        self.bottom_frame = ttk.Frame(self)

        # Add frames to the PanedWindow
        self.add(self.top_frame)   # Add the top frame (row 0)
        self.add(self.bottom_frame)  # Add the bottom frame (row 1)

        # Add widgets to top_frame (similar to row 0 previously)
        self.packages_widget = PackageSelection(self.top_frame, self, self.event_queue, 0, 0)
        self.classes_widget = ClassSelection(self.top_frame, self, self.event_queue, 0, 1)
        self.categories_widget = CategorySelection(self.top_frame, self, self.event_queue, 0, 2)
        self.methods_widget = MethodSelection(self.top_frame, self, self.event_queue, 0, 3)

        # Add MethodEditor to bottom_frame (similar to row 1 previously)
        self.editor_area_widget = MethodEditor(self.bottom_frame, self, self.event_queue, 0, 0, colspan=4)

        # Configure grid in top_frame and bottom_frame for proper resizing
        self.top_frame.columnconfigure(0, weight=1)
        self.top_frame.columnconfigure(1, weight=1)
        self.top_frame.columnconfigure(2, weight=1)
        self.top_frame.columnconfigure(3, weight=1)
        self.top_frame.rowconfigure(0, weight=1)

        self.bottom_frame.columnconfigure(0, weight=1)
        self.bottom_frame.rowconfigure(0, weight=1)

    @property
    def event_queue(self):
        return self.application.event_queue
    
    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record


class StackFrame:
    def __init__(self, gemstone_process, level):
        self.gemstone_session = gemstone_process.session
        self.gemstone_process = gemstone_process
        self.level = level
        self.frame_data = frame_data = self.gemstone_process.perform('_frameContentsAt:', self.gemstone_session.from_py(self.level))
        self.is_valid = not frame_data.isNil().to_py
        if self.is_valid:
            self.gemstone_method = frame_data.at(1)
            self.ip_offset = frame_data.at(2)
            self.var_context = frame_data.at(4)

    @property
    def step_point_offset(self):
        # See OGStackFrame initializeContexts
        step_point = self.gemstone_method.perform('_nextStepPointForIp:', self.ip_offset)
        offsets = self.gemstone_method.perform('_sourceOffsets')
        offset = offsets.at(step_point.min(offsets.size()))
        return offset.to_py

    @property
    def method_source(self):
        return self.gemstone_method.fullSource().to_py

    @property
    def method_name(self):
        return self.gemstone_method.selector().to_py

    @property
    def class_name(self):
        return self.gemstone_method.homeMethod().inClass().asString().to_py

    @property
    def self(self):
        return self.frame_data.at(8)

    @property
    def vars(self):
        vars = {}
        var_names = self.frame_data.at(9)
        for idx, name in enumerate(var_names):
            value = self.frame_data.at(11+idx)
            vars[name.to_py] = value
        return vars

    
class CallStack:
    def __init__(self, gemstone_process):
        self.gemstone_process = gemstone_process
        self.frames = self.make_frames()
        
    def make_frames(self):
        session = self.gemstone_process.session
        max_level = self.gemstone_process.stackDepth().to_py
        stack = []
        level = 1
        while level <= max_level and ((frame := self.stack_frame(level)).is_valid):
            stack.append(frame)
            level += 1
        return stack
    
    def stack_frame(self, level):
        return StackFrame(self.gemstone_process, level)

    def __getitem__(self, level):
        return self.frames[level-1]

    def __iter__(self):
        return iter(self.frames)


class ObjectInspector(ttk.Frame):
    def __init__(self, parent, an_object=None, values=None):
        super().__init__(parent)

        if not values:
            values = {}
            for instvar_name in an_object.gemstone_class().allInstVarNames():
                values[instvar_name.to_py] = an_object.instVarNamed(instvar_name)
        
        # Keep a list of actual value objects
        self.actual_values = []

        # Create a Treeview widget in the 'context' tab
        self.treeview = ttk.Treeview(self, columns=('Name', 'Class', 'Value'), show='headings')
        self.treeview.heading('Name', text='Name')
        self.treeview.heading('Class', text='Class')
        self.treeview.heading('Value', text='Value')
        self.treeview.grid(row=0, column=0, sticky="nsew")

        # Add data to the Treeview and keep track of actual values
        for name, value in values.items():
            self.treeview.insert('', 'end', values=(name, value.gemstone_class().asString().to_py, value.asString().to_py))
            self.actual_values.append(value)

        # Configure grid in the context_frame for proper resizing
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Bind double-click event to add new tab
        self.treeview.bind("<Double-1>", self.on_item_double_click)

    def on_item_double_click(self, event):
        selected_item = self.treeview.focus()
        if selected_item:
            index = self.treeview.index(selected_item)
            value = self.actual_values[index]  # Fetch the actual value from the list
            if hasattr(value, 'gemstone_class') and hasattr(value, 'allInstVarNames'):
                new_tab = ObjectInspector(self.master, an_object=value)
                self.master.add(new_tab, text=f"Inspector: {self.treeview.item(selected_item, 'values')[0]}")                



class Explorer(ttk.Notebook):
    def __init__(self, parent, an_object=None, values=None):
        super().__init__(parent)

        # Create a new ObjectInspector for the 'context' tab
        context_frame = ObjectInspector(self, an_object=an_object, values=values)
        self.add(context_frame, text='Context')


class DebuggerWindow(ttk.PanedWindow):
    def __init__(self, parent, application, gemstone_session_record, event_queue, exception):
        super().__init__(parent, orient=tk.VERTICAL)  # Make DebuggerWindow a vertical paned window

        self.application = application
        self.exception = exception
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record

        # Create top and bottom frames to act as rows in the PanedWindow
        self.call_stack_frame = ttk.Frame(self)
        self.code_panel_frame = ttk.Frame(self)
        self.explorer_frame = ttk.Frame(self)

        # Add frames to the PanedWindow with equal weights
        self.add(self.call_stack_frame, weight=1)
        self.add(self.code_panel_frame, weight=1)
        self.add(self.explorer_frame, weight=1)

        # Add DebuggerControls to the top of the call_stack_frame
        self.debugger_controls = DebuggerControls(self.call_stack_frame, self, self.event_queue)
        self.debugger_controls.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Add a Treeview widget to the top frame, below DebuggerControls, to represent the three-column list
        self.listbox = ttk.Treeview(self.call_stack_frame, columns=('Level', 'Column1', 'Column2'), show='headings')
        self.listbox.heading('Level', text='Level')
        self.listbox.heading('Column1', text='Class Name')
        self.listbox.heading('Column2', text='Method Name')
        self.listbox.grid(row=1, column=0, sticky="nsew")
        
        # Dictionary to store StackFrame objects by Treeview item ID
        self.stack_frames = CallStack(self.exception.context)
        
        # Bind item selection to method execution
        self.listbox.bind("<ButtonRelease-1>", self.on_listbox_select)
        
        # Add a Text widget to the bottom frame (text editor)
        self.code_panel = CodePanel(self.code_panel_frame, application=application)
        self.code_panel.grid(row=0, column=0, sticky="nsew")

        # Configure grid in call_stack_frame, code_panel_frame, and explorer_frame for proper resizing
        self.call_stack_frame.columnconfigure(0, weight=1)
        self.call_stack_frame.rowconfigure(1, weight=1)

        self.code_panel_frame.columnconfigure(0, weight=1)
        self.code_panel_frame.rowconfigure(0, weight=1)

        self.explorer_frame.columnconfigure(0, weight=1)
        self.explorer_frame.rowconfigure(0, weight=1)

        # Make the parent window expand correctly
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Ensure DebuggerWindow itself expands within its parent
        self.grid(row=0, column=0, sticky="nsew")

        self.refresh()

    @property
    def is_running(self):
        return bool(self.stack_frames)
    
    def refresh(self):
        # Clear the existing contents of the listbox
        for item in self.listbox.get_children():
            self.listbox.delete(item)
        
        # Re-populate the listbox with updated stack frames
        for frame in self.stack_frames:
            iid = str(frame.level)
            self.listbox.insert('', 'end', iid=iid, values=(frame.level, frame.class_name, frame.method_name))
        
        # Select the first entry in the listbox by iid
        if self.stack_frames:
            first_iid = str(1)
            self.listbox.selection_set(first_iid)
            self.listbox.focus(first_iid)

            self.code_panel.refresh(self.stack_frames[1].method_source, mark=self.stack_frames[1].step_point_offset)
            self.refresh_explorer(self.stack_frames[1])

    def refresh_explorer(self, frame):
        # Clear existing widgets in the explorer_frame
        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        # Create an Explorer widget in the explorer_frame
        explorer = Explorer(self.explorer_frame, frame, values=dict([('self', frame.self)] + list(frame.vars.items())))
        explorer.grid(row=0, column=0, sticky="nsew")
    
    def on_listbox_select(self, event):
        frame = self.get_selected_stack_frame()
        if frame:
            self.code_panel.refresh(frame.method_source, mark=frame.step_point_offset)
            self.refresh_explorer(frame)
            
    def get_selected_stack_frame(self):
        selected_item = self.listbox.focus()
        if selected_item:
            return self.stack_frames[int(selected_item)]
        return None

    @contextlib.contextmanager
    def active_frame(self):
        frame = self.get_selected_stack_frame()
        if frame:
            try:
                yield frame
            except GemstoneError as ex:
                self.exception = ex
                self.stack_frames = CallStack(self.exception.context)
                self.refresh()
            else:
                self.finish(frame.result)
        
    def continue_running(self):
        with self.active_frame() as frame:
            frame.result = self.exception.continue_with()
            frame.result.gemstone_class().asString()
    
    def step_over(self):
        with self.active_frame() as frame:
            frame.result = self.exception.context.gciStepOverFromLevel(frame.level)

    def step_into(self):
        with self.active_frame() as frame:
            frame.result = self.exception.context.gciStepIntoFromLevel(frame.level)
                
    def step_through(self):
        with self.active_frame() as frame:
            frame.result = self.exception.context.gciStepThruFromLevel(frame.level)
            
    def stop(self):
        with self.active_frame() as frame:
            frame.result = self.exception.context.resume()
        self.stack_frames = None
        self.destroy()
                
    def finish(self, result):
        self.stack_frames = None

        # Remove existing frames from the PanedWindow
        self.forget(self.call_stack_frame)
        self.forget(self.code_panel_frame)
        self.forget(self.explorer_frame)

        # Create and add a Text widget to display the result
        self.result_text = tk.Text(self)
        self.result_text.insert('1.0', result.asString().to_py)
        self.result_text.pack(fill='both', expand=True)
        
            
class DebuggerControls(ttk.Frame):
    def __init__(self, parent, debugger, event_queue):
        super().__init__(parent)
        self.debugger = debugger
        self.event_queue = event_queue

        # Create buttons for Debugger Controls
        self.continue_button = ttk.Button(self, text="Continue", command=self.handle_continue)
        self.continue_button.grid(row=0, column=0, padx=5, pady=5)

        self.over_button = ttk.Button(self, text="Over", command=self.handle_over)
        self.over_button.grid(row=0, column=1, padx=5, pady=5)

        self.into_button = ttk.Button(self, text="Into", command=self.handle_into)
        self.into_button.grid(row=0, column=2, padx=5, pady=5)

        self.through_button = ttk.Button(self, text="Through", command=self.handle_through)
        self.through_button.grid(row=0, column=3, padx=5, pady=5)

        self.stop_button = ttk.Button(self, text="Stop", command=self.handle_stop)
        self.stop_button.grid(row=0, column=4, padx=5, pady=5)

    def handle_continue(self):
        self.debugger.continue_running()

    def handle_over(self):
        self.debugger.step_over()

    def handle_into(self):
        self.debugger.step_into()
        
    def handle_through(self):
        self.debugger.step_through()

    def handle_stop(self):
        self.debugger.stop()


        
class LoginFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.error_label = None

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)
        self.rowconfigure(4, weight=1)
        self.rowconfigure(5, weight=1)
        self.rowconfigure(6, weight=1)
        self.rowconfigure(7, weight=1)
        self.rowconfigure(8, weight=1)
        
        # Username label and entry
        ttk.Label(self, text="Username:").grid(column=0,row=0)
        self.username_entry = ttk.Entry(self)
        self.username_entry.insert(0, 'DataCurator')
        self.username_entry.grid(column=1,row=0)

        # Password label and entry
        ttk.Label(self, text="Password:").grid(column=0,row=1)
        self.password_entry = ttk.Entry(self, show='*')
        self.password_entry.insert(0, 'swordfish')
        self.password_entry.grid(column=1,row=1)

        ttk.Label(self, text="Stone name:").grid(column=0,row=2)
        self.stone_name_entry = ttk.Entry(self)
#        self.stone_name_entry.insert(0, 'gs64stone')
        self.stone_name_entry.insert(0, 'development')
        self.stone_name_entry.grid(column=1,row=2)

        # Remote checkbox
        self.remote_var = tk.BooleanVar()
        self.remote_checkbox = ttk.Checkbutton(self, text="Login RPC?", variable=self.remote_var, command=self.toggle_remote_widgets)
        self.remote_checkbox.grid(column=0, row=3)

        # Remote widgets (initially hidden)
        self.netldi_name_label = ttk.Label(self, text="Netldi name:")
        self.netldi_name_entry = ttk.Entry(self)
        self.netldi_name_entry.insert(0, 'gs64-ldi')

        self.rpc_hostname_label = ttk.Label(self, text="RPC host name:")
        self.rpc_hostname_entry = ttk.Entry(self)
        self.rpc_hostname_entry.insert(0, 'localhost')

        # Login button
        ttk.Button(self, text="Login", command=self.attempt_login).grid(column=0,row=8,columnspan=2)
        
    @property
    def login_rpc(self):
        return self.remote_var.get()

    def toggle_remote_widgets(self):
        if self.remote_var.get():
            # Show the remote widgets
            self.netldi_name_label.grid(column=0, row=4)
            self.netldi_name_entry.grid(column=1, row=4)
            self.rpc_hostname_label.grid(column=0, row=5)
            self.rpc_hostname_entry.grid(column=1, row=5)
        else:
            # Hide the remote widgets
            self.netldi_name_label.grid_remove()
            self.netldi_name_entry.grid_remove()
            self.rpc_hostname_label.grid_remove()
            self.rpc_hostname_entry.grid_remove()
            
    def attempt_login(self):
        if self.error_label:
            self.error_label.destroy()

        username = self.username_entry.get()
        password = self.password_entry.get()
        stone_name = self.stone_name_entry.get()
        netldi_name = self.netldi_name_entry.get()
        rpc_hostname = self.rpc_hostname_entry.get()
        try:
            if self.login_rpc:
                gemstone_session_record = GemstoneSessionRecord.log_in_rpc(username, password, rpc_hostname, stone_name, netldi_name)
            else:
                gemstone_session_record = GemstoneSessionRecord.log_in_linked(username, password, stone_name)
            self.parent.event_queue.publish('LoggedInSuccessfully', gemstone_session_record)
        except DomainException as ex:
            self.error_label = ttk.Label(self, text=str(ex), foreground="red")
            self.error_label.grid(column=0,row=6,columnspan=2)           


def run_application():
    app = Swordfish()
    app.mainloop()

if __name__ == "__main__":
    run_application()
