import logging

from ptongue.gemproxyrpc import RPCSession
from ptongue.gemproxy import GemstoneError

import tkinter as tk
from tkinter import ttk

class DomainException(Exception):
    pass

class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.selected_class_category = []
        self.selected_class = []
        self.selected_method_category = []
        self.selected_method = []

    @classmethod
    def log_in(cls, gemstone_user_name, gemstone_password, rpc_hostname, stone_name, netldi_name):
        nrs_string = f'!@{rpc_hostname}#netldi:{netldi_name}!gemnetobject'
        logging.getLogger(__name__).debug(f'Logging in with: {gemstone_user_name} stone_name={stone_name} netldi_task={nrs_string}')
        try:
            gemstone_session = RPCSession(gemstone_user_name, gemstone_password, stone_name=stone_name, netldi_task=nrs_string)
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

                
class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = []

    def subscribe(self, event_name, callback, *args):
        self.events.setdefault(event_name, [])
        self.events[event_name].append((callback, args))

    def publish(self, event_name, *args):
        if event_name in self.events:
            self.queue.append((event_name, args))
        self.root.event_generate('<<CustomEventsPublished>>')

    def process_events(self, event):
        while self.queue:
            event_name, args = self.queue.pop(0)
            if event_name in self.events:
                for callback, callback_args in self.events[event_name]:
                    callback(*callback_args, *args)


class Swordfish(tk.Tk):
    def __init__(self):
        super().__init__()
        self.event_queue = EventQueue(self)
        self.bind('<<CustomEventsPublished>>', self.event_queue.process_events)
        self.title("Swordfish")
        self.geometry("800x600")

        self.notebook = None
        
        self.gemstone_session_record = None

        self.event_queue.subscribe('LoggedInSuccessfully', self.show_main_app)
        self.event_queue.subscribe('LoggedOut', self.show_login_screen)
        
        self.create_menu()
        self.show_login_screen()

    @property
    def is_logged_in(self):
        return self.gemstone_session_record is not None
    
    def create_menu(self):
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        self.file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.quit)

        self.session_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Session", menu=self.session_menu)
        self.update_session_menu()
        
        self.event_queue.subscribe('LoggedInSuccessfully', self.update_session_menu)
        self.event_queue.subscribe('LoggedOut', self.update_session_menu)

    def update_session_menu(self, gemstone_session_record=None):
        self.session_menu.delete(0, tk.END)
        if self.is_logged_in:
            self.session_menu.add_command(label="Logout", command=self.logout)
        else:
            self.session_menu.add_command(label="Login", command=self.show_login_screen)
        
    def logout(self):
        self.gemstone_session_record.log_out()
        self.gemstone_session_record = None
        self.event_queue.publish('LoggedOut')
            
    def clear_widgets(self):
        for widget in self.winfo_children():
            if widget != self.menu_bar:
                widget.destroy()

    def show_login_screen(self):
        self.clear_widgets()

        self.login_frame = LoginFrame(self)
        self.login_frame.pack(expand=True, fill="both")

    def show_main_app(self, gemstone_session_record):
        self.gemstone_session_record = gemstone_session_record
        
        self.clear_widgets()

        self.create_notebook()
        self.add_browser_tab()

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both")

    def add_browser_tab(self):
        browser_tab = BrowserWindow(self.notebook, self.gemstone_session_record, self.event_queue)
        self.notebook.add(browser_tab, text="Browser Window")


class FramedWidget:
    def __init__(self, parent, event_queue, row, column, colspan=1):
        self.event_queue = event_queue
        self.frame = ttk.Frame(parent, borderwidth=2, relief="sunken")
        self.frame.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

        
class PackageSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        self.browser_window = parent
        self.packages_listbox = tk.Listbox(self.frame)
        self.packages_listbox.pack(expand=True, fill='both')
        for package in self.browser_window.gemstone_session_record.class_categories:
            self.packages_listbox.insert(tk.END, package)
        self.packages_listbox.bind('<<ListboxSelect>>', self.repopulate_hierarchy_and_list)
        
    def repopulate_hierarchy_and_list(self, event):
        try:
            selected_listbox = event.widget
            selected_index = selected_listbox.curselection()[0]
            selected_package = selected_listbox.get(selected_index)

            self.event_queue.publish('RepopulateClasses', selected_package)
        except IndexError:
            pass


class ClassSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)
        
        self.browser_window = parent
        self.selected_class = None
        self.classes_notebook = ttk.Notebook(self.frame)
        self.classes_notebook.pack(expand=True, fill='both')

        # Create 'List' tab with a listbox
        self.list_frame = ttk.Frame(self.classes_notebook)
        self.classes_notebook.add(self.list_frame, text='List')
        self.list_listbox = tk.Listbox(self.list_frame)
        self.list_listbox.pack(expand=True, fill='both')
        self.list_listbox.bind('<<ListboxSelect>>', self.repopulate_categories)

        # Create 'Hierarchy' tab with a Treeview
        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(self.hierarchy_frame)
        self.hierarchy_tree.pack(expand=True, fill='both')
        self.hierarchy_tree.insert('', 'end', text='Root Node')
        parent_node = self.hierarchy_tree.insert('', 'end', text='Parent Node 1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.2')
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.repopulate_categories)

        # Add Radiobuttons for Class or Instance selection
        self.selection_var = tk.StringVar(value='class')
        self.selection_var.trace_add('write', lambda name, index, operation: self.switch_side())
        self.class_radiobutton = tk.Radiobutton(self.frame, text='Class', variable=self.selection_var, value='class')
        self.instance_radiobutton = tk.Radiobutton(self.frame, text='Instance', variable=self.selection_var, value='instance')
        self.class_radiobutton.grid(row=0, column=0, sticky='w')
        self.instance_radiobutton.grid(row=1, column=0, sticky='w')       
        
        self.event_queue.subscribe('RepopulateClasses', self.repopulate)

    def switch_side(self):
        self.event_queue.publish('SelectedClassChanged', self.selected_class, self.show_instance_side)

    @property
    def show_instance_side(self):
        return self.selection_var.get() == 'instance'  

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                # Handle selection from a Listbox
                selected_index = widget.curselection()[0]
                self.selected_class = widget.get(selected_index)
            elif isinstance(widget, ttk.Treeview):
                # Handle selection from a Treeview
                selected_item_id = widget.selection()[0]
                self.selected_class = widget.item(selected_item_id, 'text')

            self.event_queue.publish('SelectedClassChanged', self.selected_class, self.show_instance_side)
        except IndexError:
            pass
        
    def repopulate(self, selected_package):
        # Repopulate hierarchy_tree with new options based on the selected package
        self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
        parent_node = self.hierarchy_tree.insert('', 'end', text=f'{selected_package} Parent Node 1')
        self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.1')
        self.hierarchy_tree.insert(parent_node, 'end', text=f'{selected_package} Child Node 1.2')

        # Repopulate list_listbox with new options based on the selected package
        self.list_listbox.delete(0, tk.END)
        for class_name in self.browser_window.gemstone_session_record.get_classes_in_category(selected_package):
            self.list_listbox.insert(tk.END, class_name)

        # Always select the 'List' tab in the classes_notebook after repopulating
        self.classes_notebook.select(self.list_frame)
        
class CategorySelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        self.browser_window = parent
        self.selected_class = None
        self.selected_category = None
        self.show_instance_side = None
        self.categories_listbox = tk.Listbox(self.frame)
        self.categories_listbox.pack(expand=True, fill='both')
        self.categories_listbox.bind('<<ListboxSelect>>', self.repopulate_class_and_instance)
        
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

    def repopulate_class_and_instance(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            self.selected_category = selected_listbox.get(selected_index)

            self.event_queue.publish('SelectedCategoryChanged', self.selected_class, self.selected_category, self.show_instance_side)
        except IndexError:
            pass
        
    def repopulate(self, selected_class, show_instance_side):
        self.show_instance_side = show_instance_side
        self.selected_class = selected_class
        self.categories_listbox.delete(0, tk.END)
        for category in self.browser_window.gemstone_session_record.get_categories_in_class(self.selected_class, self.show_instance_side):
            self.categories_listbox.insert(tk.END, category)

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        self.browser_window = parent

        # Create 'Class' tab with a listbox
        self.methods_listbox = tk.Listbox(self.frame)
        self.methods_listbox.pack(expand=True, fill='both')
        self.methods_listbox.insert(0, 'Class Option 1', 'Class Option 2', 'Class Option 3')
        self.methods_listbox.bind('<<ListboxSelect>>', self.populate_text_editor)

        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        
    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            self.selected_method = selected_listbox.get(selected_index)

            self.event_queue.publish('MethodSelected', self.selected_class, self.selected_category, self.show_instance_side, self.selected_method)
        except IndexError:
            pass
        
    def repopulate(self, selected_class, selected_category, show_instance_side):
        self.selected_class = selected_class
        self.selected_category = selected_category
        self.show_instance_side = show_instance_side
        self.methods_listbox.delete(0, tk.END)
        for selector in self.browser_window.gemstone_session_record.get_selectors_in_class(self.selected_class, self.selected_category, self.show_instance_side):
            self.methods_listbox.insert(tk.END, selector)

            
class MethodEditor(FramedWidget):
    def __init__(self, parent, event_queue, row, column, colspan=1):
        super().__init__(parent, event_queue, row, column, colspan=colspan)

        self.browser_window = parent
        
        # Add a notebook to editor_area_widget
        self.editor_notebook = ttk.Notebook(self.frame)
        self.editor_notebook.pack(expand=True, fill='both')

        # Bind right-click event to the notebook for context menu
        self.editor_notebook.bind('<Button-3>', self.open_tab_menu)

        # Dictionary to keep track of open tabs
        self.open_tabs = {}  # Format: {(class_name, show_instance_side, method_symbol): tab_reference}

        self.event_queue.subscribe('MethodSelected', self.open_method)

    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)
        
    def open_tab_menu(self, event):
        # Identify which tab was clicked
        tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))

        matching_keys = [key for key, value in self.open_tabs.items() if value == self.get_tab(tab_index)]
        key_to_use = matching_keys[0] if matching_keys else None

        if key_to_use:
            # Create a context menu for the tab
            menu = tk.Menu(self.browser_window, tearoff=0)
            menu.add_command(label="Close", command=lambda: self.close_tab(key_to_use))
            menu.add_command(label="Save", command=lambda: self.save_tab(key_to_use))
            menu.post(event.x_root, event.y_root)

    def save_tab(self, key):
        # Placeholder for save functionality
        print(f"Saving content of tab: {key}")

    def close_tab(self, key):
        print(f"Closing content of tab: {key}")
        tab_id = self.open_tabs[key]
        self.editor_notebook.forget(tab_id)
        if key in self.open_tabs:
            del self.open_tabs[key]

    def open_method(self, selected_class, selected_category, show_instance_side, method_symbol):
        # Check if tab already exists using open_tabs dictionary
        if (selected_class, show_instance_side, method_symbol) in self.open_tabs:
            self.editor_notebook.select(self.open_tabs[(selected_class, show_instance_side, method_symbol)])
            return

        # Create a new tab with a text editor containing the selected text
        new_tab = ttk.Frame(self.editor_notebook)
        text_editor = tk.Text(new_tab, wrap='word')
        text_editor.pack(expand=True, fill='both')
        text_editor.insert(tk.END, method_symbol)

        self.editor_notebook.add(new_tab, text=method_symbol)
        self.editor_notebook.select(new_tab)

        # Add the tab to open_tabs dictionary
        self.open_tabs[(selected_class, show_instance_side, method_symbol)] = new_tab


            
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
        self.stone_name_entry.insert(0, 'gs64stone')
        self.stone_name_entry.grid(column=1,row=2)
        
        ttk.Label(self, text="Netldi name:").grid(column=0,row=3)
        self.netldi_name_entry = ttk.Entry(self)
        self.netldi_name_entry.insert(0, 'gs64-ldi')
        self.netldi_name_entry.grid(column=1,row=3)
        
        ttk.Label(self, text="RPC host name:").grid(column=0,row=4)
        self.rpc_hostname_entry = ttk.Entry(self)
        self.rpc_hostname_entry.insert(0, 'localhost')
        self.rpc_hostname_entry.grid(column=1,row=4)

        # Login button
        ttk.Button(self, text="Login", command=self.attempt_login).grid(column=0,row=5,columnspan=2)

    def attempt_login(self):
        if self.error_label:
            self.error_label.destroy()

        username = self.username_entry.get()
        password = self.password_entry.get()
        stone_name = self.stone_name_entry.get()
        netldi_name = self.netldi_name_entry.get()
        rpc_hostname = self.rpc_hostname_entry.get()

        try:
            gemstone_session_record = GemstoneSessionRecord.log_in(username, password, rpc_hostname, stone_name, netldi_name)
            self.parent.event_queue.publish('LoggedInSuccessfully', gemstone_session_record)
        except DomainException as ex:
            self.error_label = ttk.Label(self, text=str(ex), foreground="red")
            self.error_label.grid(column=0,row=6,columnspan=2)           


if __name__ == "__main__":
    app = Swordfish()
    app.mainloop()
