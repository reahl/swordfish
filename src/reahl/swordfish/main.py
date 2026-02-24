#!/var/local/gemstone/venv/wonka/bin/python

import json
import logging
import re
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
import weakref
from tkinter import ttk

from reahl.ptongue import GemstoneError, LinkedSession, RPCSession
from reahl.swordfish.gemstone import GemstoneBrowserSession
from reahl.swordfish.gemstone import GemstoneDebugSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException


class DomainException(Exception):
    pass

class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.gemstone_browser_session = GemstoneBrowserSession(gemstone_session)
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
        self.select_method_category(None)

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
        return self.gemstone_browser_session.class_organizer

    @property
    def class_categories(self):
        yield from self.gemstone_browser_session.list_packages()

    def create_and_install_package(self, package_name):
        self.gemstone_browser_session.create_and_install_package(package_name)

    def create_class(
        self,
        class_name,
        superclass_name='Object',
        in_dictionary=None,
    ):
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            selected_dictionary = self.selected_package or 'UserGlobals'
        self.gemstone_browser_session.create_class(
            class_name=class_name,
            superclass_name=superclass_name,
            in_dictionary=selected_dictionary,
        )
        
    def get_classes_in_category(self, category):
        yield from self.gemstone_browser_session.list_classes(category)
        
    def get_categories_in_class(self, class_name, show_instance_side):
        categories = self.gemstone_browser_session.list_method_categories(
            class_name,
            show_instance_side,
        )
        if categories and categories[0] == 'all':
            categories = categories[1:]
        yield from categories

    def get_selectors_in_class(self, class_name, method_category, show_instance_side):
        yield from self.gemstone_browser_session.list_methods(
            class_name,
            method_category,
            show_instance_side,
        )

    def get_method(self, class_name, show_instance_side, method_symbol):
        try:
            return self.gemstone_browser_session.get_compiled_method(
                class_name,
                method_symbol,
                show_instance_side,
            )
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
        selected_method_category = self.gemstone_browser_session.get_method_category(
            class_name,
            method_symbol,
            show_instance_side,
        )
        self.select_package(selected_package)
        self.select_class(class_name)
        self.select_instance_side(show_instance_side)
        self.select_method_category(selected_method_category)
        self.select_method_symbol(method_symbol)
        
    def get_current_methods(self):
        return list(self.get_selectors_in_class(self.selected_class, self.selected_method_category, self.show_instance_side))
        
    def find_class_names_matching(self, search_input):
        yield from self.gemstone_browser_session.find_classes(search_input)
        
    def find_selectors_matching(self, search_input):
        yield from self.gemstone_browser_session.find_selectors(search_input)

    def find_implementors_of_method(self, method_name):
        yield from [
            (
                implementor['class_name'],
                not implementor['show_instance_side'],
            )
            for implementor in self.gemstone_browser_session.find_implementors(
                method_name
            )
        ]

    def find_senders_of_method(self, method_name):
        sender_search_result = self.gemstone_browser_session.find_senders(
            method_name
        )
        yield from [
            (
                sender['class_name'],
                sender['show_instance_side'],
                sender['method_selector'],
            )
            for sender in sender_search_result['senders']
        ]

    def method_sends(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_sends(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_structure_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_structure_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_control_flow_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_control_flow_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_ast(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_ast(
            class_name,
            method_selector,
            show_instance_side,
        )

    def preview_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        return self.gemstone_browser_session.method_rename_preview(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )

    def apply_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        return self.gemstone_browser_session.apply_method_rename(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )

    def preview_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        return self.gemstone_browser_session.method_move_preview(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
        )

    def apply_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
        overwrite_target_method=False,
        delete_source_method=True,
    ):
        return self.gemstone_browser_session.apply_method_move(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
            overwrite_target_method=overwrite_target_method,
            delete_source_method=delete_source_method,
        )

    def preview_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        return self.gemstone_browser_session.method_add_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )

    def apply_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        return self.gemstone_browser_session.apply_method_add_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )

    def preview_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        rewrite_source_senders=False,
    ):
        return self.gemstone_browser_session.method_remove_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            rewrite_source_senders=rewrite_source_senders,
        )

    def apply_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        overwrite_new_method=False,
        rewrite_source_senders=False,
    ):
        return self.gemstone_browser_session.apply_method_remove_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            overwrite_new_method=overwrite_new_method,
            rewrite_source_senders=rewrite_source_senders,
        )

    def preview_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
    ):
        return self.gemstone_browser_session.method_extract_preview(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        )

    def apply_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
        overwrite_new_method=False,
    ):
        return self.gemstone_browser_session.apply_method_extract(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
            overwrite_new_method=overwrite_new_method,
        )

    def preview_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
    ):
        return self.gemstone_browser_session.method_inline_preview(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
        )

    def apply_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
        delete_inlined_method=False,
    ):
        return self.gemstone_browser_session.apply_method_inline(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
            delete_inlined_method=delete_inlined_method,
        )
        
    def update_method_source(self, selected_class, show_instance_side, method_symbol, source):
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
        )

    def run_code(self, source):
        return self.gemstone_browser_session.run_code(source)

    def run_gemstone_tests(self, class_name):
        return self.gemstone_browser_session.run_gemstone_tests(class_name)

    def run_test_method(self, class_name, method_selector):
        return self.gemstone_browser_session.run_test_method(class_name, method_selector)

    def debug_test_method(self, class_name, method_selector):
        return self.gemstone_browser_session.debug_test_method(class_name, method_selector)
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
            self.file_menu.add_command(label="Senders", command=self.show_senders_dialog)
            self.file_menu.add_command(label="Run", command=self.show_run_dialog)
            self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

    def show_find_dialog(self):
        self.parent.open_find_dialog()
        
    def show_implementors_dialog(self):
        self.parent.open_implementors_dialog()

    def show_senders_dialog(self):
        self.parent.open_senders_dialog()

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


class SendersDialog(tk.Toplevel):
    def __init__(self, parent, method_name=None):
        super().__init__(parent)
        self.title("Senders")
        self.geometry("500x500")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent
        self.sender_results = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ttk.Label(self, text="Method Name:").grid(
            row=0,
            column=0,
            padx=10,
            pady=10,
            sticky='w',
        )
        self.method_entry = ttk.Entry(self)
        self.method_entry.grid(
            row=0,
            column=1,
            columnspan=2,
            padx=10,
            pady=10,
            sticky='ew',
        )
        if method_name:
            self.method_entry.insert(0, method_name)

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=1, column=0, columnspan=3, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.find_button = ttk.Button(
            self.button_frame,
            text="Find",
            command=self.find_senders,
        )
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(
            self.button_frame,
            text="Cancel",
            command=self.destroy,
        )
        self.cancel_button.grid(row=0, column=1, padx=5)

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)
        self.results_listbox.grid(
            row=2,
            column=0,
            columnspan=3,
            padx=10,
            pady=10,
            sticky='nsew',
        )

        self.find_senders()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def find_senders(self):
        method_name = self.method_entry.get()
        self.sender_results = []
        if method_name:
            self.sender_results = list(
                self.gemstone_session_record.find_senders_of_method(method_name)
            )

        self.results_listbox.delete(0, tk.END)
        for class_name, show_instance_side, method_selector in self.sender_results:
            side_text = '' if show_instance_side else ' class'
            self.results_listbox.insert(
                tk.END,
                f'{class_name}{side_text}>>{method_selector}',
            )

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_sender = self.sender_results[selected_index]
            class_name, show_instance_side, method_selector = selected_sender
            self.parent.handle_sender_selection(
                class_name,
                show_instance_side,
                method_selector,
            )
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
        self.run_tab = None
        
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
        self.run_tab = None

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
        self.notebook.select(self.debugger_tab)
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
        self.gemstone_session_record.jump_to_method(class_name, show_instance_side, method_symbol)
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        self.gemstone_session_record.jump_to_method(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')

    def run_code(self, source=""):
        if self.run_tab is None or not self.run_tab.winfo_exists():
            self.run_tab = RunTab(self.notebook, self)
            self.notebook.add(self.run_tab, text='Run')
        self.notebook.select(self.run_tab)
        run_immediately = bool(source and source.strip())
        self.run_tab.present_source(source, run_immediately=run_immediately)
        
    def open_find_dialog(self):
        FindDialog(self)
        
    def open_implementors_dialog(self, method_symbol=None):
        ImplementorsDialog(self, method_name=method_symbol)

    def open_senders_dialog(self, method_symbol=None):
        SendersDialog(self, method_name=method_symbol)
        
        
class RunTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.last_exception = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(5, weight=1)

        self.source_label = ttk.Label(self, text='Source Code:')
        self.source_label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 0))

        self.source_text = tk.Text(self, height=10)
        self.source_text.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=(0, 10))
        self.button_frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(
            self.button_frame,
            text='Run',
            command=self.run_code_from_editor,
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5))

        self.close_button = ttk.Button(
            self.button_frame,
            text='Close Tab',
            command=self.close_tab,
        )
        self.close_button.grid(row=0, column=1, padx=(0, 5))

        self.status_label = ttk.Label(self, text='Ready')
        self.status_label.grid(row=3, column=0, sticky='w', padx=10)

        self.result_label = ttk.Label(self, text='Result:')
        self.result_label.grid(row=4, column=0, sticky='nw', padx=10, pady=(10, 0))

        self.result_text = tk.Text(self, height=7, state='disabled')
        self.result_text.grid(row=5, column=0, sticky='nsew', padx=10, pady=(0, 10))

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record

    def present_source(self, source, run_immediately=False):
        if source and source.strip():
            self.source_text.delete('1.0', tk.END)
            self.source_text.insert(tk.END, source)
        if run_immediately:
            self.run_code_from_editor()

    def run_code_from_editor(self):
        self.status_label.config(text='Running...')
        self.clear_debug_button()
        self.last_exception = None
        try:
            code_to_run = self.source_text.get('1.0', tk.END).strip()
            result = self.gemstone_session_record.run_code(code_to_run)
            self.on_run_complete(result)
        except GemstoneError as gemstone_exception:
            self.on_run_error(gemstone_exception)

    def on_run_complete(self, result):
        self.status_label.config(text='Completed successfully')
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert(tk.END, result.asString().to_py)
        self.result_text.config(state='disabled')

    def on_run_error(self, exception):
        self.last_exception = exception
        self.status_label.config(text=f'Error: {str(exception)}')
        self.debug_button = ttk.Button(
            self.button_frame,
            text='Debug',
            command=self.open_debugger,
        )
        self.debug_button.grid(row=0, column=2, sticky='w')

    def clear_debug_button(self):
        if hasattr(self, 'debug_button') and self.debug_button is not None:
            self.debug_button.destroy()
            self.debug_button = None

    def open_debugger(self):
        if self.last_exception is None:
            return
        self.application.open_debugger(self.last_exception)

    def close_tab(self):
        if self.application.run_tab is self:
            self.application.run_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()


class JsonResultDialog(tk.Toplevel):
    def __init__(self, parent, title, result_payload):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
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

    def show_test_result(self, result):
        if result['has_passed']:
            messagebox.showinfo('Test Result', f"Passed ({result['run_count']} run)")
        else:
            lines = [f"Failures: {result['failure_count']}, Errors: {result['error_count']}"]
            lines.extend(result['failures'])
            lines.extend(result['errors'])
            messagebox.showerror('Test Result', '\n'.join(lines))

class InteractiveSelectionList(ttk.Frame):
    def __init__(self, parent, get_all_entries, get_selected_entry, set_selected_to):
        super().__init__(parent)

        self.get_all_entries = get_all_entries
        self.get_selected_entry = get_selected_entry
        self.set_selected_to = set_selected_to
        self.synchronizing_selection = False

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, columnspan=2, sticky='ew')

        # Packages listbox to show filtered packages with scrollbar
        self.selection_listbox = tk.Listbox(self, selectmode=tk.SINGLE, exportselection=False)
        self.selection_listbox.grid(row=1, column=0, sticky='nsew')

        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.selection_listbox.yview)
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
        self.synchronizing_selection = True
        try:
            self.all_entries = self.get_all_entries()
            self.filter_var.set('')
            self.update_filter()

            selected_indices = self.selection_listbox.curselection()
            if selected_indices:
                index = selected_indices[0]
                if not self.selection_listbox.bbox(index):
                    self.selection_listbox.see(index)
        finally:
            self.synchronizing_selection = False
                    
    def update_filter(self, *args):
        filter_text = self.filter_var.get().lower()
        self.selection_listbox.delete(0, tk.END)

        selected_entry = self.get_selected_entry()
        filtered_index = 0
        for entry in self.all_entries:
            if filter_text in entry.lower():
                self.selection_listbox.insert(tk.END, entry)
                if selected_entry and selected_entry == entry:
                    self.selection_listbox.selection_set(filtered_index)
                filtered_index += 1

    def handle_selection(self, event):
        if self.synchronizing_selection:
            return
        try:
            selected_listbox = event.widget
            selected_indices = selected_listbox.curselection()
            selected_index = selected_indices[-1]
            selected_entry = selected_listbox.get(selected_index)
            current_selected_entry = self.get_selected_entry()
            if selected_entry == current_selected_entry:
                return

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
        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

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

    def show_context_menu(self, event):
        idx = self.selection_list.selection_listbox.nearest(event.y)
        self.selection_list.selection_listbox.selection_clear(0, 'end')
        self.selection_list.selection_listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='Add Package', command=self.add_package)
        menu.tk_popup(event.x_root, event.y_root)

    def add_package(self):
        package_name = simpledialog.askstring('Add Package', 'Package name:')
        if not package_name:
            return
        try:
            package_name = package_name.strip()
            if not package_name:
                return
            self.gemstone_session_record.create_and_install_package(package_name)
            self.gemstone_session_record.select_package(package_name)
            self.selection_list.repopulate()
            self.event_queue.publish('SelectedPackageChanged', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Package', str(error))

            
class ClassSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.classes_notebook = ttk.Notebook(self)
        self.classes_notebook.grid(row=0, column=0, columnspan=2, sticky='nsew')

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.selection_list = InteractiveSelectionList(self, self.get_all_classes, self.get_selected_class, self.select_class)
        self.selection_list.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.selection_list, text='List')

        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.hierarchy_frame.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(
            self.hierarchy_frame,
            columns=('class_category',),
            show='tree headings',
        )
        self.hierarchy_tree.grid(row=0, column=0, sticky='nsew')
        self.hierarchy_frame.rowconfigure(0, weight=1)
        self.hierarchy_frame.columnconfigure(0, weight=1)
        self.hierarchy_tree.heading('#0', text='Class')
        self.hierarchy_tree.heading('class_category', text='Class Category')
        self.hierarchy_tree.column('#0', width=260, anchor='w')
        self.hierarchy_tree.column('class_category', width=180, anchor='w')
        self.hierarchy_item_by_class_name = {}
        self.synchronizing_hierarchy_selection = False
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.repopulate_categories)
        self.classes_notebook.bind(
            '<<NotebookTabChanged>>',
            self.handle_classes_notebook_changed,
        )

        self.selection_var = tk.StringVar(value='instance' if self.gemstone_session_record.show_instance_side else 'class')
        self.syncing_side_selection = False
        self.selection_var.trace_add('write', lambda name, index, operation: self.switch_side())
        self.class_radiobutton = tk.Radiobutton(self, text='Class', variable=self.selection_var, value='class')
        self.instance_radiobutton = tk.Radiobutton(self, text='Instance', variable=self.selection_var, value='instance')
        self.class_radiobutton.grid(column=0, row=2, sticky='w')
        self.instance_radiobutton.grid(column=1, row=2, sticky='w')
        self.show_class_definition_var = tk.BooleanVar(value=False)
        self.show_class_definition_checkbox = tk.Checkbutton(
            self,
            text='Show Class Definition',
            variable=self.show_class_definition_var,
            command=self.toggle_class_definition,
        )
        self.show_class_definition_checkbox.grid(
            column=0,
            row=3,
            columnspan=2,
            sticky='w',
        )
        self.class_definition_text = tk.Text(
            self,
            wrap='word',
            height=8,
        )
        self.class_definition_text.grid(
            column=0,
            row=4,
            columnspan=2,
            sticky='nsew',
        )
        self.class_definition_text.config(state='disabled')
        self.class_definition_text.grid_remove()

        self.rowconfigure(1, weight=0)
        self.rowconfigure(4, weight=1)

        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def switch_side(self):
        if self.syncing_side_selection:
            return
        self.gemstone_session_record.select_instance_side(self.show_instance_side)
        self.event_queue.publish('SelectedClassChanged')

    @property
    def show_instance_side(self):
        return self.selection_var.get() == 'instance'  

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                selected_index = widget.curselection()[0]
                selected_class = widget.get(selected_index)
                self.select_class(
                    selected_class,
                    selection_source='list',
                )
                return
            if isinstance(widget, ttk.Treeview):
                if self.synchronizing_hierarchy_selection:
                    return
                selected_item_id = widget.selection()[0]
                selected_class = widget.item(selected_item_id, 'text')
                class_values = widget.item(selected_item_id, 'values')
                class_category = class_values[0] if class_values else ''
                current_class = self.gemstone_session_record.selected_class
                current_package = self.gemstone_session_record.selected_package
                selected_package = class_category or current_package
                if (
                    selected_class == current_class
                    and selected_package == current_package
                ):
                    return
                self.select_class(
                    selected_class,
                    selection_source='hierarchy',
                    class_category=class_category,
                )
        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            expected_side = (
                'instance'
                if self.gemstone_session_record.show_instance_side
                else 'class'
            )
            if self.selection_var.get() != expected_side:
                self.syncing_side_selection = True
                self.selection_var.set(expected_side)
                self.syncing_side_selection = False
            self.selection_list.repopulate()
            if self.selected_tab_is_hierarchy():
                self.refresh_hierarchy_tree()
            self.refresh_class_definition()

    def selected_tab_is_hierarchy(self):
        selected_tab = self.classes_notebook.select()
        return selected_tab == str(self.hierarchy_frame)

    def handle_classes_notebook_changed(self, event):
        if event.widget.select() == str(self.hierarchy_frame):
            self.refresh_hierarchy_tree()

    def refresh_hierarchy_tree(self):
        self.synchronizing_hierarchy_selection = True
        try:
            self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
            self.hierarchy_item_by_class_name = {}
            class_names = self.get_all_classes()
            if not class_names:
                return
            class_definition_by_class_name = self.class_definition_map_for_classes(
                class_names,
            )
            superclass_by_class_name = {
                class_name: class_definition.get('superclass_name')
                for class_name, class_definition in class_definition_by_class_name.items()
            }
            children_by_parent_name = {}
            for class_name, superclass_name in superclass_by_class_name.items():
                parent_name = superclass_name
                if superclass_name not in superclass_by_class_name:
                    parent_name = None
                if parent_name not in children_by_parent_name:
                    children_by_parent_name[parent_name] = []
                children_by_parent_name[parent_name].append(class_name)
            for child_names in children_by_parent_name.values():
                child_names.sort()
            self.add_hierarchy_children(
                '',
                None,
                children_by_parent_name,
                class_definition_by_class_name,
            )
            self.reveal_selected_class_in_hierarchy()
        finally:
            self.synchronizing_hierarchy_selection = False

    def class_definition_map_for_classes(self, class_names):
        class_definition_by_class_name = {}
        classes_to_query = list(class_names)
        while classes_to_query:
            class_name = classes_to_query.pop()
            if class_name not in class_definition_by_class_name:
                class_definition = {
                    'class_name': class_name,
                    'superclass_name': None,
                    'package_name': '',
                }
                try:
                    fetched_class_definition = (
                        self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                            class_name,
                        )
                    )
                    class_definition.update(fetched_class_definition)
                except GemstoneDomainException:
                    pass
                superclass_name = class_definition.get('superclass_name')
                class_definition_by_class_name[class_name] = class_definition
                if (
                    superclass_name is not None
                    and superclass_name not in class_definition_by_class_name
                ):
                    classes_to_query.append(superclass_name)
        return class_definition_by_class_name

    def add_hierarchy_children(
        self,
        parent_item_id,
        parent_class_name,
        children_by_parent_name,
        class_definition_by_class_name,
    ):
        child_class_names = children_by_parent_name.get(parent_class_name, [])
        for child_class_name in child_class_names:
            class_definition = class_definition_by_class_name.get(
                child_class_name,
                {},
            )
            class_category = class_definition.get('package_name') or ''
            child_item_id = self.hierarchy_tree.insert(
                parent_item_id,
                'end',
                text=child_class_name,
                values=(class_category,),
            )
            self.hierarchy_item_by_class_name[child_class_name] = child_item_id
            self.add_hierarchy_children(
                child_item_id,
                child_class_name,
                children_by_parent_name,
                class_definition_by_class_name,
            )

    def reveal_selected_class_in_hierarchy(self):
        selected_class_name = self.gemstone_session_record.selected_class
        if not selected_class_name:
            return
        selected_item_id = self.hierarchy_item_by_class_name.get(selected_class_name)
        if selected_item_id is None:
            return
        parent_item_id = self.hierarchy_tree.parent(selected_item_id)
        while parent_item_id:
            self.hierarchy_tree.item(parent_item_id, open=True)
            parent_item_id = self.hierarchy_tree.parent(parent_item_id)
        self.hierarchy_tree.item(selected_item_id, open=True)
        self.hierarchy_tree.selection_set(selected_item_id)
        self.hierarchy_tree.focus(selected_item_id)
        self.hierarchy_tree.see(selected_item_id)

    def get_all_classes(self):
        selected_package = self.gemstone_session_record.selected_package
        return list(self.browser_window.gemstone_session_record.get_classes_in_category(selected_package))

    def get_selected_class(self):
        return self.gemstone_session_record.selected_class

    def select_class(
        self,
        selected_class,
        selection_source='list',
        class_category='',
    ):
        selected_package = self.gemstone_session_record.selected_package
        if selection_source == 'hierarchy':
            selected_package = class_category
            if not selected_package:
                try:
                    class_definition = (
                        self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                            selected_class,
                        )
                    )
                except (GemstoneDomainException, GemstoneError):
                    class_definition = {}
                selected_package = class_definition.get('package_name') or selected_package
            if selected_package:
                self.gemstone_session_record.select_package(selected_package)
                self.selection_list.repopulate()
        self.gemstone_session_record.select_class(selected_class)
        if selection_source == 'hierarchy':
            self.gemstone_session_record.select_method_category('all')
        self.refresh_class_definition()
        self.event_queue.publish('SelectedClassChanged', origin=self)

    def show_context_menu(self, event):
        if self.selection_list.selection_listbox.size():
            idx = self.selection_list.selection_listbox.nearest(event.y)
            self.selection_list.selection_listbox.selection_clear(0, 'end')
            self.selection_list.selection_listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='Add Class', command=self.add_class)
        menu.add_command(label='Run All Tests', command=self.run_all_tests)
        menu.tk_popup(event.x_root, event.y_root)

    def add_class(self):
        selected_package = self.gemstone_session_record.selected_package
        if not selected_package:
            messagebox.showerror('Add Class', 'Select a package first.')
            return
        class_name = simpledialog.askstring('Add Class', 'Class name:')
        if class_name is None:
            return
        class_name = class_name.strip()
        if not class_name:
            return
        superclass_name = simpledialog.askstring(
            'Add Class',
            'Superclass name:',
            initialvalue='Object',
        )
        if superclass_name is None:
            return
        superclass_name = superclass_name.strip()
        if not superclass_name:
            return
        try:
            self.gemstone_session_record.create_class(
                class_name=class_name,
                superclass_name=superclass_name,
                in_dictionary=selected_package,
            )
            self.gemstone_session_record.select_class(class_name)
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish('SelectedClassChanged', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Class', str(error))

    def toggle_class_definition(self):
        if self.show_class_definition_var.get():
            self.class_definition_text.grid()
            self.refresh_class_definition()
            return
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.config(state='disabled')
        self.class_definition_text.grid_remove()

    def formatted_class_definition(self, class_definition):
        class_name = class_definition.get('class_name') or ''
        superclass_name = class_definition.get('superclass_name') or 'Object'
        package_name = class_definition.get('package_name') or ''
        inst_var_names = class_definition.get('inst_var_names') or []
        class_var_names = class_definition.get('class_var_names') or []
        class_inst_var_names = class_definition.get('class_inst_var_names') or []
        pool_dictionary_names = class_definition.get('pool_dictionary_names') or []
        return (
            f"{superclass_name} subclass: '{class_name}'\n"
            f'    instVarNames: {self.symbol_array_literal(inst_var_names)}\n'
            f'    classVars: {self.symbol_array_literal(class_var_names)}\n'
            f'    classInstVars: {self.symbol_array_literal(class_inst_var_names)}\n'
            f'    poolDictionaries: {self.symbol_array_literal(pool_dictionary_names)}\n'
            f'    inDictionary: {package_name}'
        )

    def symbol_array_literal(self, symbol_names):
        if not symbol_names:
            return '#()'
        return '#(%s)' % ' '.join(symbol_names)

    def refresh_class_definition(self):
        if not self.show_class_definition_var.get():
            return
        class_definition_text = ''
        selected_class = self.gemstone_session_record.selected_class
        if selected_class:
            try:
                class_definition = (
                    self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        selected_class,
                    )
                )
                class_definition_text = self.formatted_class_definition(
                    class_definition,
                )
            except (GemstoneDomainException, GemstoneError):
                class_definition_text = ''
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.insert('1.0', class_definition_text)
        self.class_definition_text.config(state='disabled')

    def run_all_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        try:
            result = self.gemstone_session_record.run_gemstone_tests(class_name)
            self.show_test_result(result)
        except GemstoneError as e:
            self.browser_window.application.open_debugger(e)

                    
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
        if origin is self:
            return
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
        self.show_method_hierarchy_var = tk.BooleanVar(value=False)
        self.show_method_hierarchy_checkbox = tk.Checkbutton(
            self,
            text='Show Method Inheritance',
            variable=self.show_method_hierarchy_var,
            command=self.toggle_method_hierarchy,
        )
        self.show_method_hierarchy_checkbox.grid(row=1, column=0, sticky='w')
        self.method_hierarchy_tree = ttk.Treeview(
            self,
            show='tree',
        )
        self.method_hierarchy_tree.heading('#0', text='Class')
        self.method_hierarchy_tree.column('#0', width=240, anchor='w')
        self.method_hierarchy_tree.grid(row=2, column=0, sticky='nsew')
        self.method_hierarchy_tree.grid_remove()
        self.method_hierarchy_tree.bind(
            '<<TreeviewSelect>>',
            self.method_hierarchy_selected,
        )
        self.syncing_method_hierarchy_selection = False

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        self.event_queue.subscribe('MethodSelected', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

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
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()

    def get_all_methods(self):
        return self.gemstone_session_record.get_current_methods()

    def get_selected_method(self):
        return self.gemstone_session_record.selected_method_symbol

    def select_method(self, selected_method):
        self.gemstone_session_record.select_method_symbol(selected_method)
        if self.show_method_hierarchy_var.get():
            self.refresh_method_hierarchy()
        self.event_queue.publish('MethodSelected', origin=self)

    def toggle_method_hierarchy(self):
        if self.show_method_hierarchy_var.get():
            self.method_hierarchy_tree.grid()
            self.refresh_method_hierarchy()
        else:
            self.method_hierarchy_tree.delete(
                *self.method_hierarchy_tree.get_children(),
            )
            self.method_hierarchy_tree.grid_remove()

    def refresh_method_hierarchy(self):
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        inheritance_entries = self.method_inheritance_entries()
        parent_item_id = ''
        selected_item_id = None
        selected_class = self.gemstone_session_record.selected_class
        for inheritance_entry in inheritance_entries:
            item_id = self.method_hierarchy_tree.insert(
                parent_item_id,
                'end',
                text=inheritance_entry['class_name'],
            )
            if inheritance_entry['class_name'] == selected_class:
                selected_item_id = item_id
            parent_item_id = item_id
        if selected_item_id is None and parent_item_id:
            selected_item_id = parent_item_id
        if selected_item_id:
            self.syncing_method_hierarchy_selection = True
            self.method_hierarchy_tree.selection_set(selected_item_id)
            self.method_hierarchy_tree.focus(selected_item_id)
            self.method_hierarchy_tree.see(selected_item_id)
            self.syncing_method_hierarchy_selection = False

    def method_inheritance_entries(self):
        selected_class = self.gemstone_session_record.selected_class
        method_selector = self.gemstone_session_record.selected_method_symbol
        show_instance_side = self.gemstone_session_record.show_instance_side
        if not selected_class or not method_selector:
            return []
        superclass_chain = self.superclass_chain_for_method_inheritance(
            selected_class,
        )
        inheritance_entries = []
        for class_name in superclass_chain:
            compiled_method = self.gemstone_session_record.get_method(
                class_name,
                show_instance_side,
                method_selector,
            )
            if compiled_method is not None:
                inheritance_entries.append(
                    {
                        'class_name': class_name,
                        'method_selector': method_selector,
                    },
                )
        return inheritance_entries

    def superclass_chain_for_method_inheritance(self, class_name):
        superclass_chain = []
        current_class_name = class_name
        while current_class_name:
            superclass_chain.append(current_class_name)
            try:
                class_definition = (
                    self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        current_class_name,
                    )
                )
            except GemstoneDomainException:
                class_definition = {}
            current_class_name = class_definition.get('superclass_name')
        superclass_chain.reverse()
        return superclass_chain

    def method_hierarchy_selected(self, event):
        if self.syncing_method_hierarchy_selection:
            return
        try:
            selected_item_id = event.widget.selection()[0]
        except IndexError:
            return
        selected_class = event.widget.item(selected_item_id, 'text')
        selected_method = self.gemstone_session_record.selected_method_symbol
        if not selected_class or not selected_method:
            return
        show_instance_side = self.gemstone_session_record.show_instance_side
        if self.gemstone_session_record.gemstone_session is not None:
            self.gemstone_session_record.jump_to_method(
                selected_class,
                show_instance_side,
                selected_method,
            )
        else:
            selected_method_category = (
                self.gemstone_session_record.gemstone_browser_session.get_method_category(
                    selected_class,
                    selected_method,
                    show_instance_side,
                )
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(selected_class)
            self.gemstone_session_record.select_method_category(
                selected_method_category,
            )
            self.gemstone_session_record.select_method_symbol(selected_method)
        self.event_queue.publish('SelectedClassChanged', origin=self)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)
        self.event_queue.publish('MethodSelected', origin=self)

    def show_context_menu(self, event):
        idx = self.selection_list.selection_listbox.nearest(event.y)
        self.selection_list.selection_listbox.selection_clear(0, 'end')
        self.selection_list.selection_listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='Run Test', command=self.run_test)
        menu.add_command(label='Debug Test', command=self.debug_test)
        menu.tk_popup(event.x_root, event.y_root)

    def run_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        try:
            result = self.gemstone_session_record.run_test_method(class_name, method_selector)
            self.show_test_result(result)
        except GemstoneError as e:
            self.browser_window.application.open_debugger(e)

    def debug_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        try:
            self.gemstone_session_record.debug_test_method(class_name, method_selector)
        except GemstoneError as e:
            self.browser_window.application.open_debugger(e)

        
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
        return None

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
    def __init__(self, parent, application, tab_key=None):
        super().__init__(parent)

        self.application = application
        self.tab_key = tab_key

        self.text_editor = tk.Text(self, tabs=('4',), wrap='none')

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
        self.text_editor.configure(
            yscrollcommand=self.scrollbar_y.set,
            xscrollcommand=self.scrollbar_x.set,
        )

        self.text_editor.grid(row=0, column=0, sticky='nsew')
        self.scrollbar_y.grid(row=0, column=1, sticky='ns')
        self.scrollbar_x.grid(row=1, column=0, sticky='ew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.text_editor.tag_configure("smalltalk_keyword", foreground="blue")
        self.text_editor.tag_configure("smalltalk_comment", foreground="green")
        self.text_editor.tag_configure("smalltalk_string", foreground="orange")
        self.text_editor.tag_configure("highlight", background="darkgrey")

        self.text_editor.bind("<KeyRelease>", self.on_key_release)
        self.text_editor.bind("<Button-3>", self.open_text_menu)

        self.current_context_menu = None
        self.text_editor.bind("<Button-1>", self.close_context_menu, add="+")

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
        has_complete_context = (
            class_name is not None and method_selector is not None
        )
        if not has_complete_context:
            return None
        return (class_name, show_instance_side, method_selector)

    def selected_text(self):
        try:
            return self.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ''

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
            starts_before_or_at_cursor = (
                send_entry['start_offset'] <= cursor_offset
            )
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
            )
            self.current_context_menu.add_command(
                label='Close',
                command=self.close_current_tab,
            )
            self.current_context_menu.add_separator()
        selected_text = self.selected_text()
        if selected_text:
            self.current_context_menu.add_command(
                label='Run',
                command=lambda: self.run_selected_text(selected_text),
            )
            self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Find Implementors',
            command=self.open_implementors_from_source,
        )
        self.current_context_menu.add_command(
            label='Find Senders',
            command=self.open_senders_from_source,
        )
        self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Method Sends',
            command=self.show_method_sends,
        )
        self.current_context_menu.add_command(
            label='Method Structure',
            command=self.show_method_structure,
        )
        self.current_context_menu.add_command(
            label='Method Control Flow',
            command=self.show_method_control_flow,
        )
        self.current_context_menu.add_command(
            label='Method AST',
            command=self.show_method_ast,
        )
        self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Apply Rename Method',
            command=self.apply_method_rename,
        )
        self.current_context_menu.add_command(
            label='Apply Move Method',
            command=self.apply_method_move,
        )
        self.current_context_menu.add_command(
            label='Apply Add Parameter',
            command=self.apply_method_add_parameter,
        )
        self.current_context_menu.add_command(
            label='Apply Remove Parameter',
            command=self.apply_method_remove_parameter,
        )
        self.current_context_menu.add_command(
            label='Apply Extract Method',
            command=self.apply_method_extract,
        )
        self.current_context_menu.add_command(
            label='Apply Inline Method',
            command=self.apply_method_inline,
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
        self.application.run_code(selected_text)

    def open_implementors_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
            )
            return
        self.application.open_implementors_dialog(method_symbol=selector)

    def open_senders_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
            )
            return
        self.application.open_senders_dialog(method_symbol=selector)

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
                add_parameter_result = self.gemstone_session_record.apply_method_add_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    parameter_name,
                    default_argument_source,
                )
            else:
                add_parameter_result = self.gemstone_session_record.preview_method_add_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    parameter_name,
                    default_argument_source,
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
                remove_parameter_result = self.gemstone_session_record.apply_method_remove_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    overwrite_new_method=overwrite_new_method,
                    rewrite_source_senders=rewrite_source_senders,
                )
            else:
                remove_parameter_result = self.gemstone_session_record.preview_method_remove_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    rewrite_source_senders=rewrite_source_senders,
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
        selection_start_offset = self.text_offset_for_index(
            selection_start_index
        )
        selection_end_offset = self.text_offset_for_index(selection_end_index)
        if selection_start_offset <= selection_end_offset:
            return (selection_start_offset, selection_end_offset)
        return (selection_end_offset, selection_start_offset)

    def selector_from_words(self, text):
        words = re.findall(r'[A-Za-z0-9]+', text)
        if not words:
            return 'extractedPart'
        capitalized_words = ''.join(
            word[0:1].upper() + word[1:]
            for word in words
            if word
        )
        if not capitalized_words:
            return 'extractedPart'
        selector = 'extracted%s' % capitalized_words
        normalized_selector = re.sub(r'[^A-Za-z0-9_]', '', selector)
        if not normalized_selector:
            return 'extractedPart'
        if normalized_selector[0].isdigit():
            normalized_selector = 'extracted%s' % normalized_selector
        return (
            normalized_selector[0].lower()
            + normalized_selector[1:]
        )

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
                is_already_inferred = (
                    identifier_name in inferred_argument_names
                )
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
            base_selector = self.selector_from_words(
                'compute %s' % variable_name
            )
        else:
            sends = first_statement.get('sends', [])
            if sends:
                base_selector = self.selector_from_words(
                    sends[0].get('selector', '')
                )
            else:
                base_selector = self.selector_from_words(statement_source)
        if not inferred_argument_names:
            return base_selector
        keyword_tokens = ['%s:' % base_selector]
        for argument_name in inferred_argument_names[1:]:
            keyword_token = (
                re.sub(r'[^A-Za-z0-9_]', '', argument_name) or 'with'
            )
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
                (
                    'Selection must fully cover one or more '
                    'top-level statements.'
                )
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
            self.text_editor.tag_add("smalltalk_keyword", f"1.0 + {start} chars", f"1.0 + {end} chars")

        for match in re.finditer(r'".*?"', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_comment", f"1.0 + {start} chars", f"1.0 + {end} chars")

        for match in re.finditer(r'\'.*?\'', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_string", f"1.0 + {start} chars", f"1.0 + {end} chars")

    def on_key_release(self, event):
        text = self.text_editor.get("1.0", tk.END)
        self.apply_syntax_highlighting(text)

    def refresh(self, source, mark=None):
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", source)
        if mark is not None and mark >= 0:
            position = self.text_editor.index(f"1.0 + {mark-1} chars")
            self.text_editor.tag_add("highlight", position, f"{position} + 1c")
        self.apply_syntax_highlighting(source)
        

class EditorTab(tk.Frame):
    def __init__(self, parent, browser_window, method_editor, tab_key):
        super().__init__(parent)
        self.browser_window = browser_window
        self.method_editor = method_editor
        self.tab_key = tab_key

        # Create CodePanel instance
        self.code_panel = CodePanel(
            self,
            self.browser_window.application,
            tab_key=tab_key,
        )
        self.code_panel.grid(row=0, column=0, sticky='nsew')

        # Configure the grid weights for resizing
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.repopulate()

    def open_tab_menu(self, event):
        return None

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


class ObjectInspector(ttk.Frame):
    def __init__(self, parent, an_object=None, values=None):
        super().__init__(parent)

        if not values:
            values = self.inspect_object(an_object)

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

    def inspect_object(self, an_object):
        try:
            is_class = an_object.isBehavior().to_py
        except GemstoneError:
            is_class = False
        if is_class:
            return self.inspect_class(an_object)
        return self.inspect_instance(an_object)

    def inspect_instance(self, an_object):
        # AI: Regular instances expose their instance variables via instVarNamed:.
        values = {}
        for i, instvar_name in enumerate(an_object.gemstone_class().allInstVarNames(), start=1):
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
        except GemstoneError:
            pass
        for i, instvar_name in enumerate(an_object.gemstone_class().allInstVarNames(), start=1):
            try:
                values[instvar_name.to_py] = an_object.instVarAt(i)
            except GemstoneError:
                pass
        return values

    def on_item_double_click(self, event):
        selected_item = self.treeview.focus()
        if selected_item:
            index = self.treeview.index(selected_item)
            value = self.actual_values[index]
            tab_label = f"Inspector: {self.treeview.item(selected_item, 'values')[0]}"
            for tab_id in self.master.tabs():
                if self.master.tab(tab_id, 'text') == tab_label:
                    self.master.select(tab_id)
                    return
            try:
                new_tab = ObjectInspector(self.master, an_object=value)
            except GemstoneError as e:
                messagebox.showerror('Inspector', f'Cannot inspect this object:\n{e}')
                return
            self.master.add(new_tab, text=tab_label)
            self.master.select(new_tab)                



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
        
        self.debug_session = GemstoneDebugSession(self.exception)
        self.stack_frames = self.debug_session.call_stack()
        
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
        if self.application.debugger_tab is self:
            self.application.debugger_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
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
        self.close_button = ttk.Button(
            self,
            text='Close Debugger',
            command=self.dismiss,
        )
        self.close_button.pack(anchor='e', padx=5, pady=5)
        
            
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
