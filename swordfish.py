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

#    @exposed
    # def fields(self, fields):
    #     class_category_choices = [Choice(category, Field(label=category)) for category in self.class_categories]
    #     fields.selected_class_category = MultiChoiceField(class_category_choices, label='Class category')
        
    #     def class_choices():
    #         return [Choice(gemstone_class, Field(label=gemstone_class)) for gemstone_class in self.current_classes]
        
    #     fields.selected_class = MultiChoiceField(class_choices, label='Class')
        
    #     def method_category_choices():
    #         return [Choice(category, Field(label=category)) for category in self.current_categories]
        
    #     fields.selected_method_category = MultiChoiceField(method_category_choices, label='Category')
        
    #     def method_choices():
    #         return [Choice(method, Field(label=method)) for method in self.current_methods]
        
    #     fields.selected_method = MultiChoiceField(method_choices, label='Method')

    # @exposed('log_out')
    # def events(self, events):
    #     events.log_out = Event(label='Log out', action=Action(self.log_out))

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
        
    def get_categories_in_class(self, class_name):
        if not class_name:
            return
        yield from [i.to_py for i in self.gemstone_session.resolve_symbol(class_name).categoryNames().asSortedCollection()]

    def get_selectors_in_class(self, class_name, method_category):
        if not class_name or not method_category:
            return
        
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        try:
            selectors = gemstone_class.selectorsIn(method_category).asSortedCollection()
        except GemstoneError:
            return
        
        yield from [i.to_py for i in selectors]




class EventBoard:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event, callback):
        if event not in self.subscribers:
            self.subscribers[event] = []
        self.subscribers[event].append(callback)

    def publish(self, event, *args, **kwargs):
        if event in self.subscribers:
            for callback in self.subscribers[event]:
                callback(*args, **kwargs)

                
class Swordfish(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Swordfish")
        self.geometry("800x600")
        self.events = EventBoard()

        self.notebook = None
        self.logged_in = False
        self.gemstone_session_record = None

        self.events.subscribe('logged_in_successfully', self.log_in)
        self.events.subscribe('logged_in_successfully', self.show_main_app)
        self.events.subscribe('logged_out', self.show_login_screen)
        
        self.create_menu()
        self.show_login_screen()

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
        
        self.events.subscribe('logged_in_successfully', self.update_session_menu)
        self.events.subscribe('logged_out', self.update_session_menu)

    def update_session_menu(self, gemstone_session_record=None):
        self.session_menu.delete(0, tk.END)
        if self.logged_in:
            self.session_menu.add_command(label="Logout", command=self.logout)
        else:
            self.session_menu.add_command(label="Login", command=self.show_login_screen)

    def log_in(self, gemstone_session_record):
        self.gemstone_session_record = gemstone_session_record
        self.logged_in = True
        
    def logout(self):
        self.logged_in = False
        self.events.publish('logged_out')
            
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
        browser_tab = BrowserWindow(self.notebook, self.gemstone_session_record)
        self.notebook.add(browser_tab, text="Browser Window")


class FramedWidget:
    def __init__(self, parent, row, column, colspan=1):
        self.frame = ttk.Frame(parent, borderwidth=2, relief="sunken")
        self.frame.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

        
class PackageSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=colspan)

        self.browser_window = parent
        self.packages_listbox = tk.Listbox(self.frame)
        self.packages_listbox.pack(expand=True, fill='both')
        for package in self.browser_window.gemstone_session_record.class_categories:
            self.packages_listbox.insert(tk.END, package)
        self.packages_listbox.bind('<<ListboxSelect>>', self.browser_window.repopulate_hierarchy_and_list)

class ClassSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=colspan)
        
        self.browser_window = parent
        self.classes_notebook = ttk.Notebook(self.frame)
        self.classes_notebook.pack(expand=True, fill='both')

        # Create 'List' tab with a listbox
        self.list_frame = ttk.Frame(self.classes_notebook)
        self.classes_notebook.add(self.list_frame, text='List')
        self.list_listbox = tk.Listbox(self.list_frame)
        self.list_listbox.pack(expand=True, fill='both')
        self.list_listbox.bind('<<ListboxSelect>>', self.browser_window.repopulate_categories)

        # Create 'Hierarchy' tab with a Treeview
        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(self.hierarchy_frame)
        self.hierarchy_tree.pack(expand=True, fill='both')
        self.hierarchy_tree.insert('', 'end', text='Root Node')
        parent_node = self.hierarchy_tree.insert('', 'end', text='Parent Node 1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.1')
        self.hierarchy_tree.insert(parent_node, 'end', text='Child Node 1.2')
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.browser_window.repopulate_categories)

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
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=colspan)

        self.browser_window = parent
        self.categories_listbox = tk.Listbox(self.frame)
        self.categories_listbox.pack(expand=True, fill='both')
        self.categories_listbox.insert(0, "Category 1", "Category 2", "Category 3")
        self.categories_listbox.bind('<<ListboxSelect>>', lambda event: self.browser_window.repopulate_class_and_instance(self.selected_class, event))
        
    def repopulate(self, selected_class):
        self.selected_class = selected_class
        self.categories_listbox.delete(0, tk.END)
        for category in self.browser_window.gemstone_session_record.get_categories_in_class(selected_class):
            self.categories_listbox.insert(tk.END, category)

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=colspan)

        self.browser_window = parent

        # Add a notebook with 2 tabs to methods_widget
        self.methods_notebook = ttk.Notebook(self.frame)
        self.methods_notebook.pack(expand=True, fill='both')

        # Create 'Class' tab with a listbox
        self.class_frame = ttk.Frame(self.methods_notebook)
        self.methods_notebook.add(self.class_frame, text='Class')
        self.class_listbox = tk.Listbox(self.class_frame)
        self.class_listbox.pack(expand=True, fill='both')
        self.class_listbox.insert(0, 'Class Option 1', 'Class Option 2', 'Class Option 3')
        self.class_listbox.bind('<<ListboxSelect>>', self.browser_window.populate_text_editor)

        # Create 'Instance' tab with a listbox
        self.instance_frame = ttk.Frame(self.methods_notebook)
        self.methods_notebook.add(self.instance_frame, text='Instance')
        self.instance_listbox = tk.Listbox(self.instance_frame)
        self.instance_listbox.pack(expand=True, fill='both')
        self.instance_listbox.bind('<<ListboxSelect>>', self.browser_window.populate_text_editor)

    def repopulate(self, selected_class, selected_category):
        # Repopulate class_listbox with new options based on the selected category
        self.class_listbox.delete(0, tk.END)
        for i in range(1, 4):
            self.class_listbox.insert(tk.END, f"{selected_category} Class Option {i}")

        # Repopulate instance_listbox with new options based on the selected category
        self.instance_listbox.delete(0, tk.END)
        for i in range(1, 4):
            self.instance_listbox.insert(tk.END, f"{selected_category} Instance Option {i}")

class MethodEditor(FramedWidget):
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=colspan)

        self.browser_window = parent
        
        # Add a notebook to editor_area_widget
        self.editor_notebook = ttk.Notebook(self.frame)
        self.editor_notebook.pack(expand=True, fill='both')

        # Bind right-click event to the notebook for context menu
        self.editor_notebook.bind('<Button-3>', self.open_tab_menu)

        # Dictionary to keep track of open tabs
        self.open_tabs = {}

    def open_tab_menu(self, event):
        # Identify which tab was clicked
        tab_id = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
        tab_text = self.editor_notebook.tab(tab_id, "text")

        # Create a context menu for the tab
        menu = tk.Menu(self.browser_window, tearoff=0)
        menu.add_command(label="Close", command=lambda: self.close_tab(tab_id, tab_text))
        menu.add_command(label="Save", command=lambda: self.save_tab(tab_id))
        menu.post(event.x_root, event.y_root)

    def save_tab(self, tab_id):
        # Placeholder for save functionality
        print(f"Saving content of tab: {self.editor_notebook.tab(tab_id, 'text')}")

    def close_tab(self, tab_id, key):
        self.editor_notebook.forget(tab_id)
        if key in self.open_tabs:
            del self.open_tabs[key]
            
    def open_method(self, method_symbol):
        # Check if tab already exists using open_tabs dictionary
        if method_symbol in self.open_tabs:
            self.editor_notebook.select(self.open_tabs[method_symbol])
            return

        # Create a new tab with a text editor containing the selected text
        new_tab = ttk.Frame(self.editor_notebook)
        text_editor = tk.Text(new_tab, wrap='word')
        text_editor.pack(expand=True, fill='both')
        text_editor.insert(tk.END, method_symbol)

        self.editor_notebook.add(new_tab, text=method_symbol)
        self.editor_notebook.select(new_tab)

        # Add the tab to open_tabs dictionary
        self.open_tabs[method_symbol] = new_tab


            
class BrowserWindow(ttk.Frame):
    def __init__(self, parent, gemstone_session_record):
        super().__init__(parent)

        self.gemstone_session_record = gemstone_session_record
        
        self.packages_widget = PackageSelection(self, 0, 0)
        self.classes_widget = ClassSelection(self, 0, 1)
        self.categories_widget = CategorySelection(self, 0, 2)
        self.methods_widget = MethodSelection(self, 0, 3)
        self.editor_area_widget = MethodEditor(self, 1, 0, colspan=4)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.columnconfigure(3, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    def repopulate_hierarchy_and_list(self, event):
        try:
            selected_listbox = event.widget
            selected_index = selected_listbox.curselection()[0]
            selected_package = selected_listbox.get(selected_index)

            self.classes_widget.repopulate(selected_package)
        except IndexError:
            pass

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                # Handle selection from a Listbox
                selected_index = widget.curselection()[0]
                selected_item = widget.get(selected_index)
            elif isinstance(widget, ttk.Treeview):
                # Handle selection from a Treeview
                selected_item_id = widget.selection()[0]
                selected_item = widget.item(selected_item_id, 'text')

            self.categories_widget.repopulate(selected_item)
        except IndexError:
            pass
        
    def repopulate_class_and_instance(self, selected_class, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_category = selected_listbox.get(selected_index)

            self.methods_widget.repopulate(selected_class, selected_category)
        except IndexError:
            pass

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_text = selected_listbox.get(selected_index)

            self.editor_area_widget.open_method(selected_text)
        except IndexError:
            pass
    


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
        except DomainException as ex:
            gemstone_session_record = None
            self.error_label = ttk.Label(self, text=str(ex), foreground="red")
            self.error_label.grid(column=0,row=6,columnspan=2)

        if gemstone_session_record:
            self.parent.events.publish('logged_in_successfully', gemstone_session_record)


if __name__ == "__main__":
    app = Swordfish()
    app.mainloop()
