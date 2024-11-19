import logging
import weakref

from ptongue.gemproxyrpc import RPCSession
from ptongue.gemproxylinked import LinkedSession
from ptongue.gemproxy import GemstoneError

import tkinter as tk
from tkinter import ttk

class DomainException(Exception):
    pass

class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.selected_class_category = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.show_instance_side = True

    def select_class_category(self, class_category):
        self.selected_class_category = class_category
        
    def select_instance_side(self, show_instance_side):
        self.show_instance_side = show_instance_side

    def select_class(self, selected_class):
        self.selected_class = selected_class

    def select_method_category(self, selected_method_category):
        self.selected_method_category = selected_method_category
        
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
            selectors = class_to_query.selectorsIn(method_category).asSortedCollection()
        except GemstoneError:
            return
        
        yield from [i.to_py for i in selectors]

    def get_method(self, class_name, method_symbol, show_instance_side):
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        class_to_query = gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        try:
            return class_to_query.compiledMethodAt(method_symbol)
        except GemstoneError:
            return
        
        
class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = []
        self.root.bind('<<CustomEventsPublished>>', self.process_events)

    def subscribe(self, event_name, callback, *args):
        self.events.setdefault(event_name, [])
        self.events[event_name].append((weakref.WeakMethod(callback), args))

    def publish(self, event_name, *args):
        if event_name in self.events:
            self.queue.append((event_name, args))
        self.root.event_generate('<<CustomEventsPublished>>')

    def process_events(self, event):
        while self.queue:
            event_name, args = self.queue.pop(0)
            if event_name in self.events:
                logging.getLogger(__name__).debug(f'Processing: {event_name}')
                for weak_callback, callback_args in self.events[event_name]:
                    callback = weak_callback()
                    if callback is not None:
                        logging.getLogger(__name__).debug(f'Calling: {callback}')
                        callback(*callback_args, *args)
                    
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
        self.file_menu.add_command(label="Find", command=self.show_find_dialog)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

        # Session Menu
        self.add_cascade(label="Session", menu=self.session_menu)
        self.update_session_menu()

    def _subscribe_events(self):
        self.event_queue.subscribe('LoggedInSuccessfully', self.update_session_menu)
        self.event_queue.subscribe('LoggedOut', self.update_session_menu)

    def update_session_menu(self, gemstone_session_record=None):
        self.session_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            self.session_menu.add_command(label="Commit", command=self.parent.commit)
            self.session_menu.add_command(label="Abort", command=self.parent.abort)
            self.session_menu.add_command(label="Logout", command=self.parent.logout)
        else:
            self.session_menu.add_command(label="Login", command=self.parent.show_login_screen)

    def show_find_dialog(self):
        FindDialog(self.parent)


class FindDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Find")
        self.geometry("300x400")
        self.transient(parent)
        self.grab_set()

        self.parent = parent

        # Radio buttons for search type
        self.search_type = tk.StringVar(value="class")
        ttk.Label(self, text="Search Type:").grid(row=0, column=0, padx=10, pady=5, sticky='w')
        self.class_radio = ttk.Radiobutton(self, text="Class", variable=self.search_type, value="class")
        self.class_radio.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        self.method_radio = ttk.Radiobutton(self, text="Method", variable=self.search_type, value="method")
        self.method_radio.grid(row=0, column=2, padx=5, pady=5, sticky='w')

        # Find entry
        ttk.Label(self, text="Find what:").grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.find_entry = ttk.Entry(self, width=30)
        self.find_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=10)

        # Buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=2, column=0, columnspan=3, pady=10)

        self.find_button = ttk.Button(self.button_frame, text="Find", command=self.find_text)
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=5)

        # Listbox for results (initially hidden)
        self.results_listbox = tk.Listbox(self, width=50, height=10)
        self.results_listbox.grid(row=3, column=0, columnspan=3, padx=10, pady=10)
        self.results_listbox.grid_remove()
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)

    def find_text(self):
        # Simulate search results based on the search type and query
        search_query = self.find_entry.get()
        search_type = self.search_type.get()
        results = []

        if search_query:
            if search_type == "class":
                # Simulate finding classes
                results = [f"Class_{i}: {search_query}" for i in range(1, 6)]
            elif search_type == "method":
                # Simulate finding methods
                results = [f"Method_{i}: {search_query}" for i in range(1, 6)]

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
            self.parent.handle_find_selection(search_type, selected_text)
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
        self.browser_tab = BrowserWindow(self.notebook, self.gemstone_session_record, self.event_queue)
        self.notebook.add(self.browser_tab, text="Browser Window")

    def handle_find_selection(self, search_type, selected_text):
        # Placeholder method to handle the selection from the Find dialog
        print(f"Selected {search_type}: {selected_text}")
        
class FramedWidget(ttk.Frame):
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, borderwidth=2, relief="sunken")
        self.browser_window = parent
        self.event_queue = event_queue
        self.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

    @property
    def gemstone_session_record(self):
        return self.browser_window.gemstone_session_record
    
    def destroy(self):
        super().destroy()
        self.event_queue.clear_subscribers(self)
        
        
class PackageSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky='ew')

        # Packages listbox to show filtered packages
        self.packages_listbox = tk.Listbox(self, selectmode=tk.SINGLE, exportselection=False)
        self.packages_listbox.grid(row=1, column=0, sticky='nsew')
        
        # Configure row/column weights for proper resizing
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Initial population of listbox
        self.repopulate()

        # Bind the listbox selection event
        self.packages_listbox.bind('<<ListboxSelect>>', self.repopulate_hierarchy_and_list)

        # Subscribe to event_queue for any "Aborted" event
        self.event_queue.subscribe('Aborted', self.repopulate)

    def repopulate_hierarchy_and_list(self, event):
        try:
            selected_listbox = event.widget
            selected_index = selected_listbox.curselection()[0]
            selected_package = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_class_category(selected_package)
            self.event_queue.publish('RepopulateClasses')
        except IndexError:
            pass

    def repopulate(self):
        # Store packages for filtering purposes
        self.all_packages = list(self.browser_window.gemstone_session_record.class_categories)
        self.update_filter()

    def update_filter(self, *args):
        # Get the filter text
        filter_text = self.filter_var.get().lower()

        # Clear current listbox contents
        self.packages_listbox.delete(0, tk.END)

        # Add only matching packages to the listbox
        for package in self.all_packages:
            if filter_text in package.lower():
                self.packages_listbox.insert(tk.END, package)

            
class ClassSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)
        
        self.classes_notebook = ttk.Notebook(self)
        self.classes_notebook.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Create 'List' tab with a filter entry and a listbox
        self.list_frame = ttk.Frame(self.classes_notebook)
        self.list_frame.grid(row=0, column=0, sticky="nsew")
        self.list_frame.rowconfigure(1, weight=1)
        self.list_frame.columnconfigure(0, weight=1)
        self.classes_notebook.add(self.list_frame, text='List')

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self.list_frame, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky='ew')

        # Classes listbox to show filtered classes
        self.list_listbox = tk.Listbox(self.list_frame, selectmode=tk.SINGLE, exportselection=False)
        self.list_listbox.grid(row=1, column=0, sticky="nsew")
        self.list_listbox.bind('<<ListboxSelect>>', self.repopulate_categories)

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

        self.event_queue.subscribe('RepopulateClasses', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

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
            self.event_queue.publish('SelectedClassChanged')
        except IndexError:
            pass

    def repopulate(self):
        # Repopulate hierarchy_tree with new options based on the selected package
        selected_package = self.gemstone_session_record.selected_class_category
        self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
        parent_node = self.hierarchy_tree.insert('', 'end', text=f'{selected_package} Parent Node 1')
        self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.1')
        self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.2')

        # Repopulate list_listbox with new options based on the selected package
        self.all_classes = list(self.browser_window.gemstone_session_record.get_classes_in_category(selected_package))
        self.update_filter()

        # Always select the 'List' tab in the classes_notebook after repopulating
        self.classes_notebook.select(self.list_frame)

    def update_filter(self, *args):
        # Get the filter text
        filter_text = self.filter_var.get().lower()

        # Clear current listbox contents
        self.list_listbox.delete(0, tk.END)

        # Add only matching classes to the listbox
        for class_name in self.all_classes:
            if filter_text in class_name.lower():
                self.list_listbox.insert(tk.END, class_name)
        

class CategorySelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        # Filter entry to allow filtering categories_listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky='ew')

        # Categories listbox to show filtered categories
        self.categories_listbox = tk.Listbox(self, selectmode=tk.SINGLE, exportselection=False)
        self.categories_listbox.grid(row=1, column=0, sticky='nsew')

        # Configure the grid layout to expand properly
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Bind the listbox selection event
        self.categories_listbox.bind('<<ListboxSelect>>', self.repopulate_class_and_instance)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

    def repopulate_class_and_instance(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            self.selected_category = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_category(self.selected_category)
            self.event_queue.publish('SelectedCategoryChanged')
        except IndexError:
            pass
        
    def repopulate(self):
        # Repopulate categories_listbox with new options based on the selected class
        self.all_categories = ['*']+list(self.gemstone_session_record.get_categories_in_class(
            self.gemstone_session_record.selected_class, 
            self.gemstone_session_record.show_instance_side
        ))
        self.update_filter()

    def update_filter(self, *args):
        # Get the filter text
        filter_text = self.filter_var.get().lower()

        # Clear current listbox contents
        self.categories_listbox.delete(0, tk.END)

        # Add only matching categories to the listbox
        for category in self.all_categories:
            if filter_text in category.lower():
                self.categories_listbox.insert(tk.END, category)

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        # Filter entry to allow filtering methods_listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky='ew')

        # Methods listbox to show filtered methods
        self.methods_listbox = tk.Listbox(self, selectmode=tk.SINGLE)
        self.methods_listbox.grid(row=1, column=0, sticky='nsew')

        # Configure the grid layout to expand properly
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Bind the listbox selection event
        self.methods_listbox.bind('<<ListboxSelect>>', self.populate_text_editor)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        
    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_method = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_symbol(selected_method)
            self.event_queue.publish('MethodSelected')
        except IndexError:
            pass
        
    def repopulate(self):
        # Repopulate methods_listbox with new options based on the selected class and category
        self.all_methods = list(self.gemstone_session_record.get_selectors_in_class(
            self.gemstone_session_record.selected_class, 
            self.gemstone_session_record.selected_method_category, 
            self.gemstone_session_record.show_instance_side
        ))
        self.update_filter()

    def update_filter(self, *args):
        # Get the filter text
        filter_text = self.filter_var.get().lower()

        # Clear current listbox contents
        self.methods_listbox.delete(0, tk.END)

        # Add only matching methods to the listbox
        for method in self.all_methods:
            if filter_text in method.lower():
                self.methods_listbox.insert(tk.END, method)

            
class MethodEditor(FramedWidget):
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        self.current_menu = None
        
        # Add a notebook to editor_area_widget
        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.grid(row=0, column=0, sticky='nsew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Bind right-click event to the notebook for context menu
        self.editor_notebook.bind('<Button-3>', self.open_tab_menu)

        # Dictionary to keep track of open tabs
        self.open_tabs = {}  # Format: {(class_name, show_instance_side, method_symbol): tab_reference}

        self.event_queue.subscribe('MethodSelected', self.open_method)
        self.event_queue.subscribe('Aborted', self.repopulate)
        
    def repopulate(self):
        # Iterate through each open tab and update the text editor with the current method source code
        for key, tab in self.open_tabs.items():
            selected_class, show_instance_side, method_symbol = key
            method_source = self.gemstone_session_record.get_method(selected_class, method_symbol, show_instance_side).sourceString().to_py
            text_editor = tab.winfo_children()[0]  # Assuming the text editor is the only child of the tab
            text_editor.delete(1.0, tk.END)  # Clear current text
            text_editor.insert(tk.END, method_source)  # Insert updated source code


    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)

    def open_tab_menu(self, event):
        # Identify which tab was clicked
        tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))

        matching_keys = [key for key, value in self.open_tabs.items() if value == self.get_tab(tab_index)]
        key_to_use = matching_keys[0] if matching_keys else None

        if key_to_use:
            # If a menu is already open, unpost it first
            if self.current_menu:
                self.current_menu.unpost()

            # Create a context menu for the tab
            self.current_menu = tk.Menu(self.browser_window, tearoff=0)
            self.current_menu.add_command(label="Close", command=lambda: self.close_tab(key_to_use))
            self.current_menu.add_command(label="Save", command=lambda: self.save_tab(key_to_use))

            self.current_menu.post(event.x_root, event.y_root)

    def save_tab(self, key):
        # Placeholder for save functionality
        print(f"Saving content of tab: {key}")

    def close_tab(self, key):
        tab_id = self.open_tabs[key]
        self.editor_notebook.forget(tab_id)
        if key in self.open_tabs:
            del self.open_tabs[key]

    def open_method(self):
        selected_class = self.gemstone_session_record.selected_class
        show_instance_side = self.gemstone_session_record.show_instance_side
        selected_method_symbol = self.gemstone_session_record.selected_method_symbol

        # Check if tab already exists using open_tabs dictionary
        if (selected_class, show_instance_side, selected_method_symbol) in self.open_tabs:
            self.editor_notebook.select(self.open_tabs[(selected_class, show_instance_side, selected_method_symbol)])
            return

        # Create a new tab using EditorTab
        new_tab = EditorTab(self.editor_notebook, self.browser_window)
        self.editor_notebook.add(new_tab, text=selected_method_symbol)
        self.editor_notebook.select(new_tab)

        # Add the tab to open_tabs dictionary
        self.open_tabs[(selected_class, show_instance_side, selected_method_symbol)] = new_tab

class MethodEditor(FramedWidget):
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

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
        
    def repopulate(self):
        # Iterate through each open tab and update the text editor with the current method source code
        for key, tab in self.open_tabs.items():
            tab.repopulate()

    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)

    def open_tab_menu_handler(self, event):
        # Identify which tab was clicked
        tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
        tab = self.get_tab(tab_index)
        tab.open_tab_menu(event)

    def save_tab(self, key):
        # Placeholder for save functionality
        print(f"Saving content of tab: {key}")

    def close_tab(self, key):
        tab_id = self.open_tabs[key]
        self.editor_notebook.forget(tab_id)
        if key in self.open_tabs:
            del self.open_tabs[key]

    def open_method(self):
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


class EditorTab(tk.Frame):
    def __init__(self, parent, browser_window, method_editor, tab_key):
        super().__init__(parent)
        self.browser_window = browser_window
        self.method_editor = method_editor
        self.tab_key = tab_key

        # Assuming text editor widget will be placed here (e.g., tk.Text)
        self.text_editor = tk.Text(self)
        self.text_editor.pack(fill='both', expand=True)

        self.repopulate()

    def open_tab_menu(self, event):
        # If a menu is already open, unpost it first
        if self.method_editor.current_menu:
            self.method_editor.current_menu.unpost()

        # Create a context menu for the tab
        self.method_editor.current_menu = tk.Menu(self.browser_window, tearoff=0)
        self.method_editor.current_menu.add_command(label="Close", command=lambda: self.method_editor.close_tab(self.tab_key))
        self.method_editor.current_menu.add_command(label="Save", command=lambda: self.method_editor.save_tab(self.tab_key))

        self.method_editor.current_menu.post(event.x_root, event.y_root)

    def repopulate(self):
        selected_class = self.browser_window.gemstone_session_record.selected_class
        method_symbol = self.browser_window.gemstone_session_record.selected_method_symbol
        show_instance_side = self.browser_window.gemstone_session_record.show_instance_side        
        method_source = self.browser_window.gemstone_session_record.get_method(selected_class, method_symbol, show_instance_side).sourceString().to_py
        self.text_editor.delete(1.0, tk.END)  # Clear current text
        self.text_editor.insert(tk.END, method_source)  # Insert updated source code

            
class BrowserWindow(ttk.Frame):
    def __init__(self, parent, gemstone_session_record, event_queue):
        super().__init__(parent)

        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record
        
        self.packages_widget = PackageSelection(self, self.event_queue, 0, 0)
        self.classes_widget = ClassSelection(self, self.event_queue, 0, 1)
        self.categories_widget = CategorySelection(self, self.event_queue, 0, 2)
        self.methods_widget = MethodSelection(self, self.event_queue, 0, 3)
        self.editor_area_widget = MethodEditor(self, self.event_queue, 1, 0, colspan=4)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.columnconfigure(3, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)


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


if __name__ == "__main__":
    app = Swordfish()
    app.mainloop()
