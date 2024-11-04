import tkinter as tk
from tkinter import ttk

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

class MyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Swordfish")
        self.geometry("800x600")
        self.events = EventBoard()

        self.notebook = None
        self.logged_in = False

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

    def update_session_menu(self):
        self.session_menu.delete(0, tk.END)
        if self.logged_in:
            self.session_menu.add_command(label="Logout", command=self.logout)
        else:
            self.session_menu.add_command(label="Login", command=self.show_login_screen)

    def log_in(self):
        self.logged_in = True
        self.events.publish('logged_in_successfully')
        
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

    def show_main_app(self):
        self.clear_widgets()

        self.create_notebook()
        self.add_browser_tab()

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both")

    def add_browser_tab(self):
        browser_tab = BrowserWindow(self.notebook)
        self.notebook.add(browser_tab, text="Browser Window")


class FramedWidget:
    def __init__(self, parent, row, column, colspan=1):
        self.frame = ttk.Frame(parent, borderwidth=2, relief="sunken")
        self.frame.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

        
class PackageSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=1)

        self.browser_window = parent
        self.packages_listbox = tk.Listbox(self.frame)
        self.packages_listbox.pack(expand=True, fill='both')
        self.packages_listbox.insert(0, "Package 1", "Package 2", "Package 3")
        self.packages_listbox.bind('<<ListboxSelect>>', self.browser_window.repopulate_hierarchy_and_list)

class ClassSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=1)
        
        self.browser_window = parent
        self.classes_notebook = ttk.Notebook(self.frame)
        self.classes_notebook.pack(expand=True, fill='both')

        # Create 'List' tab with a listbox
        self.list_frame = ttk.Frame(self.classes_notebook)
        self.classes_notebook.add(self.list_frame, text='List')
        self.list_listbox = tk.Listbox(self.list_frame)
        self.list_listbox.pack(expand=True, fill='both')
        self.list_listbox.insert(0, 'List Option 1', 'List Option 2', 'List Option 3')
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
        for i in range(1, 4):
            self.list_listbox.insert(tk.END, f'{selected_package} List Option {i}')

        # Always select the 'List' tab in the classes_notebook after repopulating
        self.classes_notebook.select(self.list_frame)
        
class CategorySelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=1)

        self.browser_window = parent
        self.categories_listbox = tk.Listbox(self.frame)
        self.categories_listbox.pack(expand=True, fill='both')
        self.categories_listbox.insert(0, "Category 1", "Category 2", "Category 3")
        self.categories_listbox.bind('<<ListboxSelect>>', self.browser_window.repopulate_class_and_instance)
        
    def repopulate(self, selected_class):
        self.categories_listbox.delete(0, tk.END)
        for i in range(1, 4):
            self.categories_listbox.insert(tk.END, f"{selected_class} New Category {i}")

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, row, column, colspan=1):
        super().__init__(parent, row, column, colspan=1)

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
        self.instance_listbox.insert(0, 'Instance Option 1', 'Instance Option 2', 'Instance Option 3')
        self.instance_listbox.bind('<<ListboxSelect>>', self.browser_window.populate_text_editor)

    def repopulate(self, selected_category):
        # Repopulate class_listbox with new options based on the selected category
        self.class_listbox.delete(0, tk.END)
        for i in range(1, 4):
            self.class_listbox.insert(tk.END, f"{selected_category} Class Option {i}")

        # Repopulate instance_listbox with new options based on the selected category
        self.instance_listbox.delete(0, tk.END)
        for i in range(1, 4):
            self.instance_listbox.insert(tk.END, f"{selected_category} Instance Option {i}")

        
class BrowserWindow(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.packages_widget = PackageSelection(self, 0, 0)
        self.classes_widget = ClassSelection(self, 0, 1)
        self.categories_widget = CategorySelection(self, 0, 2)
        self.methods_widget = MethodSelection(self, 0, 3)
        

        # Row 2 - 1 Column
        self.editor_area_widget = FramedWidget(self, 1, 0, colspan=4)

        # Add a notebook to editor_area_widget
        self.editor_notebook = ttk.Notebook(self.editor_area_widget.frame)
        self.editor_notebook.pack(expand=True, fill='both')

        # Bind right-click event to the notebook for context menu
        self.editor_notebook.bind('<Button-3>', self.open_tab_menu)

        # Dictionary to keep track of open tabs
        self.open_tabs = {}

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)
        self.columnconfigure(3, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    def open_tab_menu(self, event):
        # Identify which tab was clicked
        tab_id = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
        tab_text = self.editor_notebook.tab(tab_id, "text")

        # Create a context menu for the tab
        menu = tk.Menu(self, tearoff=0)
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
        
    def repopulate_class_and_instance(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_category = selected_listbox.get(selected_index)

            self.methods_widget.repopulate(selected_category)
        except IndexError:
            pass

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_text = selected_listbox.get(selected_index)

            # Check if tab already exists using open_tabs dictionary
            if selected_text in self.open_tabs:
                self.editor_notebook.select(self.open_tabs[selected_text])
                return

            # Create a new tab with a text editor containing the selected text
            new_tab = ttk.Frame(self.editor_notebook)
            text_editor = tk.Text(new_tab, wrap='word')
            text_editor.pack(expand=True, fill='both')
            text_editor.insert(tk.END, selected_text)

            self.editor_notebook.add(new_tab, text=selected_text)
            self.editor_notebook.select(new_tab)

            # Add the tab to open_tabs dictionary
            self.open_tabs[selected_text] = new_tab
            
        except IndexError:
            pass
    


class LoginFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.error_label = None

        # Username label and entry
        ttk.Label(self, text="Username:").pack(pady=10)
        self.username_entry = ttk.Entry(self)
        self.username_entry.pack(pady=5)

        # Password label and entry
        ttk.Label(self, text="Password:").pack(pady=10)
        self.password_entry = ttk.Entry(self, show="*")
        self.password_entry.pack(pady=5)

        # Login button
        ttk.Button(self, text="Login", command=self.attempt_login).pack(pady=20)

    def attempt_login(self):
        if self.error_label:
            self.error_label.destroy()

        username = self.username_entry.get()
        password = self.password_entry.get()
        if username == "user" and password == "pw":
            self.parent.log_in()
        else:
            self.error_label = ttk.Label(self, text="Invalid credentials, please try again.", foreground="red")
            self.error_label.pack(pady=10)

if __name__ == "__main__":
    app = MyApp()
    app.mainloop()
